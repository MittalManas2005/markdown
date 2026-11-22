"""Report job: one status comment per run on the issue (or PR), with a machine-readable marker (ADR-004)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .common import log, run

ART = Path("artifacts")


def round_outputs(needs: dict, name: str) -> dict:
    job = needs.get(name) or {}
    return {"result": job.get("result", "skipped"), **(job.get("outputs") or {})}


def p1_questions() -> list[str]:
    qs = []
    for spec in sorted(ART.glob("*-r1-build/spec.md")):
        for line in spec.read_text().splitlines():
            if line.startswith("| Q-") and "| P1 |" in line.replace("|P1|", "| P1 |"):
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 2:
                    qs.append(f"**{cells[0]}**: {cells[1]}")
    return qs


def main() -> int:
    needs = json.loads(os.environ["NEEDS_JSON"])
    repo, run_id = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"]
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    gate = (needs.get("gate") or {}).get("outputs") or {}
    mode, variant = gate.get("mode", ""), gate.get("variant", "pipeline")
    target = gate.get("pr") if mode == "review-only" else gate.get("issue")
    rows, state, pr = [], "error", ""
    if mode == "review-only":
        ro = round_outputs(needs, "review_only")
        state = {"approve": "approved", "request_changes": "changes_requested"}.get(ro.get("verdict", ""), "error")
        rows.append(f"| review-only | — | — | {ro.get('verdict') or ro['result']} |")
    else:
        for i in (1, 2, 3):
            r = round_outputs(needs, f"round{i}")
            if r["result"] == "skipped" and not r.get("build_status"):
                continue
            pr = r.get("pr") or pr
            rows.append(f"| {i} | {r.get('build_status') or r['result']} | {r.get('ci') or '—'} | {r.get('verdict') or '—'} |")
            bs, ci, verdict = r.get("build_status"), r.get("ci"), r.get("verdict")
            if bs == "needs_input":
                state = "needs_input"
            elif bs and bs != "ready":
                state = "stopped"
            elif ci and ci != "success":
                state = "stopped_ci"
            elif verdict == "approve":
                state = "approved"
            elif verdict == "request_changes":
                state = "review_rounds_used_up" if i == 3 else "changes_requested"
            elif verdict == "error":
                state = "review_error"
    marker = json.dumps({"run_id": run_id, "state": state, "variant": variant, "mode": mode})
    lines = [f"### AutoSE run — {state.replace('_', ' ')}", "",
             f"Run: {run_url} · mode `{mode}` · variant `{variant}`", ""]
    if pr:
        lines += [f"Pull request: https://github.com/{repo}/pull/{pr}", ""]
    lines += ["| round | build (stages 1–4) | CI (stage 5) | review (stage 6) |", "|---|---|---|---|", *rows, ""]
    if state == "needs_input":
        qs = p1_questions()
        lines += ["The Requirements stage needs a maintainer decision before it can continue:", ""]
        lines += [f"- {q}" for q in qs] or ["- (see `spec.md` in the run artifacts)"]
        lines += ["", "Reply with a comment starting with `/autose` followed by your answer to continue."]
    if state == "approved":
        lines += ["The independent reviewer approved. **A maintainer decides whether to merge.**"]
    lines += ["", f"<!-- autose:status {marker} -->"]
    body = Path("status_comment.md")
    body.write_text("\n".join(lines) + "\n")
    if target:
        proc = run(["gh", "issue", "comment", str(target), "--repo", repo, "--body-file", str(body)])
        if proc.returncode != 0:
            log(f"could not comment: {proc.stderr[:300]}")
    log(body.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
