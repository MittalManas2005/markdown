"""Review job (stage 6): independent reviewer (ADR-008).

The reviewer agent receives ONLY: the issue, the diff, and the repository at the PR head.
This job never downloads build artifacts and never passes the PR description to the agent.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable

from . import config
from .claude_runner import AgentEnvironmentError, AgentResult, run_agent
from .common import gh_output, git_exclude, log, run
from .gate import ALLOWED_ASSOC, has_write

OUT = Path(os.environ.get("AUTOSE_OUT", ".autose_review"))

VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "target_stage", "summary", "verified", "findings"],
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "request_changes"]},
        "target_stage": {"type": "string", "enum": ["none", "design", "implementation"]},
        "summary": {"type": "string"},
        "verified": {"type": "array", "items": {"type": "string"}},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "file", "issue", "evidence"],
                "properties": {
                    "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
                    "file": {"type": "string"},
                    "line": {"type": ["integer", "null"]},
                    "issue": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
    },
}


def ran_test_suite(commands: list[dict] | None) -> bool:
    """True if the reviewer itself ran unittest and it passed, according to its session transcript."""
    return any("python -m unittest" in c["command"] and c["ok"] and "FAILED (" not in c["output_tail"]
               for c in commands or [])


def validate(v: dict | None, commands: list[dict] | None) -> list[str]:
    if not isinstance(v, dict):
        return ["no structured verdict returned"]
    errs = []
    if v.get("verdict") == "approve" and not ran_test_suite(commands):
        errs.append("approve requires evidence that the reviewer ran the tests and they passed "
                    "(no passing `python -m unittest` command in its session transcript)")
    serious = [f for f in v.get("findings", []) if f.get("severity") in ("blocker", "major")]
    if v.get("verdict") == "request_changes":
        if not serious:
            errs.append("request_changes needs at least one blocker/major finding")
        if v.get("target_stage") not in ("design", "implementation"):
            errs.append("request_changes must name target_stage design or implementation")
        if any(not str(f.get("evidence", "")).strip() for f in serious):
            errs.append("every blocker/major finding needs evidence")
    if v.get("verdict") == "approve":
        if not v.get("verified"):
            errs.append("approve must list what was verified")
        if any(f.get("severity") == "blocker" for f in v.get("findings", [])):
            errs.append("cannot approve with a blocker finding")
    return errs


def render_commands(commands: list[dict] | None) -> str:
    if commands is None:
        return "- (no session transcript found)"
    if not commands:
        return "- (none)"
    mark = {True: "denied", False: ""}
    lines = []
    for c in commands:
        status = mark[c["denied"]] or ("ok" if c["ok"] else "failed")
        cmd = c["command"].replace("`", "'").replace("\n", " ")
        lines.append(f"- `{cmd[:160]}` ({status})")
    return "\n".join(lines)


def render(v: dict, pr: str, issue: str, rnd: int, model: str, commands: list[dict] | None = None) -> str:
    finding_rows = "\n".join(
        f"| {f['severity']} | `{f['file']}`{(':' + str(f['line'])) if f.get('line') else ''} | {f['issue']} | {f['evidence']} |"
        for f in v["findings"]) or "| — | — | — | — |"
    verified = "\n".join(f"- {x}" for x in v["verified"]) or "- (nothing listed)"
    return (f"---\nartefact: review\npr: {pr}\nissue: {issue}\nround: {rnd}\nverdict: {v['verdict']}\n"
            f"target_stage: {v['target_stage']}\nreviewer_model: {model}\n---\n\n"
            f"## AutoSE independent review (round {rnd})\n\n**Verdict: {v['verdict'].replace('_', ' ')}**"
            + (f" (back to **{v['target_stage']}**)" if v['verdict'] == 'request_changes' else "") + "\n\n"
            f"{v['summary']}\n\n### What I verified\n{verified}\n\n"
            f"### Commands I ran (from the session transcript, not self-reported)\n{render_commands(commands)}\n\n"
            "### Findings\n\n"
            f"| severity | location | issue | evidence |\n|---|---|---|---|\n{finding_rows}\n\n"
            "_The reviewer saw only the issue, the diff and the repository at this PR's head. "
            "A maintainer decides whether to merge._\n")


def maintainer_answers(comments: list[dict], writer: Callable[[str], bool]) -> list[str]:
    """The maintainer's clarifications: `/autose` comments with text, by people with write access (ADR-016).

    These are exactly the comments the gate accepts as answers. Bot comments (status reports) and agent output
    are never included, so the reviewer still sees nothing the implementing agents wrote."""
    out = []
    for c in comments:
        body = (c.get("body") or "").strip()
        user = c.get("user") or {}
        if not body.startswith("/autose") or user.get("type") == "Bot":
            continue
        if c.get("author_association") not in ALLOWED_ASSOC or not writer(user.get("login", "")):
            continue
        text = body[len("/autose"):].strip()
        if text:
            out.append(text)
    return out


def issue_markdown(number: str, data: dict, answers: list[str]) -> str:
    text = (f"# Issue #{number}: {data.get('title', '')}\n\n<untrusted_issue>\n{data.get('body') or ''}\n"
            "</untrusted_issue>\n")
    if answers:
        text += ("\n## Maintainer answers (clarifications posted on the issue; part of the requirements)\n\n"
                 + "\n".join(f"<untrusted_answers>\n{a}\n</untrusted_answers>\n" for a in answers))
    return text


def resolve_issue(pr_info: dict, given: str) -> str:
    if given:
        return given
    m = re.search(r"issue-(\d+)", pr_info.get("headRefName", ""))
    if m:
        return m.group(1)
    refs = pr_info.get("closingIssuesReferences") or []
    return str(refs[0]["number"]) if refs else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", required=True)
    ap.add_argument("--issue", default="")
    ap.add_argument("--round", type=int, default=1)
    a = ap.parse_args(argv)
    repo = os.environ["GITHUB_REPOSITORY"]
    model = config.model_for("reviewer")
    OUT.mkdir(exist_ok=True)
    git_exclude(f"{OUT.name}/")

    info = json.loads(run(["gh", "pr", "view", a.pr, "--repo", repo, "--json",
                           "number,headRefName,headRefOid,baseRefName,closingIssuesReferences"]).stdout)
    issue = resolve_issue(info, a.issue)
    if not issue:
        raise SystemExit("cannot determine which issue this PR addresses")
    data = json.loads(run(["gh", "issue", "view", issue, "--repo", repo, "--json", "number,title,body,author"]).stdout)
    comments = json.loads(run(["gh", "api", "--paginate", f"repos/{repo}/issues/{issue}/comments"]).stdout or "[]")
    answers = maintainer_answers(comments, lambda login: has_write(repo, login))
    (OUT / "issue.md").write_text(issue_markdown(issue, data, answers))
    base = info["baseRefName"]
    run(["git", "fetch", "origin", f"{base}:refs/remotes/origin/{base}"])
    mb = run(["git", "merge-base", f"origin/{base}", "HEAD"]).stdout.strip()
    (OUT / "diff.patch").write_text(run(["git", "diff", mb, "HEAD"]).stdout)

    prompt = (f"Review pull request #{a.pr} for issue #{issue}. The issue is in .autose_review/issue.md and the "
              "diff in .autose_review/diff.patch; the repository at the PR head is the current directory.")
    try:
        res = run_agent("reviewer", prompt, stage="6-review", attempt=a.round, json_schema=VERDICT_SCHEMA)
    except AgentEnvironmentError as env_err:  # never turn a broken runner into "request changes"
        log(str(env_err))
        res = AgentResult(ok=False, error=str(env_err), commands=env_err.commands)
    verdict = res.structured
    errors = validate(verdict, res.commands) if res.ok else [res.error or "reviewer failed"]
    if errors:
        log(f"invalid verdict: {errors}")
        (OUT / "review.md").write_text(f"---\nartefact: review\npr: {a.pr}\nverdict: error\n---\n\n"
                                       "## AutoSE review could not be completed\n\n" + "\n".join(f"- {e}" for e in errors)
                                       + "\n\n### Commands the reviewer ran (from the session transcript)\n"
                                       + render_commands(res.commands) + "\n")
        if isinstance(verdict, dict):
            (OUT / "rejected_verdict.json").write_text(json.dumps(verdict, indent=2))
        run(["gh", "pr", "review", a.pr, "--repo", repo, "--comment", "--body-file", str(OUT / "review.md")])
        gh_output(verdict="error", target_stage="none", issue=issue)
        return 0
    (OUT / "verdict.json").write_text(json.dumps(verdict, indent=2))
    (OUT / "review.md").write_text(render(verdict, a.pr, issue, a.round, model, res.commands))
    findings = [f for f in verdict["findings"] if f["severity"] in ("blocker", "major")]
    (OUT / "review_findings.md").write_text(
        "# Independent reviewer findings (address every item)\n\n" + verdict["summary"] + "\n\n"
        + "\n".join(f"- [{f['severity']}] {f['file']}:{f.get('line') or ''} {f['issue']} — evidence: {f['evidence']}"
                    for f in findings) + "\n")
    flag = "--approve" if verdict["verdict"] == "approve" else "--request-changes"
    posted = run(["gh", "pr", "review", a.pr, "--repo", repo, flag, "--body-file", str(OUT / "review.md")])
    posted_as = flag.lstrip("-")
    if posted.returncode != 0:  # e.g. repository setting forbids Actions approvals: still leave a visible review
        log(f"could not post {flag}: {posted.stderr.strip()[:300]}; posting as a comment review")
        run(["gh", "pr", "review", a.pr, "--repo", repo, "--comment", "--body-file", str(OUT / "review.md")])
        posted_as = "comment"
    (OUT / "posted.json").write_text(json.dumps({"posted_as": posted_as}))
    gh_output(verdict=verdict["verdict"], target_stage=verdict["target_stage"], issue=issue)
    return 0


if __name__ == "__main__":
    sys.exit(main())
