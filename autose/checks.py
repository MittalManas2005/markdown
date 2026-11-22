"""Deterministic stage checks (ADR-007). Code decides; agent output is only input."""
from __future__ import annotations

import ast
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .common import clean_env, parse_front_matter, run, tail

ORACLES = ("exact", "contains", "not-contains", "no-error", "raises", "property")
# A preservation AC may carry the tag inside or after the oracle brackets: "(contains, preservation)" or
# "(contains) (preservation)". Run 45008926010 stopped at stage 1 over exactly this form (the skill's examples
# and this pattern disagreed); the testability rule itself (ID, label, oracle kind, Given/when/then) is unchanged.
AC_LINE = re.compile(
    r"(AC-(?:FR|NFR|CON)-\d{3}-\d+)\s*\[(Confirmed|Inferred)\]\s*\((" + "|".join(ORACLES) + r")"
    r"(?:\s*,\s*preservation)?\)\s*(?:\(preservation\)\s*)?:?(.*)",
    re.I)


@dataclass
class Check:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    kind: str = ""  # for test-stage failures: coverage | vacuous | suite | count


# ---------------------------------------------------------------- stage 1: spec
def check_spec(text: str) -> Check:
    meta, body = parse_front_matter(text)
    if not meta:
        return Check(False, ["spec.md has no parseable YAML front matter"])
    status = str(meta.get("status", "")).upper()
    data = {"status": status, "meta": meta}
    if status == "NEEDS_INPUT":
        qs = meta.get("blocking_questions") or []
        if not qs:
            return Check(False, ["status NEEDS_INPUT but blocking_questions is empty"], data)
        return Check(False, [f"requirements need maintainer input: {', '.join(map(str, qs))}"], data)
    if status == "FAIL":
        return Check(False, ["requirements agent reported FAIL (see the spec's stage-gate section)"], data)
    if status != "PASS":
        return Check(False, [f"unknown status {status!r}"], data)
    ac_ids = [str(a) for a in (meta.get("ac_ids") or [])]
    reasons: list[str] = []
    if not ac_ids:
        reasons.append("front matter lists no ac_ids")
    found = {}
    for line in body.splitlines():
        m = AC_LINE.search(line)
        if m:
            found[m.group(1).upper()] = (m.group(3).lower(), m.group(4))
    for ac in ac_ids:
        if ac.upper() not in found:
            reasons.append(f"{ac}: not written as 'ID [label] (oracle): Given ... when ... then ...'")
            continue
        _, sentence = found[ac.upper()]
        s = sentence.lower()
        if not ("given" in s and "when" in s and "then" in s):
            reasons.append(f"{ac}: missing Given/when/then")
    frs = set(re.findall(r"^###\s+(FR-\d{3})", body, re.M))
    for fr in sorted(frs):
        if not any(a.upper().startswith(f"AC-{fr}-") for a in ac_ids):
            reasons.append(f"{fr} has no acceptance criterion")
    if not frs:
        reasons.append("no functional requirement (### FR-nnn) found")
    data["ac_ids"] = ac_ids
    data["inferred"] = [str(a) for a in (meta.get("inferred_ac_ids") or [])]
    data["oracles"] = {k: v[0] for k, v in found.items()}
    return Check(not reasons, reasons, data)


# ---------------------------------------------------------------- stage 2: design
def _symbols_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(f"{node.name}.{sub.name}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


def check_design(text: str, repo: Path) -> Check:
    meta, body = parse_front_matter(text)
    if not meta:
        return Check(False, ["design.md has no parseable YAML front matter"])
    files = meta.get("files") or []
    reasons: list[str] = []
    if not isinstance(files, list) or not files:
        return Check(False, ["design.md front matter lists no files to change"])
    named_functions = 0
    for entry in files:
        if not isinstance(entry, dict) or "path" not in entry:
            reasons.append(f"malformed files entry: {entry!r}")
            continue
        rel = str(entry["path"]).lstrip("./")
        change = str(entry.get("change", "modify")).lower()
        symbols = [str(s) for s in (entry.get("symbols") or [])]
        new_symbols = [str(s) for s in (entry.get("new_symbols") or [])]
        named_functions += len(symbols) + len(new_symbols)
        if not rel.startswith(config.ALLOWED_CHANGE_PREFIXES):
            reasons.append(f"{rel}: outside the paths AutoSE may change {config.ALLOWED_CHANGE_PREFIXES}")
        p = repo / rel
        if change == "new":
            if p.exists():
                reasons.append(f"{rel}: marked new but already exists")
            continue
        if not p.exists():
            reasons.append(f"{rel}: listed for modification but does not exist")
            continue
        if rel.endswith(".py") and symbols:
            try:
                existing = _symbols_in(p)
            except SyntaxError as e:
                reasons.append(f"{rel}: cannot parse ({e})")
                continue
            for s in symbols:
                if s not in existing:
                    reasons.append(f"{rel}: symbol {s!r} not found (use new_symbols for new ones)")
    if named_functions == 0:
        reasons.append("design names no functions/classes to change (symbols / new_symbols)")
    if "architecture.md" not in body.lower():
        reasons.append("design.md has no 'ARCHITECTURE.md vs source' section")
    return Check(not reasons, reasons, {"files": files})


# ---------------------------------------------------------------- stage 3: changes, guard, build
def stage_all(repo: Path) -> None:
    run(["git", "add", "-A", "--", "."], cwd=repo)


def changed_files(repo: Path, base: str) -> list[tuple[str, str]]:
    stage_all(repo)
    proc = run(["git", "diff", "--cached", "--name-status", "--no-renames", base], cwd=repo)
    out = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            out.append((parts[0][0], parts[-1]))
    return out


def write_patch(repo: Path, since: str, dest: Path) -> None:
    stage_all(repo)
    proc = run(["git", "diff", "--cached", "--binary", since], cwd=repo)
    dest.write_text(proc.stdout)


def _test_methods(src: str) -> set[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name.startswith("test"):
                    names.add(f"{node.name}.{sub.name}")
    return names


def diff_guard(repo: Path, base: str, changes: list[tuple[str, str]]) -> Check:
    reasons = []
    if not changes:
        return Check(False, ["no changes were made"])
    for status, path in changes:
        if not path.startswith(config.ALLOWED_CHANGE_PREFIXES):
            reasons.append(f"{path}: changes outside {config.ALLOWED_CHANGE_PREFIXES} are not allowed")
        if path.startswith("tests/") and status == "D":
            reasons.append(f"{path}: deleting test files is not allowed")
        if path.startswith("tests/") and path.endswith(".py") and status == "M":
            old = run(["git", "show", f"{base}:{path}"], cwd=repo).stdout
            new = (repo / path).read_text(encoding="utf-8")
            removed = _test_methods(old) - _test_methods(new)
            if removed:
                reasons.append(f"{path}: existing tests removed or renamed: {sorted(removed)[:5]}")
    code_changed = any(p.startswith("markdown/") for _, p in changes)
    if code_changed and not any(p == "docs/changelog.md" for _, p in changes):
        reasons.append("repository rule: changes under markdown/ need an entry in docs/changelog.md "
                       "(docs/contributing.md; enforced by the changelog-enforcer CI workflow)")
    return Check(not reasons, reasons)


def check_build(repo: Path) -> Check:
    env = clean_env()
    reasons = []
    steps = [
        (["python", "-m", "compileall", "-q", "markdown"], "compile"),
        (["python", "-c", "import markdown; markdown.markdown('# t\\n\\n*x*', extensions=['extra', 'toc'])"],
         "import + convert"),
        (["python", "-m", "flake8", "markdown", "tests"], "flake8 (repository style)"),
    ]
    logs = {}
    for cmd, name in steps:
        proc = run(cmd, cwd=repo, env=env, timeout=600)
        logs[name] = tail(proc.stdout + proc.stderr, 40)
        if proc.returncode != 0:
            reasons.append(f"{name} failed:\n{logs[name]}")
    return Check(not reasons, reasons, {"logs": logs})


# ---------------------------------------------------------------- spelling (mirrors CI's `checkspelling` job)
# Baseline runs 45008881976, 45008918900 and 45008931950 passed every test but failed CI's spell check on test
# docstrings ("attr", "NFR", "stdin"). The repository's own pyspelling tasks are run on the changed files, and
# only words that the change introduces are reported (the Markdown task flags some words already in `main`,
# because CI checks the rendered HTML instead).
SPELL_TASKS = {".py": "python", ".md": "markdown"}


def _misspelled(repo: Path, task: str, path: str) -> set[str]:
    proc = run(["python", "-m", "pyspelling", "-c", ".pyspelling.yml", "-n", task, "-S", path],
               cwd=repo, env=clean_env(), timeout=300)
    words, inside = set(), False
    for line in (proc.stdout or "").splitlines():
        if line.startswith("-" * 20):
            inside = not inside
        elif inside and line.strip() and " " not in line.strip():
            words.add(line.strip())
    return words


def spelling_available(repo: Path) -> bool:
    return (shutil.which("aspell") is not None and (repo / ".pyspelling.yml").exists()
            and run(["python", "-m", "pyspelling", "--version"], cwd=repo, env=clean_env()).returncode == 0)


def check_spelling(repo: Path, base: str, paths: list[str]) -> Check:
    targets = [p for p in paths if Path(p).suffix in SPELL_TASKS and (repo / p).is_file()]
    if not targets:
        return Check(True, [], {"spelling": "no files to check"})
    if not spelling_available(repo):
        if os.environ.get("AUTOSE_REQUIRE_SPELLING") == "1":
            return Check(False, ["the spell checker (pyspelling + aspell) is not installed on this runner"])
        return Check(True, [], {"spelling": "skipped: pyspelling or aspell not installed"})
    reasons, found = [], {}
    with tempfile.TemporaryDirectory(prefix="autose-spell-") as tmp:
        for rel in targets:
            task = SPELL_TASKS[Path(rel).suffix]
            now = _misspelled(repo, task, rel)
            before: set[str] = set()
            old = run(["git", "show", f"{base}:{rel}"], cwd=repo)
            if old.returncode == 0 and now:
                copy = Path(tmp) / rel
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_text(old.stdout)
                before = _misspelled(repo, task, str(copy))
            new = sorted(now - before)
            if new:
                found[rel] = new
                reasons.append(f"{rel}: new words rejected by the repository's spell check (CI job `checkspelling`): "
                               f"{', '.join(new)}. CI spell-checks docstrings, comments and documentation: put "
                               "identifiers, code and IDs in backticks, or use plain English words.")
    return Check(not reasons, reasons, {"misspelled": found})


# ---------------------------------------------------------------- stage 4: tests
RAN = re.compile(r"^Ran (\d+) tests?", re.M)


def run_suite(repo: Path) -> tuple[int, int, str]:
    proc = run(["python", "-m", "unittest", "discover", "tests"], cwd=repo, env=clean_env(), timeout=1200)
    text = proc.stdout + proc.stderr
    m = RAN.search(text)
    return proc.returncode, int(m.group(1)) if m else -1, text


def _ac_tokens(ac: str) -> tuple[str, str]:
    return ac.upper(), ac.lower().replace("-", "_")


def check_tests(repo: Path, base: str, ac_ids: list[str], base_count: int) -> Check:
    changes = changed_files(repo, base)
    test_files = [p for s, p in changes if p.startswith("tests/") and p.endswith(".py") and s != "D"]
    reasons: list[str] = []
    data: dict = {"test_files": test_files}
    if not test_files:
        return Check(False, ["no test files were added or changed"], data, kind="coverage")
    blob = "\n".join((repo / p).read_text(encoding="utf-8") for p in test_files)
    missing = [ac for ac in ac_ids if not any(tok in blob or tok in blob.lower() for tok in _ac_tokens(ac))]
    data["ac_coverage"] = {ac: ac not in missing for ac in ac_ids}
    if missing:
        return Check(False, [f"acceptance criteria without a test that names them: {missing}"], data,
                     kind="coverage")
    # New tests must fail on the base commit (otherwise they don't exercise the change).
    vac = fails_on_base(repo, base, test_files)
    data["fails_on_base"] = vac
    if not vac["failed"]:
        return Check(False, ["the new/changed tests all pass on the base commit, so they do not test the change"],
                     data, kind="vacuous")
    rc, count, text = run_suite(repo)
    data.update({"suite_rc": rc, "tests_ran": count, "base_tests": base_count, "suite_tail": tail(text, 80)})
    if rc != 0:
        return Check(False, ["full test suite fails:\n" + tail(text, 60)], data, kind="suite")
    if base_count > 0 and count < base_count:
        return Check(False, [f"fewer tests ran ({count}) than on the base commit ({base_count})"], data,
                     kind="count")
    return Check(True, reasons, data)


def fails_on_base(repo: Path, base: str, test_files: list[str]) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="autose-base-")) / "wt"
    run(["git", "worktree", "add", "--detach", str(tmp), base], cwd=repo)
    try:
        for rel in test_files:
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / rel, dest)
        modules = [rel[:-3].replace("/", ".") for rel in test_files]
        proc = run(["python", "-m", "unittest", *modules], cwd=tmp, env=clean_env(), timeout=600)
        return {"failed": proc.returncode != 0, "tail": tail(proc.stdout + proc.stderr, 30)}
    finally:
        run(["git", "worktree", "remove", "--force", str(tmp)], cwd=repo)


def base_test_count(repo: Path) -> int:
    _, count, _ = run_suite(repo)
    return count
