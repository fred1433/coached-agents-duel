"""Play one duel end to end and return a complete, replayable record."""
from __future__ import annotations

import datetime as dt
import hashlib

from .agents import ACTION_SCHEMA, LESSON_SCHEMA, Agent, MemoryLocked, lesson_prompt, play_prompt
from .engine import GOODS, ROLES, Match, Scenario


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def call_record(res, kind: str, n: int | None = None) -> dict:
    return {"kind": kind, "n": n, "model": res.model, "usage": res.usage, "duration_ms": res.duration_ms,
            "duration_api_ms": res.duration_api_ms, "cli_cost_usd": res.cli_cost_usd,
            "failed_attempts": res.attempts, "prompt_chars": res.prompt_chars, "output_chars": len(res.text or "")}


def play_duel(duel_id: str, players: dict, scenario: Scenario, llm, series: str, eval_mode: bool = False,
              keep_prompts: bool = False) -> dict:
    """players: {"first": Agent, "second": Agent}. Agents are only read, never modified."""
    m = Match(scenario)
    calls, prompts = [], []
    while not m.over:
        role = m.actor
        system, user = play_prompt(players[role], m, role)
        res = llm.call(system, user, ACTION_SCHEMA)
        calls.append(call_record(res, "play", m.turn + 1))
        if keep_prompts:
            prompts.append({"n": m.turn + 1, "role": role, "system": system, "user": user})
        m.apply(role, res.structured if isinstance(res.structured, dict) else None)
    rec = {
        "id": duel_id, "series": series, "eval": eval_mode, "scenario": scenario.to_dict(),
        "players": {r: {"agent": players[r].id, "name": players[r].name, "version": players[r].version,
                        "lessons": list(players[r].lessons)} for r in ROLES},
        "actions": m.actions, "status": m.status, "agreement": m.agreement,
        "values": {r: m.value(r) for r in ROLES}, "scores": m.scores(),
        "invalid_actions": sum(1 for a in m.actions if not a["valid"]),
        "calls": calls, "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    if keep_prompts:
        rec["prompts"] = prompts
    return rec


def compact_moves(rec: dict, me: str) -> str:
    lines = []
    for a in rec["actions"]:
        who = "you" if rec["players"][a["role"]]["agent"] == me else "them"
        if not a["valid"]:
            lines.append(f"  {a['n']}. {who}: invalid ({a['error']})")
        elif a["action"] == "offer":
            mine_role = a["role"] if who == "you" else ("second" if a["role"] == "first" else "first")
            yours = a["alloc"][mine_role]
            lines.append(f"  {a['n']}. {who}: offer {a['offer_id']}, you would get "
                         + ", ".join(f"{yours[g]} {g}" for g in GOODS) + f'. "{a["message"][:160]}"')
        else:
            lines.append(f"  {a['n']}. {who}: {a['action']} {a['offer_id']}. \"{a['message'][:160]}\"")
    return "\n".join(lines)


def batch_summary(records: list, agent_id: str) -> str:
    """End-of-match information for one agent's batch: same for coached and self-reflective branches."""
    out = []
    for rec in records:
        role = next(r for r in ROLES if rec["players"][r]["agent"] == agent_id)
        opp = "second" if role == "first" else "first"
        s = rec["scenario"]
        out.append(
            f"Duel {rec['id']} against {rec['players'][opp]['name']} (you moved {role}). "
            f"Stock: {s['stock']}. Your values: {s['values'][role]}. Their values (revealed): {s['values'][opp]}.\n"
            f"{compact_moves(rec, agent_id)}\n"
            f"  Result: {rec['status']}; your score {rec['scores'][role]:.2f}, theirs {rec['scores'][opp]:.2f}.")
    return "\n\n".join(out)


def update_memory(agent: Agent, records: list, llm, feedback: str | None, eval_mode: bool = False) -> dict:
    """One memory update. Coached agents pass the coach's note; self-reflective ones pass None."""
    if eval_mode:
        raise MemoryLocked("eval=true: evaluation matches never write memory")
    summary = batch_summary(records, agent.id)
    system, user = lesson_prompt(agent, summary, feedback)
    res = llm.call(system, user, LESSON_SCHEMA)
    out = res.structured if isinstance(res.structured, dict) else {"decision": None}
    rec = agent.apply_update(out, source="coach" if feedback else "self")
    rec.update(agent=agent.id, feedback=feedback, reason=out.get("reason"), call=call_record(res, "lesson"),
               prompt_hash=_h(system + user), duels=[r["id"] for r in records])
    return rec
