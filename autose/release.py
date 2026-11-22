"""Release job (stage 5): push the branch, open/update the PR, wait for CI. Deterministic, no LLM (ADR-001).

Runs with a GitHub App installation token (GH_TOKEN) so that the PR's events trigger upstream CI (ADR-010),
and with the job's GITHUB_TOKEN (CHECKS_TOKEN) for reading check runs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import checks
from .common import gh_output, git_exclude, log, parse_front_matter, run

OUT = Path(".autose_out")
PASSING = {"success", "neutral", "skipped"}


def gh(args: list[str], token: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, GH_TOKEN=token)
    return run(["gh", *args], env=env)


def push(branch: str, token: str, force: bool) -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    cmd = ["git", "push", url, f"HEAD:refs/heads/{branch}"] + (["--force"] if force else [])
    log(f"$ git push <app-token-url> HEAD:refs/heads/{branch}{' --force' if force else ''}")
    proc = subprocess.run(cmd, text=True, capture_output=True)  # not logged: the URL contains a token
    if proc.returncode != 0:
        raise SystemExit("git push failed: " + proc.stderr.replace(token, "***")[-1500:])


def pr_body(issue: str, rnd: int, run_url: str) -> str:
    spec_meta, spec_body = parse_front_matter((OUT / "spec.md").read_text()) if (OUT / "spec.md").exists() else ({}, "")
    design_meta, _ = parse_front_matter((OUT / "design.md").read_text()) if (OUT / "design.md").exists() else ({}, "")
    ac_lines = [ln.strip() for ln in spec_body.splitlines() if ln.strip().startswith("- AC-")]
    files = [f"`{f.get('path')}`" for f in (design_meta.get("files") or []) if isinstance(f, dict)]
    report_meta, _ = parse_front_matter((OUT / "test_report.md").read_text()) if (OUT / "test_report.md").exists() else ({}, "")
    inferred = spec_meta.get("inferred_ac_ids") or []
    return (
        f"Fixes #{issue}\n\n"
        f"Opened by **AutoSE** (round {rnd}). An independent reviewer agent reviews this PR next; "
        "**a maintainer decides whether to merge**.\n\n"
        f"### Acceptance criteria (from the Requirements stage)\n" + ("\n".join(ac_lines) or "_none listed_") + "\n\n"
        + (f"> Inferred criteria for the maintainer to confirm: {', '.join(map(str, inferred))}\n\n" if inferred else "")
        + f"### Files changed (planned by the Design stage)\n{', '.join(files) or '_see diff_'}\n\n"
        f"### Tests\nAutoSE test stage: {report_meta.get('result', 'n/a')}; "
        f"tests run: {report_meta.get('tests_ran', 'n/a')} (base: {report_meta.get('base_tests', 'n/a')}).\n\n"
        f"Artifacts (spec, design, diff, test report): {run_url}\n"
    )


def wait_for_ci(sha: str, token: str, appear_timeout: int = 420, total_timeout: int = 2100) -> tuple[str, list]:
    repo = os.environ["GITHUB_REPOSITORY"]
    start = time.time()
    runs: list = []
    while time.time() - start < total_timeout:
        proc = gh(["api", f"repos/{repo}/commits/{sha}/check-runs?per_page=100"], token)
        try:
            runs = json.loads(proc.stdout).get("check_runs", [])
        except (json.JSONDecodeError, AttributeError):
            runs = []
        if not runs and time.time() - start > appear_timeout:
            return "no-ci", []
        if runs and all(r.get("status") == "completed" for r in runs):
            bad = [r for r in runs if r.get("conclusion") not in PASSING]
            return ("failure" if bad else "success"), runs
        time.sleep(20)
    return "timeout", runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--variant", default="pipeline")
    ap.add_argument("--base-sha", required=True)
    a = ap.parse_args(argv)
    token, checks_token = os.environ["GH_TOKEN"], os.environ["CHECKS_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    branch = f"autose/issue-{a.issue}" + ("-single" if a.variant == "single" else "")
    # The downloaded artifacts live in .autose_out/ inside the checkout: they must never be committed
    # (the PR branch holds only code and tests, ADR-004; artifacts would leak reasoning to the reviewer, ADR-003).
    git_exclude(f"{OUT}/")
    run(["git", "config", "user.name", "autose-release[bot]"])
    run(["git", "config", "user.email", "autose-release@users.noreply.github.com"])

    if a.round == 1:
        # A fresh attempt: the branch is the base commit plus the full change (replaces any earlier attempt).
        run(["git", "checkout", "-B", branch, a.base_sha])
        patch, force = OUT / "diff.patch", True
    else:
        run(["git", "fetch", "origin", f"{branch}:refs/remotes/origin/{branch}"])
        run(["git", "checkout", "-B", branch, f"origin/{branch}"])
        patch, force = OUT / "round.patch", False
    if not patch.exists() or not patch.read_text().strip():
        raise SystemExit(f"{patch} is missing or empty")
    applied = run(["git", "apply", "--index", "--whitespace=nowarn", str(patch)])
    if applied.returncode != 0:
        raise SystemExit("patch does not apply: " + applied.stderr[-1500:])
    guard = checks.diff_guard(Path("."), a.base_sha, checks.changed_files(Path("."), a.base_sha))
    if not guard.ok:  # defence in depth: never push a change that breaks the guard
        raise SystemExit("diff guard rejected the change at release: " + "; ".join(guard.reasons))
    title = json.loads((OUT / "issue.json").read_text()).get("title", "")
    run(["git", "commit", "-m", f"AutoSE round {a.round}: {title} (#{a.issue})"])
    push(branch, token, force)
    sha = run(["git", "rev-parse", "HEAD"]).stdout.strip()

    body_file = OUT / "pr_body.md"
    body_file.write_text(pr_body(a.issue, a.round, run_url))
    existing = gh(["pr", "list", "--repo", repo, "--head", branch, "--state", "open", "--json", "number"], token)
    numbers = [str(p["number"]) for p in json.loads(existing.stdout or "[]")]
    if numbers:
        pr = numbers[0]
        gh(["pr", "edit", pr, "--repo", repo, "--body-file", str(body_file)], token)
    else:
        created = gh(["pr", "create", "--repo", repo, "--base", "main", "--head", branch,
                      "--title", f"AutoSE: {title} (#{a.issue})"[:250], "--body-file", str(body_file)], token)
        if created.returncode != 0:
            raise SystemExit("could not open the PR: " + created.stderr[-1000:])
        pr = created.stdout.strip().rstrip("/").split("/")[-1]
    pr_url = f"https://github.com/{repo}/pull/{pr}"
    log(f"PR {pr_url} at {sha}; waiting for CI")

    ci, runs = wait_for_ci(sha, checks_token)
    rows = "\n".join(f"| {r.get('name')} | {r.get('status')} | {r.get('conclusion')} |" for r in runs) or "| — | — | — |"
    (OUT / "pr.md").write_text(
        f"---\nartefact: pr\nissue: {a.issue}\nround: {a.round}\nbranch: {branch}\npr: {pr}\n"
        f"pr_url: {pr_url}\nhead_sha: {sha}\nci: {ci}\n---\n\n# Release (stage 5)\n\n"
        f"PR: {pr_url}\n\n## PR description\n\n{body_file.read_text()}\n\n"
        f"## CI check runs on {sha}\n\n| check | status | conclusion |\n|---|---|---|\n{rows}\n\n"
        f"## AutoSE stage check: the pull request is open and CI passes\n\n"
        f"Result: **{'PASS' if ci == 'success' else 'FAIL'}** (CI: {ci})\n")
    (OUT / "release.json").write_text(json.dumps({"pr": pr, "pr_url": pr_url, "head_sha": sha, "ci": ci}, indent=2))
    gh_output(pr=pr, head_sha=sha, ci=ci)
    return 0


if __name__ == "__main__":
    sys.exit(main())
