"""Run one agent as a headless Claude Code session (ADR-005).

Each call is `claude -p` with the role's model, effort, tool allowlist, deny rules, turn cap and
`--permission-mode dontAsk`, so any tool call outside the allowlist is denied instead of prompting.
The prompt is passed on stdin; untrusted text (issues) is only ever in files, never in arguments.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .common import agent_env, append_usage, log, out_path

PROMPTS = Path(__file__).parent / "prompts"
SKILL = Path(__file__).parent / "skills" / "requirements-spec-builder.md"


@dataclass
class AgentResult:
    ok: bool
    text: str = ""
    structured: dict | None = None
    session_id: str | None = None
    subtype: str = ""
    error: str = ""
    denials: list = field(default_factory=list)


def system_prompt(role: str) -> str:
    parts = [(PROMPTS / "common.md").read_text(), (PROMPTS / f"{role}.md").read_text()]
    if role in ("requirements", "single"):
        parts.append("\n\n# Requirements skill (apply it in AutoSE mode)\n\n" + SKILL.read_text())
    return "\n\n".join(parts)


def run_agent(role: str, prompt: str, *, stage: str, attempt: int, cwd: str = ".",
              resume: str | None = None, json_schema: dict | None = None) -> AgentResult:
    cfg = config.ROLES[role]
    cmd = [
        "claude", "-p",
        "--model", config.model_for(role),
        "--effort", cfg["effort"],
        "--output-format", "json",
        "--max-turns", str(cfg["max_turns"]),
        "--permission-mode", "dontAsk",
        "--allowedTools", ",".join(config.allowed_tools(role)),
        "--disallowedTools", ",".join(config.denied_tools(role)),
        "--append-system-prompt", system_prompt(role),
    ]
    if resume:
        cmd += ["--resume", resume]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]
    env = agent_env()
    env["AUTOSE_ROLE"] = role  # lets the local fake CLI used in tests know which role it plays
    log(f"agent {role} (stage {stage}, attempt {attempt}, model {config.model_for(role)})")
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, input=prompt, text=True, capture_output=True,
                              timeout=cfg["timeout"])
    except subprocess.TimeoutExpired:
        _usage(role, stage, attempt, {}, started, "timeout")
        return AgentResult(ok=False, error=f"agent {role} exceeded its wall-clock limit of {cfg['timeout']}s")
    raw_path = out_path("logs", f"{stage}-{role}-{attempt}.json")
    raw_path.write_text(proc.stdout or "")
    if proc.stderr:
        out_path("logs", f"{stage}-{role}-{attempt}.stderr.txt").write_text(proc.stderr[-20000:])
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        _usage(role, stage, attempt, {}, started, "no-json")
        msg = (proc.stderr or proc.stdout or "")[-1500:]
        if "limit" in msg.lower():
            msg = "usage or rate limit reported by Claude Code: " + msg
        return AgentResult(ok=False, error=f"agent {role} produced no JSON result (exit {proc.returncode}): {msg}")
    subtype = data.get("subtype", "")
    _usage(role, stage, attempt, data, started, subtype)
    denials = data.get("permission_denials") or []
    if denials:
        log(f"agent {role}: {len(denials)} tool call(s) denied by the permission rules")
    ok = (subtype == "success") and not data.get("is_error")
    err = "" if ok else f"agent {role} ended with {subtype or 'error'}: {str(data.get('result', ''))[:500]}"
    return AgentResult(ok=ok, text=data.get("result") or "", structured=data.get("structured_output"),
                       session_id=data.get("session_id"), subtype=subtype, error=err, denials=denials)


def _usage(role: str, stage: str, attempt: int, data: dict, started: float, outcome: str) -> None:
    usage = data.get("usage") or {}
    append_usage({
        "role": role, "stage": stage, "attempt": attempt, "outcome": outcome,
        "model_requested": config.model_for(role),
        "models": list((data.get("modelUsage") or {}).keys()),
        "input_tokens": usage.get("input_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cost_usd_list_price": data.get("total_cost_usd", 0),
        "num_turns": data.get("num_turns", 0),
        "duration_s": round(time.time() - started, 1),
        "permission_denials": len(data.get("permission_denials") or []),
    })
