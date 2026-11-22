"""Build job: stages 1-4 as a deterministic state machine (ADR-002, ADR-007).

Usage (inside a checkout of the fork, after `pip install -e '.[testing]' flake8`):
    python -m autose.orchestrator --issue 3 --round 1 --start-stage requirements \
        --base-sha <sha> --variant pipeline
Inputs it expects in .autose_out/: issue.json (from `gh issue view --json`), and for later rounds / resume:
spec.md, design.md, review_findings.md, prev_spec.md, answers.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import checks, config
from .claude_runner import AgentEnvironmentError, run_agent
from .common import RunState, gh_output, git_exclude, log, out_path, run

REPO = Path(".").resolve()


class Stop(Exception):
    def __init__(self, stage: int, status: str, reason: str):
        super().__init__(reason)
        self.stage, self.status, self.reason = stage, status, reason


def append_check_section(artifact: Path, title: str, ok: bool, reasons: list[str]) -> None:
    """Every stage explains its check result in its own artifact (assignment: explain why, then stop)."""
    text = artifact.read_text() if artifact.exists() else ""
    body = "\n".join(f"- {r}" for r in reasons) or "- all checks passed"
    artifact.write_text(f"{text.rstrip()}\n\n## AutoSE stage check: {title}\n\nResult: **{'PASS' if ok else 'FAIL'}**\n\n{body}\n")


def write_feedback(name: str, title: str, reasons: list[str]) -> None:
    out_path(name).write_text(f"# {title}\n\n" + "\n\n".join(reasons) + "\n")


class Build:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.out = Path(config.OUT_DIR)
        self.out.mkdir(exist_ok=True)
        git_exclude(f"{config.OUT_DIR}/", REPO)  # artifacts are never part of the change (ADR-004)
        self.start_sha = run(["git", "rev-parse", "HEAD"], cwd=REPO).stdout.strip()
        self.state = RunState(self.out / "run_state.json", issue=args.issue, round=args.round,
                              variant=args.variant, base_sha=args.base_sha, start_sha=self.start_sha,
                              start_stage=args.start_stage)
        self.ac_ids: list[str] = []
        self.render_issue()
        self.base_count = self.state.data.get("base_tests") or self.count_base_tests()
        self.state.set(base_tests=self.base_count)

    # ------------------------------------------------------------ setup
    def render_issue(self) -> None:
        data = json.loads((self.out / "issue.json").read_text())
        author = (data.get("author") or {}).get("login", "unknown")
        text = (f"# Issue #{data.get('number')}: {data.get('title', '')}\n\nAuthor: {author}\n\n"
                f"<untrusted_issue>\n{data.get('body') or ''}\n</untrusted_issue>\n")
        (self.out / "issue.md").write_text(text)
        answers = self.out / "answers_raw.md"
        if answers.exists():
            (self.out / "answers.md").write_text(f"<untrusted_answers>\n{answers.read_text()}\n</untrusted_answers>\n")

    def count_base_tests(self) -> int:
        """Count tests on the base commit in this job's environment (ADR-007: same-environment comparison)."""
        tmp = Path(self.out, "basecount")
        run(["git", "worktree", "add", "--detach", str(tmp), self.args.base_sha], cwd=REPO)
        try:
            return checks.base_test_count(tmp)
        finally:
            run(["git", "worktree", "remove", "--force", str(tmp)], cwd=REPO)

    # ------------------------------------------------------------ stage 1
    def stage_requirements(self) -> None:
        update = (self.out / "prev_spec.md").exists() and (self.out / "answers.md").exists()
        prompt = (f"Write the spec for issue #{self.args.issue} (base commit {self.args.base_sha}). "
                  + ("This is UPDATE MODE: use .autose_out/prev_spec.md and .autose_out/answers.md. "
                     if update else "")
                  + "Inputs and output are described in your instructions.")
        res = run_agent("requirements", prompt, stage="1-requirements", attempt=1)
        spec = self.out / "spec.md"
        if not spec.exists():
            spec.write_text("---\nstatus: FAIL\n---\n# Spec not written\n")
            raise Stop(1, "failed", f"requirements agent wrote no spec.md ({res.error or res.subtype})")
        chk = checks.check_spec(spec.read_text())
        self.state.check(1, "spec testable", chk.ok, chk.reasons)
        append_check_section(spec, "all acceptance criteria are testable", chk.ok, chk.reasons)
        status = chk.data.get("status", "")
        if status == "NEEDS_INPUT" and chk.reasons and "maintainer input" in chk.reasons[0]:
            self.state.set(blocking_questions=chk.data["meta"].get("blocking_questions"))
            raise Stop(1, "needs_input", chk.reasons[0])
        if not chk.ok:
            raise Stop(1, "failed", "; ".join(chk.reasons))
        self.ac_ids = chk.data["ac_ids"]
        self.state.set(ac_ids=self.ac_ids, inferred_ac_ids=chk.data["inferred"])
        self.state.transition("requirements", "design", "spec check passed")

    def load_spec(self) -> None:
        chk = checks.check_spec((self.out / "spec.md").read_text())
        if not chk.ok:
            raise Stop(1, "failed", "spec.md from the previous round no longer passes its check")
        self.ac_ids = chk.data["ac_ids"]

    # ------------------------------------------------------------ stage 2
    def stage_design(self, extra_feedback: str | None = None) -> None:
        if extra_feedback:
            write_feedback("test_feedback.md", "Tests kept failing with the previous design", [extra_feedback])
        design = self.out / "design.md"
        for attempt in range(1, config.BUDGETS["design_attempts"] + 1):
            if design.exists():
                design.rename(self.out / f"design.attempt{attempt - 1}.md")
            prompt = (f"Write the design for issue #{self.args.issue}. "
                      "Read .autose_out/spec.md and autose/context/ARCHITECTURE.md first.")
            res = run_agent("design", prompt, stage="2-design", attempt=attempt)
            if not design.exists():
                reasons = [f"design agent wrote no design.md ({res.error or res.subtype})"]
            else:
                chk = checks.check_design(design.read_text(), REPO)
                reasons = chk.reasons
                self.state.check(2, "design names files and functions", chk.ok, chk.reasons)
                append_check_section(design, "names the files and functions to change", chk.ok, chk.reasons)
                if chk.ok:
                    self.state.transition("design", "implementation", "design check passed")
                    return
            write_feedback("design_feedback.md", "Your previous design failed the pipeline's check", reasons)
        raise Stop(2, "failed", "design check failed after retries: " + "; ".join(reasons))

    # ------------------------------------------------------------ stages 3 + 4
    def impl_test_loop(self) -> tuple[bool, str]:
        run_implementer, run_tester = True, True
        last = ""
        for attempt in range(1, config.BUDGETS["impl_attempts"] + 1):
            if run_implementer:
                res = run_agent("implementer", f"Implement issue #{self.args.issue} as designed.",
                                stage="3-implementation", attempt=attempt)
                if not res.ok and res.error:
                    log(res.error)
                changes = checks.changed_files(REPO, self.args.base_sha)
                guard = checks.diff_guard(REPO, self.args.base_sha, changes)
                build = checks.check_build(REPO) if guard.ok else checks.Check(False, ["skipped: diff guard failed"])
                spell3 = checks.check_spelling(REPO, self.args.base_sha, [
                    p for s, p in changes if s != "D" and p.startswith(("markdown/", "docs/"))])
                ok3 = guard.ok and build.ok and spell3.ok
                reasons3 = guard.reasons + ([] if build.ok else build.reasons) + spell3.reasons
                self.state.check(3, "code builds (guard + compile + flake8)", ok3, reasons3)
                checks.write_patch(REPO, self.args.base_sha, self.out / "diff.patch")
                self.write_stage3_report(changes, ok3, reasons3)
                if not ok3:
                    last = "Stage 3 check failed:\n" + "\n".join(reasons3)
                    write_feedback("impl_feedback.md", "Your previous attempt failed the build check", reasons3)
                    self.state.transition("implementation", "implementation", "build check failed; retry")
                    continue
                self.state.transition("implementation", "testing", "build check passed")
            if run_tester:
                run_agent("tester", f"Write acceptance tests for issue #{self.args.issue}.",
                          stage="4-testing", attempt=attempt)
            chk = checks.check_tests(REPO, self.args.base_sha, self.ac_ids, self.base_count)
            lint = checks.check_build(REPO)  # the new tests must also satisfy flake8
            spell4 = checks.check_spelling(REPO, self.args.base_sha, [
                p for s, p in checks.changed_files(REPO, self.args.base_sha) if s != "D" and p.startswith("tests/")])
            ok4 = chk.ok and lint.ok and spell4.ok
            reasons4 = chk.reasons + ([] if lint.ok else lint.reasons) + spell4.reasons
            self.state.check(4, "new and existing tests pass", ok4, reasons4)
            checks.write_patch(REPO, self.args.base_sha, self.out / "diff.patch")
            self.write_test_report(chk, ok4, reasons4)
            if ok4:
                self.state.transition("testing", "release", "all new and existing tests pass")
                return True, ""
            last = "Stage 4 check failed:\n" + "\n".join(reasons4)
            if chk.kind in ("coverage", "vacuous") or (chk.ok and lint.ok and not spell4.ok):
                write_feedback("test_feedback.md", "Your tests failed the pipeline's check", reasons4)
                run_implementer, run_tester = False, True
                self.state.transition("testing", "testing", f"{chk.kind or 'spelling'}: tester retries")
            else:
                write_feedback("impl_feedback.md", "Tests fail with your implementation", reasons4)
                run_implementer, run_tester = True, False
                self.state.transition("testing", "implementation", "tests fail: back to stage 3")
        return False, last

    def write_stage3_report(self, changes, ok: bool, reasons: list[str]) -> None:
        lines = [f"- `{s}` {p}" for s, p in changes] or ["- (no changes)"]
        p = self.out / "build_check.md"
        p.write_text("# Stage 3: implementation\n\nChanged files:\n" + "\n".join(lines) + "\n")
        append_check_section(p, "the code builds (diff guard, compile, import, flake8)", ok, reasons)

    def write_test_report(self, chk: checks.Check, ok: bool, reasons: list[str]) -> None:
        d = chk.data
        cov = d.get("ac_coverage") or {}
        rows = "\n".join(f"| {ac} | {'yes' if hit else 'NO'} |" for ac, hit in cov.items()) or "| — | — |"
        fob = d.get("fails_on_base") or {}
        text = (
            "---\nartefact: test_report\n"
            f"issue: {self.args.issue}\nround: {self.args.round}\nresult: {'PASS' if ok else 'FAIL'}\n"
            f"tests_ran: {d.get('tests_ran', 'n/a')}\nbase_tests: {self.base_count}\n---\n\n"
            "# Test report\n\n## Acceptance criteria → tests\n\n| AC | covered by a new test |\n|---|---|\n"
            f"{rows}\n\nTest files: {', '.join(d.get('test_files') or []) or 'none'}\n\n"
            "## New tests on the base commit (must fail)\n\n"
            f"Failed on base: **{fob.get('failed', 'n/a')}**\n\n```\n{fob.get('tail', '')}\n```\n\n"
            f"## Full suite\n\n```\n{d.get('suite_tail', 'not run')}\n```\n"
        )
        notes = self.out / "tester_notes.md"
        if notes.exists():
            text += "\n## Tester notes\n\n" + notes.read_text()
        p = self.out / "test_report.md"
        p.write_text(text)
        append_check_section(p, "all new and existing tests pass", ok, reasons)

    # ------------------------------------------------------------ pipeline variant
    def run_pipeline(self) -> None:
        stage = self.args.start_stage
        if stage == "requirements":
            self.stage_requirements()
            stage = "design"
        else:
            self.load_spec()
        if stage == "design":
            self.stage_design()
        escalations = config.BUDGETS["design_escalations"]
        while True:
            ok, reason = self.impl_test_loop()
            if ok:
                return
            if escalations == 0:
                raise Stop(4, "failed", reason)
            escalations -= 1
            self.state.transition("testing", "design", "tests kept failing: back to design once")
            self.stage_design(extra_feedback=reason)

    # ------------------------------------------------------------ single-agent variant (experiment E1)
    def run_single(self) -> None:
        session = None
        feedback: list[str] = []
        for attempt in range(1, config.BUDGETS["impl_attempts"] + 1):
            if feedback:
                write_feedback("feedback.md", "The pipeline's checks rejected your previous attempt", feedback)
            prompt = (f"Resolve issue #{self.args.issue} (base commit {self.args.base_sha}) following all four "
                      "steps." if session is None else
                      "The pipeline's checks rejected your work. Read .autose_out/feedback.md and fix exactly that.")
            res = run_agent("single", prompt, stage="1-4-single", attempt=attempt, resume=session)
            session = res.session_id or session
            spec = self.out / "spec.md"
            if not spec.exists():
                feedback = ["spec.md was not written"]
                continue
            chk1 = checks.check_spec(spec.read_text())
            self.state.check(1, "spec testable", chk1.ok, chk1.reasons)
            if chk1.data.get("status") == "NEEDS_INPUT" and "maintainer input" in (chk1.reasons or [""])[0]:
                raise Stop(1, "needs_input", chk1.reasons[0])
            if not chk1.ok:
                feedback = chk1.reasons
                continue
            self.ac_ids = chk1.data["ac_ids"]
            design = self.out / "design.md"
            chk2 = checks.check_design(design.read_text(), REPO) if design.exists() else checks.Check(
                False, ["design.md was not written"])
            self.state.check(2, "design names files and functions", chk2.ok, chk2.reasons)
            if not chk2.ok:
                feedback = chk2.reasons
                continue
            changes = checks.changed_files(REPO, self.args.base_sha)
            guard = checks.diff_guard(REPO, self.args.base_sha, changes)
            build = checks.check_build(REPO) if guard.ok else checks.Check(False, ["skipped: diff guard failed"])
            # Same spelling rule as the pipeline (stage 3 for code and docs, stage 4 for tests), applied at once
            # because the single agent writes code, docs and tests in one go.
            spell = checks.check_spelling(REPO, self.args.base_sha, [
                p for s, p in changes if s != "D" and p.startswith(("markdown/", "docs/", "tests/"))])
            ok3 = guard.ok and build.ok and spell.ok
            reasons3 = guard.reasons + ([] if build.ok else build.reasons) + spell.reasons
            self.state.check(3, "code builds", ok3, reasons3)
            self.write_stage3_report(changes, ok3, reasons3)
            if not ok3:
                feedback = reasons3
                continue
            chk4 = checks.check_tests(REPO, self.args.base_sha, self.ac_ids, self.base_count)
            self.state.check(4, "new and existing tests pass", chk4.ok, chk4.reasons)
            self.write_test_report(chk4, chk4.ok, chk4.reasons)
            checks.write_patch(REPO, self.args.base_sha, self.out / "diff.patch")
            if chk4.ok:
                self.state.transition("single", "release", "all checks passed")
                return
            feedback = chk4.reasons
        raise Stop(4, "failed", "single agent did not pass the checks within the retry budget: " + "; ".join(feedback))

    # ------------------------------------------------------------ entry
    def finish_ok(self) -> None:
        checks.write_patch(REPO, self.args.base_sha, self.out / "diff.patch")
        checks.write_patch(REPO, self.start_sha, self.out / "round.patch")
        self.state.set(status="ready", finished=True)
        gh_output(status="ready", stop_stage="", stop_reason="")

    def finish_stop(self, stop: Stop) -> None:
        self.state.set(status=stop.status, stop_stage=stop.stage, stop_reason=stop.reason[:2000], finished=True)
        (self.out / "STOPPED.md").write_text(
            f"# Run stopped at stage {stop.stage}\n\nStatus: **{stop.status}**\n\nReason:\n\n{stop.reason}\n")
        gh_output(status=stop.status, stop_stage=stop.stage, stop_reason=stop.reason[:200].replace("\n", " "))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue", required=True)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--start-stage", default="requirements", choices=["requirements", "design", "implementation"])
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--variant", default="pipeline", choices=["pipeline", "single"])
    args = ap.parse_args(argv)
    build = Build(args)
    try:
        if args.variant == "single":
            build.run_single()
        else:
            build.run_pipeline()
        build.finish_ok()
    except Stop as stop:
        build.finish_stop(stop)
    except AgentEnvironmentError as env_err:  # stop at once: retrying cannot fix a broken runner
        build.finish_stop(Stop(int(env_err.stage.split("-")[0]), "failed", str(env_err)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
