"""Shared helpers: processes, front matter, run state, usage, GitHub Actions outputs."""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from . import config


def log(msg: str) -> None:
    print(f"[autose] {msg}", flush=True)


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def out_path(*parts: str) -> Path:
    p = Path(config.OUT_DIR, *parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def run(cmd: list[str], cwd: str | Path | None = None, env: dict | None = None, timeout: int | None = None,
        input: str | None = None) -> subprocess.CompletedProcess:
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, input=input, text=True, capture_output=True)


def clean_env(extra: dict | None = None) -> dict:
    """Environment for running repository code (tests, builds): no credentials at all (ADR-009)."""
    env = {k: v for k, v in os.environ.items()
           if "TOKEN" not in k.upper() and "SECRET" not in k.upper() and not k.startswith("ACTIONS_")}
    env.update(extra or {})
    return env


def agent_env() -> dict:
    """Environment for a Claude Code agent: only the Claude credential, no GitHub tokens."""
    env = clean_env()
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        env["CLAUDE_CODE_OAUTH_TOKEN"] = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    # Claude Code removes its own credentials from the environment of every command an agent runs
    # (tests, `python -c` probes), so generated code cannot read the Claude token. Verified locally
    # with Claude Code 2.1.319: a variable from its credential list disappears, a control variable stays.
    env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] = "1"
    return env


def git_exclude(pattern: str, cwd: str | Path = ".") -> None:
    """Make git ignore an AutoSE working directory (works in normal clones and in worktrees)."""
    proc = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=cwd, text=True,
                          capture_output=True)
    path = Path(cwd, proc.stdout.strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    if pattern not in existing.splitlines():
        path.write_text(existing.rstrip("\n") + f"\n{pattern}\n")


def tail(text: str, lines: int = 60) -> str:
    return "\n".join((text or "").splitlines()[-lines:])


FRONT_RE = re.compile(r"^\s*---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)(.*)$", re.S)


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = FRONT_RE.match(text or "")
    if not m:
        return {}, text or ""
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    return (data if isinstance(data, dict) else {}), m.group(2)


def gh_output(**kv: Any) -> None:
    """Write step outputs for GitHub Actions (no-op locally)."""
    path = os.environ.get("GITHUB_OUTPUT")
    lines = [f"{k}={v}" for k, v in kv.items()]
    for line in lines:
        log(f"output {line}")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


class RunState:
    """run_state.json: where the run is, what it decided, and why it stopped (ADR-004)."""

    def __init__(self, path: Path, **init: Any):
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text())
            self.data.update({k: v for k, v in init.items() if v is not None})
        else:
            self.data = {"created": now(), "transitions": [], "checks": [], "status": "running", **init}
        self.save()

    def transition(self, src: str, dst: str, reason: str) -> None:
        self.data["transitions"].append({"at": now(), "from": src, "to": dst, "reason": reason})
        log(f"transition {src} -> {dst}: {reason}")
        self.save()

    def check(self, stage: int, name: str, ok: bool, reasons: list[str]) -> None:
        self.data["checks"].append({"at": now(), "stage": stage, "check": name, "ok": ok, "reasons": reasons})
        log(f"check stage {stage} {name}: {'PASS' if ok else 'FAIL'} {reasons[:3]}")
        self.save()

    def set(self, **kv: Any) -> None:
        self.data.update(kv)
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2))


def append_usage(record: dict) -> None:
    path = out_path("usage.json")
    data = json.loads(path.read_text()) if path.exists() else []
    data.append(record)
    path.write_text(json.dumps(data, indent=2))
