"""Build the page data and the simulation inputs from the recorded corpus. No model call.

  python3 scripts/build_data.py pilot   # corpus -> corpus/pilot_params.json (simulation inputs)
  python3 scripts/build_data.py site    # corpus + sim/results.json -> site/data/*.json
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duel.cost import PRICE_DATE, PRICE_SOURCE, summarize_calls  # noqa: E402
from duel.engine import GOODS, ROLES, other  # noqa: E402
from sim.power import total_matches, DEFAULTS  # noqa: E402

C = ROOT / "corpus"


def jl(name):
    p = C / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def share(alloc_side, values):
    return sum(alloc_side[g] * values[g] for g in GOODS) / 30


def profiles(duels, agents):
    out = {}
    for a in agents:
        first_offer, drops, lengths, imp, inv, n_act, scores = [], [], [], 0, 0, 0, []
        played = 0
        for d in duels:
            role = next((r for r in ROLES if d["players"][r]["agent"] == a["id"]), None)
            if role is None:
                continue
            played += 1
            vals = d["scenario"]["values"][role]
            mine = [x for x in d["actions"] if x["role"] == role]
            offers = [share(x["alloc"][role], vals) for x in mine if x["valid"] and x["action"] == "offer"]
            if offers:
                first_offer.append(offers[0])
                drops += [offers[i] - offers[i + 1] for i in range(len(offers) - 1)]
            inv += sum(1 for x in mine if not x["valid"])
            n_act += len(mine)
            if d["status"] == "agreed":
                lengths.append(len(d["actions"]))
            else:
                imp += 1
            scores.append(d["scores"][role])
        out[a["id"]] = {
            "duels": played,
            "first_offer_share": round(st.mean(first_offer), 3) if first_offer else None,
            "concession_per_offer": round(st.mean(drops), 3) if drops else None,
            "actions_to_agreement": round(st.mean(lengths), 2) if lengths else None,
            "impasse_rate": round(imp / played, 3) if played else None,
            "invalid_rate": round(inv / n_act, 3) if n_act else None,
            "mean_score": round(st.mean(scores), 3) if scores else None,
        }
    return out


def calibration_stats(cal):
    groups = defaultdict(list)
    for d in cal:
        key = (d["players"]["first"]["agent"], d["players"]["second"]["agent"], d["scenario"]["id"])
        groups[key].append(d)
    rows, variances = [], []
    for (f, s, sid), ds in groups.items():
        row = {"first": f, "second": s, "scenario": sid, "replays": len(ds),
               "scores_first": [d["scores"]["first"] for d in ds], "scores_second": [d["scores"]["second"] for d in ds],
               "actions": [len(d["actions"]) for d in ds], "agreed": sum(d["status"] == "agreed" for d in ds)}
        for r in ROLES:
            xs = [100 * d["scores"][r] for d in ds]
            if len(xs) > 1:
                variances.append(st.variance(xs))
        rows.append(row)
    pooled = (sum(variances) / len(variances)) ** 0.5 if variances else None
    return rows, pooled


def pilot():
    duels = [d for d in jl("duels.jsonl") if not d["eval"]]
    cal = [d for d in jl("duels.jsonl") if d["eval"]]
    rows, sigma = calibration_stats(cal)
    imp = sum(d["status"] == "impasse" for d in duels) / len(duels)
    role = st.mean(100 * (d["scores"]["first"] - d["scores"]["second"]) for d in duels)
    by_s = defaultdict(list)
    for d in duels:
        by_s[d["scenario"]["id"]] += [100 * d["scores"][r] for r in ROLES]
    scen_sd = st.pstdev([st.mean(v) for v in by_s.values()])
    agents = json.loads((C / "agents.json").read_text())
    prof = profiles(duels, agents)
    pers_sd = st.pstdev([100 * p["mean_score"] for p in prof.values()])
    out = {"measured": {"replay_sd_points": round(sigma, 2) if sigma is not None else None,
                        "impasse_rate": round(imp, 3), "first_mover_edge_points": round(role, 2),
                        "scenario_sd_points": round(scen_sd, 2), "agent_mean_sd_points": round(pers_sd, 2),
                        "duels": len(duels), "replays": len(cal), "calibration": rows},
           "sim_inputs": {"sigma_rep": max(round(sigma, 2), 1.0), "impasse_rate": round(imp, 3),
                          "role_effect": round(abs(role), 2), "scenario_sd": round(max(scen_sd, 1.0), 2),
                          "personality_sd": round(max(pers_sd, 1.0), 2)}}
    (C / "pilot_params.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["measured"] | {"calibration": len(rows)}, indent=1), json.dumps(out["sim_inputs"]))


def slim_duel(d):
    acts = []
    for a in d["actions"]:
        x = {"n": a["n"], "role": a["role"], "valid": a["valid"], "action": a["action"], "offer_id": a["offer_id"],
             "message": a["message"]}
        if a.get("alloc"):
            x["alloc"] = a["alloc"]
        if not a["valid"]:
            x["error"] = a["error"]
        acts.append(x)
    c = summarize_calls(d["calls"])
    return {"id": d["id"], "series": d["series"], "eval": d["eval"], "scenario": d["scenario"],
            "players": d["players"], "actions": acts, "status": d["status"], "agreement": d["agreement"],
            "values": d["values"], "scores": d["scores"], "invalid": d["invalid_actions"],
            "cost": {"tokens": c["tokens"], "usd": c["equivalent_usd"], "seconds": c["seconds"]}}


def site():
    duels = jl("duels.jsonl")
    mem = jl("memory_events.jsonl")
    incidents = jl("incidents.jsonl")
    agents = json.loads((C / "agents.json").read_text())
    notes = {n: json.loads((C / f"coach_notes_{n}.json").read_text()) for n in (1, 2) if (C / f"coach_notes_{n}.json").exists()}
    play_calls = [c for d in duels for c in d["calls"]]
    lesson_calls = [m["call"] for m in mem]
    duel_only = summarize_calls(play_calls)
    learning = summarize_calls(lesson_calls)
    both = summarize_calls(play_calls + lesson_calls)
    n_duels = len(duels)
    n_train = sum(1 for d in duels if not d["eval"])
    per_duel = {k: round(v / n_duels, 1) for k, v in duel_only["tokens"].items()}
    usd_duel = duel_only["equivalent_usd"] / n_duels
    usd_with_learning = (duel_only["equivalent_usd"] + learning["equivalent_usd"]) / n_duels
    chars = sum(c.get("prompt_chars", 0) + c.get("output_chars", 0) for c in play_calls)
    toks = sum(duel_only["tokens"].values())
    pp = json.loads((C / "pilot_params.json").read_text())
    simres = json.loads((ROOT / "sim" / "results.json").read_text())
    p = {**DEFAULTS, **pp["sim_inputs"]}
    pilot_examples = []
    for n, m in ((8, 16), (10, 16), (16, 16), (10, 32)):
        tm = total_matches(n, m, p)
        pilot_examples.append({"coaches": n, "eval_matches": m, "matches": tm, "usd": round(tm * usd_duel, 2)})
    cost = {
        "spend_usd": 0, "model": next((c["model"] for c in play_calls if c.get("model")), None),
        "price_source": PRICE_SOURCE, "price_date": PRICE_DATE, "duels": n_duels,
        "duel_only": duel_only, "learning": learning, "total": both,
        "per_duel_tokens": per_duel, "per_duel_usd": round(usd_duel, 4),
        "per_duel_with_learning_usd": round(usd_with_learning, 4),
        "per_duel_seconds": round(duel_only["seconds"] / n_duels, 1),
        "per_call_seconds": round(duel_only["seconds"] / duel_only["calls"], 1),
        "lesson_updates": len(mem), "incidents": len(incidents),
        "char_count_check": {"chars": chars, "tokens_reported": toks,
                             "note": "rough control only: the CLI adds its own schema and framing tokens"},
        "pilot_estimates": pilot_examples,
    }
    corpus = {"duels": [slim_duel(d) for d in duels], "agents": agents, "memory_events": mem, "coach_notes": notes,
              "profiles": profiles([d for d in duels if not d["eval"]], agents), "pilot": pp["measured"],
              "cost": cost, "training_duels": n_train, "featured": "s2-04"}
    out = ROOT / "site" / "data"
    out.mkdir(parents=True, exist_ok=True)
    (out / "corpus.json").write_text(json.dumps(corpus, separators=(",", ":")))
    (out / "sim.json").write_text(json.dumps({"params": simres["params"], "reps": simres["reps_per_cell"],
                                              "cells": simres["cells"], "rank_stability": simres["rank_stability"]},
                                             separators=(",", ":")))
    print("site data written:", n_duels, "duels,", len(mem), "memory events; per duel usd", round(usd_duel, 4))
    print(json.dumps({k: cost[k] for k in ("per_duel_tokens", "per_duel_usd", "per_duel_with_learning_usd",
                                           "per_duel_seconds", "incidents", "char_count_check", "pilot_estimates")}, indent=1))
    print("duel_only", duel_only, "\nlearning", learning)


if __name__ == "__main__":
    {"pilot": pilot, "site": site}[sys.argv[1]]()
