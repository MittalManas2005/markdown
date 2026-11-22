"""Static configuration: models, budgets, permissions (ADR-005, ADR-006, ADR-009)."""
from __future__ import annotations

import os

# Directory (inside the checkout, git-excluded) where a job keeps its artifacts and agent inputs.
OUT_DIR = os.environ.get("AUTOSE_OUT", ".autose_out")

# ADR-006: Haiku for the producing roles, Sonnet for the reviewer, effort medium.
# ADR-009: per-role turn caps and wall-clock limits (seconds).
ROLES: dict[str, dict] = {
    "requirements": {"model": "haiku", "effort": "medium", "max_turns": 20, "timeout": 900},
    "design": {"model": "haiku", "effort": "medium", "max_turns": 25, "timeout": 900},
    "implementer": {"model": "haiku", "effort": "medium", "max_turns": 40, "timeout": 1500},
    "tester": {"model": "haiku", "effort": "medium", "max_turns": 30, "timeout": 1200},
    "single": {"model": "haiku", "effort": "medium", "max_turns": 80, "timeout": 3000},
    "reviewer": {"model": "sonnet", "effort": "medium", "max_turns": 30, "timeout": 1500},
}

# ADR-002 / ADR-009: retry budgets inside one round.
BUDGETS = {
    "design_attempts": 2,  # first attempt + 1 retry with validator findings
    "impl_attempts": 3,  # first attempt + 2 retries (implementer <-> tester loop)
    "design_escalations": 1,  # testing -> design, once
}

# ADR-005 / ADR-009: paths an agent change may touch (diff guard).
ALLOWED_CHANGE_PREFIXES = ("markdown/", "tests/", "docs/")

# Tools denied to every agent, on top of the allowlists below.
DENY_ALWAYS = [
    "WebFetch", "WebSearch", "Task", "NotebookEdit",
    "Bash(curl *)", "Bash(wget *)", "Bash(git push *)", "Bash(gh *)", "Bash(pip *)",
]

READ = ["Read", "Grep", "Glob"]
TEST_CMDS = ["Bash(python -m unittest *)", "Bash(python -m compileall *)", "Bash(python -m flake8 *)"]


def allowed_tools(role: str, out_dir: str = OUT_DIR) -> list[str]:
    """Role -> Claude Code --allowedTools entries (path rules are relative to the checkout)."""
    out = f"./{out_dir}"
    if role == "requirements":
        return READ + [f"Edit({out}/spec.md)"]
    if role == "design":
        return READ + [f"Edit({out}/design.md)"]
    if role == "implementer":
        return READ + ["Edit(./markdown/**)", "Edit(./tests/**)", "Edit(./docs/**)"] + TEST_CMDS
    if role == "tester":
        return READ + ["Edit(./tests/**)", f"Edit({out}/tester_notes.md)", "Bash(python -m unittest *)"]
    if role == "single":
        return READ + [f"Edit({out}/**)", "Edit(./markdown/**)", "Edit(./tests/**)", "Edit(./docs/**)"] + TEST_CMDS
    if role == "reviewer":
        return READ + ["Bash(python -m unittest *)", "Bash(python -m flake8 *)", "Bash(python -c *)"]
    raise ValueError(f"unknown role {role}")


def denied_tools(role: str, out_dir: str = OUT_DIR) -> list[str]:
    extra: list[str] = []
    if role == "tester":
        # ADR-003: the tester works from the acceptance criteria, not from the design or the implementer.
        extra = [f"Read(./{out_dir}/design.md)"]
    return DENY_ALWAYS + extra


def model_for(role: str) -> str:
    if role == "reviewer" and os.environ.get("AUTOSE_REVIEWER_MODEL"):
        return os.environ["AUTOSE_REVIEWER_MODEL"]  # experiment E2
    return ROLES[role]["model"]
