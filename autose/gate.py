"""Gate job: who may start a run, and in which mode (ADR-010). Deterministic; reads the event file only."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .common import gh_output, log, run

ALLOWED_ASSOC = {"OWNER", "MEMBER", "COLLABORATOR"}
ALLOWED_PERMISSION = {"admin", "maintain", "write"}
MARKER = re.compile(r"<!-- autose:status (\{.*?\}) -->")


def gh_json(args: list[str]):
    proc = run(["gh", *args])
    if proc.returncode != 0:
        log(f"gh failed: {proc.stderr.strip()[:300]}")
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def has_write(repo: str, login: str) -> bool:
    data = gh_json(["api", f"repos/{repo}/collaborators/{login}/permission"])
    perm = (data or {}).get("permission", "")
    log(f"sender {login} permission: {perm or 'unknown'}")
    return perm in ALLOWED_PERMISSION


def same_repo_pr(repo: str, pr: str) -> bool:
    """Review only PRs whose branch lives in this repository: only maintainers and the App can push there.

    A PR from another fork could change packaging files that `pip install` runs in the review job."""
    data = gh_json(["api", f"repos/{repo}/pulls/{pr}"]) or {}
    head_repo = ((data.get("head") or {}).get("repo") or {}).get("full_name", "")
    log(f"PR #{pr} head repository: {head_repo or 'unknown'}")
    return head_repo == repo


def last_status(repo: str, issue: str) -> dict:
    comments = gh_json(["api", "--paginate", f"repos/{repo}/issues/{issue}/comments"]) or []
    for c in reversed(comments):
        if (c.get("user") or {}).get("type") != "Bot":
            continue
        m = MARKER.search(c.get("body") or "")
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                return {}
    return {}


def decide(event_name: str, event: dict, repo: str, sha: str) -> dict:
    d = {"run": "false", "mode": "", "issue": "", "pr": "", "variant": "pipeline", "reviewer_model": "sonnet",
         "prev_run_id": "", "base_sha": sha, "reason": ""}
    sender = (event.get("sender") or {}).get("login", "")
    if event_name == "workflow_dispatch":
        inp = event.get("inputs") or {}
        num = str(inp.get("number", "")).strip()
        if not num.isdigit():
            d["reason"] = "workflow_dispatch: number must be an issue or PR number"
            return d
        mode = inp.get("mode", "full")
        if mode == "review-only" and not same_repo_pr(repo, num):
            d["reason"] = f"PR #{num} is not a branch of {repo}; AutoSE reviews only branches in this repository"
            return d
        d.update(run="true", mode=mode, variant=inp.get("variant", "pipeline"),
                 reviewer_model=inp.get("reviewer_model", "sonnet"))
        d["pr" if mode == "review-only" else "issue"] = num
        d["reason"] = f"manual dispatch by {sender}"
        return d

    issue = event.get("issue") or {}
    number = str(issue.get("number", ""))
    if event_name == "issues":
        if (event.get("label") or {}).get("name") != "autose":
            d["reason"] = "label is not 'autose'"
            return d
        if not has_write(repo, sender):
            d["reason"] = f"{sender} lacks write access"
            return d
        d.update(run="true", mode="full", issue=number, reason=f"label 'autose' added by {sender}")
        return d

    if event_name == "issue_comment":
        comment = event.get("comment") or {}
        body = (comment.get("body") or "").strip()
        user = comment.get("user") or {}
        if not body.startswith("/autose") or user.get("type") == "Bot":
            d["reason"] = "not an /autose command from a person"
            return d
        if comment.get("author_association") not in ALLOWED_ASSOC or not has_write(repo, user.get("login", "")):
            d["reason"] = f"{user.get('login')} is not allowed to run AutoSE"
            return d
        if "pull_request" in issue:  # GitHub includes this key only when the comment is on a PR
            if not same_repo_pr(repo, number):
                d["reason"] = f"PR #{number} is not a branch of {repo}; AutoSE reviews only branches in this repository"
                return d
            d.update(run="true", mode="review-only", pr=number, reason=f"/autose on PR by {user.get('login')}")
            return d
        status = last_status(repo, number)
        d.update(run="true", issue=number, variant=status.get("variant", "pipeline"))
        if status.get("state") == "needs_input" and status.get("run_id"):
            answer = body[len("/autose"):].strip()
            Path(".autose_gate").mkdir(exist_ok=True)
            Path(".autose_gate/answers_raw.md").write_text(
                f"Answer from @{user.get('login')} ({comment.get('html_url', '')}):\n\n{answer}\n")
            d.update(mode="resume", prev_run_id=str(status["run_id"]),
                     reason=f"maintainer answer to NEEDS_INPUT from run {status['run_id']}")
        else:
            d.update(mode="full", reason=f"/autose on issue by {user.get('login')}")
        return d

    d["reason"] = f"unsupported event {event_name}"
    return d


def main() -> int:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    d = decide(os.environ["GITHUB_EVENT_NAME"], event, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"])
    log(f"gate decision: {d}")
    gh_output(**d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
