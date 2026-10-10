"""Model calls through the Claude Code CLI on a subscription (`claude -p`), isolated.

Isolation: each call runs from an empty directory, with --system-prompt (replaces
the default prompt), no tools, no MCP servers, no settings files, --safe-mode, no
session persistence, JSON output and a JSON schema. ANTHROPIC_API_KEY is removed
from the child environment so the CLI cannot fall back to API billing.

Errors are split in two:
- an unusable answer from the model is returned as `structured=None` (the engine
  then counts an invalid action, the turn is lost);
- a network failure, an exhausted quota or a CLI crash is an ExecutionIncident:
  it never scores, it is retried a bounded number of times, and every attempt is
  logged and counted in the cost.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

MODEL = os.environ.get("DUEL_MODEL", "sonnet")
EFFORT = os.environ.get("DUEL_EFFORT", "low")
QUOTA_MARKERS = ("usage limit", "rate limit", "quota", "limit reached", "429", "overloaded")


class ExecutionIncident(Exception):
    def __init__(self, kind: str, detail: str, attempts: list):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail, self.attempts = kind, detail, attempts


class QuotaExhausted(ExecutionIncident):
    pass


@dataclass
class CallResult:
    structured: dict | None
    text: str
    usage: dict
    model: str
    duration_ms: int
    duration_api_ms: int
    cli_cost_usd: float | None
    attempts: list = field(default_factory=list)  # failed attempts before success (incidents)
    prompt_chars: int = 0


def build_cmd(system: str, user: str, schema: dict, model: str = MODEL, effort: str = EFFORT) -> list:
    return ["claude", "-p", user, "--model", model, "--effort", effort,
            "--system-prompt", system, "--tools", "", "--strict-mcp-config", "--setting-sources", "",
            "--safe-mode", "--no-session-persistence", "--output-format", "json",
            "--json-schema", json.dumps(schema)]


def child_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("ANTHROPIC_")}
    return env


class ClaudeCLI:
    def __init__(self, model: str = MODEL, effort: str = EFFORT, retries: int = 2, timeout: int = 180):
        self.model, self.effort, self.retries, self.timeout = model, effort, retries, timeout
        self.workdir = tempfile.mkdtemp(prefix="duel-empty-")

    def call(self, system: str, user: str, schema: dict) -> CallResult:
        attempts = []
        for attempt in range(self.retries + 1):
            t0 = time.time()
            try:
                p = subprocess.run(build_cmd(system, user, schema, self.model, self.effort), cwd=self.workdir,
                                   env=child_env(), capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                attempts.append({"kind": "timeout", "seconds": round(time.time() - t0, 1)})
                continue
            out = p.stdout.strip()
            try:
                d = json.loads(out) if out else None
            except json.JSONDecodeError:
                d = None
            blob = (p.stderr or "") + (out[:2000] if d is None else json.dumps(d.get("result", ""))[:2000])
            if d is None or p.returncode != 0 or d.get("is_error"):
                kind = "quota" if any(m in blob.lower() for m in QUOTA_MARKERS) else "cli_error"
                rec = {"kind": kind, "returncode": p.returncode, "detail": blob[:400],
                       "usage": (d or {}).get("usage"), "seconds": round(time.time() - t0, 1)}
                attempts.append(rec)
                if kind == "quota":
                    raise QuotaExhausted("quota", rec["detail"], attempts)
                time.sleep(2 * (attempt + 1))
                continue
            mu = d.get("modelUsage") or {}
            model_id = next(iter(mu), self.model)
            return CallResult(structured=d.get("structured_output"), text=d.get("result", ""),
                              usage=d.get("usage") or {}, model=model_id, duration_ms=d.get("duration_ms", 0),
                              duration_api_ms=d.get("duration_api_ms", 0), cli_cost_usd=d.get("total_cost_usd"),
                              attempts=attempts, prompt_chars=len(system) + len(user) + len(json.dumps(schema)))
        raise ExecutionIncident("retries_exhausted", f"{len(attempts)} failed attempts", attempts)


class ScriptedLLM:
    """Model stand-in for tests: returns queued answers, never touches the network."""

    def __init__(self, answers: list):
        self.answers = list(answers)
        self.calls = []

    def call(self, system: str, user: str, schema: dict) -> CallResult:
        self.calls.append({"system": system, "user": user})
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return CallResult(structured=a, text=json.dumps(a), usage={"input_tokens": 10, "output_tokens": 5},
                          model="scripted", duration_ms=1, duration_api_ms=1, cli_cost_usd=0.0,
                          prompt_chars=len(system) + len(user))
