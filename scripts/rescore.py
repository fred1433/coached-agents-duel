"""Replay every recorded duel through the engine and recompute every score. No model, no account.

  python3 scripts/rescore.py            # prints a summary, exits 1 on any mismatch
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duel.engine import Match, Scenario, other  # noqa: E402


def replay(rec: dict) -> Match:
    m = Match(Scenario.from_dict(rec["scenario"]))
    for a in rec["actions"]:
        role = a["role"]
        if not a["valid"]:
            act = None
        elif a["action"] == "offer":
            act = {"action": "offer", "you_get": a["alloc"][role], "they_get": a["alloc"][other(role)],
                   "message": a["message"]}
        else:
            act = {"action": a["action"], "offer_id": a["offer_id"], "message": a["message"]}
        e = m.apply(role, act)
        if e["valid"] != a["valid"]:
            raise AssertionError(f"{rec['id']} action {a['n']}: validity differs on replay")
    return m


def rescore(path: Path = ROOT / "corpus" / "duels.jsonl") -> dict:
    mismatches, n, agreed = [], 0, 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        n += 1
        try:
            m = replay(rec)
        except AssertionError as e:
            mismatches.append(str(e))
            continue
        if m.status != rec["status"] or m.scores() != rec["scores"] or m.agreement != rec["agreement"]:
            mismatches.append(f"{rec['id']}: recorded {rec['status']} {rec['scores']}, replay {m.status} {m.scores()}")
        agreed += m.status == "agreed"
    return {"duels": n, "agreed": agreed, "mismatches": mismatches}


if __name__ == "__main__":
    r = rescore()
    print(f"{r['duels']} duels replayed, {r['agreed']} agreements, {len(r['mismatches'])} mismatches")
    for x in r["mismatches"]:
        print("  ", x)
    sys.exit(1 if r["mismatches"] else 0)
