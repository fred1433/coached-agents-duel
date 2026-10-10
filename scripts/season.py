"""Demo season runner. Stages are run one at a time so the coach can read between them.

  python3 scripts/season.py init
  python3 scripts/season.py series 1        # 12 duels, round robin, both roles
  python3 scripts/season.py lessons 1       # coach notes from corpus/coach_notes_1.json + self-reflection
  python3 scripts/season.py series 2
  python3 scripts/season.py lessons 2
  python3 scripts/season.py series 3
  python3 scripts/season.py calibrate       # replays from identical states, eval=true, no memory writes

Everything is appended to corpus/. Nothing here needs an API key.
"""
from __future__ import annotations

import itertools
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duel.agents import Agent  # noqa: E402
from duel.engine import Scenario, make_scenarios  # noqa: E402
from duel.llm import ClaudeCLI, ExecutionIncident, QuotaExhausted  # noqa: E402
from duel.runner import play_duel, update_memory  # noqa: E402

CORPUS = ROOT / "corpus"
SEED = 20261010

ROSTER = [
    dict(id="hollis", name="Hollis", style="The anchor", learning="coached",
         personality="You open with an ambitious offer and concede in small, deliberate steps. You rarely explain your values.",
         lessons=["Open high on the good you value most; the first number frames everything after it.",
                  "Concede one unit at a time, never two.",
                  "A deal above the impasse value beats a perfect deal that never closes.",
                  "Ask what they need before giving anything away."]),
    dict(id="marlow", name="Marlow", style="The trader", learning="coached",
         personality="You look for swaps: you give away what you value least to get what you value most. You ask questions and propose trades.",
         lessons=["Goods worth little to you are your currency; spend them first.",
                  "When they insist on one good, it is probably their top value.",
                  "Propose complete splits, not vague ideas.",
                  "Keep at least one action in reserve to accept."]),
    dict(id="juno", name="Juno", style="The closer", learning="self",
         personality="You like to close by the middle of the duel. You make fair-looking offers early and accept anything clearly above your impasse value.",
         lessons=["An early fair offer often gets accepted.",
                  "Do not let the duel reach the last action without an open offer.",
                  "Check the arithmetic of every split before sending it.",
                  "Silence about your values is not lying."]),
    dict(id="tamsin", name="Tamsin", style="The skeptic", learning="none",
         personality="You distrust first offers. You reject or counter them, test the other side, and keep your priorities hidden.",
         lessons=["The first offer you receive is never their best.",
                  "Counter instead of rejecting when time is short.",
                  "Never reveal which good you value most.",
                  "Late in the duel, accept anything above your impasse value."]),
]


def path(name):
    return CORPUS / name


def rebuild_agents() -> dict:
    """The memory journal is authoritative: agents = roster + every logged update, in order."""
    agents = {d["id"]: Agent(d["id"], d["name"], d["style"], d["personality"], d["learning"], d["lessons"]) for d in ROSTER}
    for e in read_jsonl("memory_events.jsonl"):
        r = agents[e["agent"]].apply_update({"decision": e["decision"], "lesson": e["lesson"],
                                             "replace_slot": e.get("slot")}, e["source"])
        if r["after"] != e["after"] or r["after_version"] != e["after_version"]:
            raise RuntimeError(f"memory journal does not replay for {e['agent']} round {e.get('round')}")
    return agents


def load_agents() -> dict:
    agents = rebuild_agents()
    save_agents(agents)  # agents.json is a derived snapshot, rewritten from the journal
    return agents


def save_agents(agents: dict):
    path("agents.json").write_text(json.dumps([a.to_dict() for a in agents.values()], indent=1))


def append(name, rec):
    with open(path(name), "a") as f:
        f.write(json.dumps(rec) + "\n")


def read_jsonl(name) -> list:
    p = path(name)
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def init():
    CORPUS.mkdir(exist_ok=True)
    agents = {d["id"]: Agent(d["id"], d["name"], d["style"], d["personality"], d["learning"], d["lessons"]) for d in ROSTER}
    save_agents(agents)
    scen = make_scenarios(SEED, 4)
    path("scenarios.json").write_text(json.dumps([s.to_dict() for s in scen], indent=1))
    print("initialised", list(agents), [s.id for s in scen])


def schedule(series: int):
    ids = [d["id"] for d in ROSTER]
    scen = [Scenario.from_dict(d) for d in json.loads(path("scenarios.json").read_text())]
    out = []
    for k, (x, y) in enumerate(itertools.combinations(ids, 2)):
        s = scen[(k + series) % len(scen)]
        out.append((x, y, s))  # x moves first with the 'first' value profile
        out.append((y, x, s))  # mirror: y takes the same position and profile
    return out


def run_batch(jobs, eval_mode: bool, series: str, keep_prompts_first: bool = False, llm=None, workers: int = 4):
    """Run duels in parallel. Each finished duel is appended at once. An exhausted quota cancels
    the queue cleanly; other incidents are logged (with the usage of the calls already made)
    and the duel is left to be replayed later from the same state."""
    llm = llm or ClaudeCLI()
    done = {r["id"] for r in read_jsonl("duels.jsonl")}
    todo = [j for j in jobs if j[0] not in done]

    def one(job):
        did, first, second, s = job
        return play_duel(did, {"first": first, "second": second}, s, llm, series, eval_mode,
                         keep_prompts=keep_prompts_first and did.endswith("01"))

    def handle(fut):
        did = futures[fut]
        try:
            rec = fut.result()
        except ExecutionIncident as e:  # quota or other incident: never scored, replayed later from the same state
            append("incidents.jsonl", {"duel": did, "kind": e.kind, "attempts": e.attempts,
                                       "partial_calls": getattr(e, "partial_calls", [])})
            return e
        append("duels.jsonl", rec)
        print(rec["id"], rec["status"], rec["scores"], "invalid", rec["invalid_actions"], flush=True)
        return None

    quota = None
    with ThreadPoolExecutor(workers) as ex:
        futures = {ex.submit(one, j): j[0] for j in todo}
        handled = set()
        for fut in as_completed(futures):
            handled.add(fut)
            err = handle(fut)
            if isinstance(err, QuotaExhausted):
                quota = err
                for f in futures:
                    f.cancel()  # queued duels never start; running ones finish below
                break
        for fut in futures:
            if fut not in handled and not fut.cancelled():
                handle(fut)  # waits for a duel that was already running, saves it
    if quota:
        raise quota


def series(n: int):
    agents = load_agents()
    jobs = []
    for i, (x, y, s) in enumerate(schedule(n), 1):
        jobs.append((f"s{n}-{i:02d}", agents[x], agents[y], s))
    run_batch(jobs, False, f"series {n}", keep_prompts_first=True)


def lessons(n: int, only: str | None = None, llm=None):
    """One memory update per learning agent for round n. Each update is journaled and the snapshot
    saved at once; an update already in the journal is never redone, so a rerun resumes cleanly."""
    agents = load_agents()
    notes = json.loads(path(f"coach_notes_{n}.json").read_text()) if path(f"coach_notes_{n}.json").exists() else {}
    recs = [r for r in read_jsonl("duels.jsonl") if r["series"] == f"series {n}"]
    done = {(e.get("round"), e["agent"]) for e in read_jsonl("memory_events.jsonl")}
    llm = llm or ClaudeCLI()
    for a in agents.values():
        if a.learning == "none" or (only and a.id != only) or (n, a.id) in done:
            continue
        mine = [r for r in recs if a.id in (r["players"]["first"]["agent"], r["players"]["second"]["agent"])]
        fb = notes[a.id]["note"] if a.learning == "coached" else None
        try:
            rec = update_memory(a, mine, llm, fb)
        except ExecutionIncident as e:
            append("incidents.jsonl", {"phase": "lessons", "round": n, "agent": a.id, "kind": e.kind,
                                       "attempts": e.attempts})
            if isinstance(e, QuotaExhausted):
                raise
            continue
        rec["id"] = f"r{n}-{a.id}"
        rec["round"] = n
        rec["coach_written_by"] = notes.get(a.id, {}).get("written_by") if fb else None
        append("memory_events.jsonl", rec)
        save_agents(agents)
        print(a.id, rec["decision"], rec["valid"], rec.get("error"), "->", rec["lesson"])


def calibrate():
    """3 configurations x 4 replays from strictly identical states (eval=true)."""
    agents = load_agents()
    scen = {d["id"]: Scenario.from_dict(d) for d in json.loads(path("scenarios.json").read_text())}
    configs = [("hollis", "marlow", "S1"), ("juno", "tamsin", "S2"), ("marlow", "juno", "S3")]
    jobs = []
    for c, (x, y, sid) in enumerate(configs, 1):
        for rep in range(1, 5):
            jobs.append((f"cal{c}-r{rep}", agents[x], agents[y], scen[sid]))
    run_batch(jobs, True, "calibration")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "init":
        init()
    elif cmd == "series":
        series(int(sys.argv[2]))
    elif cmd == "lessons":
        lessons(int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "calibrate":
        calibrate()
    else:
        raise SystemExit(__doc__)
