"""Model-free tests: rules, memory limits, data leaks, incidents, score concordance."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duel.agents import LESSON_MAX_WORDS, MEMORY_SLOTS, Agent, MemoryLocked, play_prompt  # noqa: E402
from duel.engine import GOODS, Match, MatchOver, Scenario, make_scenarios, score  # noqa: E402
from duel.llm import ExecutionIncident, ScriptedLLM, build_cmd, child_env  # noqa: E402
from duel.runner import play_duel, update_memory  # noqa: E402

STOCK = {"tea": 4, "silk": 3, "saffron": 2}
SCEN = Scenario("T", STOCK, {"first": {"tea": 7, "silk": 0, "saffron": 1}, "second": {"tea": 4, "silk": 2, "saffron": 4}},
                {"first": 6, "second": 6})


def offer(you, they, msg="x"):
    return {"action": "offer", "offer_id": None, "you_get": dict(zip(GOODS, you)), "they_get": dict(zip(GOODS, they)),
            "message": msg}


def agent(i="a", learning="coached", lessons=None):
    return Agent(i, i.title(), "style", "You negotiate.", learning, list(lessons or ["Lesson one."]))


# --- resources are conserved -------------------------------------------------------------
def test_offer_must_allocate_every_unit():
    m = Match(SCEN)
    e = m.apply("first", offer((4, 3, 1), (0, 0, 0)))
    assert not e["valid"] and "saffron" in e["error"]
    assert m.open_offer is None and m.turn == 1  # the turn is lost


def test_negative_and_non_integer_rejected():
    m = Match(SCEN)
    assert not m.apply("first", offer((5, 3, 2), (-1, 0, 0)))["valid"]
    m2 = Match(SCEN)
    bad = offer((4, 3, 2), (0, 0, 0)); bad["you_get"]["tea"] = 4.0
    assert not m2.apply("first", bad)["valid"]


def test_valid_offer_conserves_stock():
    m = Match(SCEN)
    e = m.apply("first", offer((3, 0, 1), (1, 3, 1)))
    assert e["valid"]
    for g in GOODS:
        assert e["alloc"]["first"][g] + e["alloc"]["second"][g] == STOCK[g]


def test_generated_scenarios_pool_value():
    for s in make_scenarios(1, 6):
        assert s.max_value("first") == 30 and s.max_value("second") == 30


# --- acceptances ----------------------------------------------------------------------------
def test_cannot_accept_own_offer():
    m = Match(SCEN)
    m.apply("first", offer((3, 0, 1), (1, 3, 1)))
    m.apply("second", {"action": "reject", "offer_id": "o1", "message": ""})
    m.apply("first", offer((3, 0, 1), (1, 3, 1)))
    m.apply("second", offer((1, 3, 1), (3, 0, 1)))  # o3 by second
    e = m.apply("first", {"action": "accept", "offer_id": "o2", "message": ""})
    assert not e["valid"] and "own offer" in e["error"]


def test_cannot_accept_stale_offer():
    m = Match(SCEN)
    m.apply("first", offer((3, 0, 1), (1, 3, 1)))  # o1
    m.apply("second", offer((1, 3, 1), (3, 0, 1)))  # o2 replaces o1
    m.apply("first", offer((2, 0, 1), (2, 3, 1)))  # o3 replaces o2
    e = m.apply("second", {"action": "accept", "offer_id": "o1", "message": ""})
    assert not e["valid"]
    assert m.status == "open"


def test_accept_with_nothing_open_and_unknown_id():
    m = Match(SCEN)
    assert not m.apply("first", {"action": "accept", "offer_id": "o1", "message": ""})["valid"]
    m.apply("second", offer((1, 3, 1), (3, 0, 1)))
    assert not m.apply("first", {"action": "accept", "offer_id": "o9", "message": ""})["valid"]


def test_agreement_is_terminal():
    m = Match(SCEN)
    m.apply("first", offer((3, 0, 1), (1, 3, 1)))
    m.apply("second", {"action": "accept", "offer_id": "o1", "message": "deal"})
    assert m.status == "agreed"
    with pytest.raises(MatchOver):
        m.apply("first", offer((4, 3, 2), (0, 0, 0)))


def test_reject_closes_offer_and_impasse_after_eight():
    m = Match(SCEN)
    m.apply("first", offer((3, 0, 1), (1, 3, 1)))
    m.apply("second", {"action": "reject", "offer_id": "o1", "message": ""})
    assert m.open_offer is None
    for _ in range(6):
        m.apply(m.actor, None)  # unusable outputs: turns lost
    assert m.status == "impasse"
    assert m.scores() == {"first": round(6 / 30, 6), "second": round(6 / 30, 6)}


def test_turn_order_enforced():
    m = Match(SCEN)
    with pytest.raises(ValueError):
        m.apply("second", offer((1, 3, 1), (3, 0, 1)))


def test_score_formula_by_hand():
    agreement = {"first": {"tea": 3, "silk": 0, "saffron": 0}, "second": {"tea": 1, "silk": 3, "saffron": 2}}
    assert score(SCEN, "agreed", agreement, "first") == round(21 / 30, 6)
    assert score(SCEN, "agreed", agreement, "second") == round(18 / 30, 6)


# --- private data never leaks ---------------------------------------------------------------
def test_opponent_values_absent_from_serialized_prompt():
    s = Scenario("L", STOCK, {"first": {"tea": 1, "silk": 2, "saffron": 3}, "second": {"tea": 913, "silk": 917, "saffron": 919}},
                 {"first": 6, "second": 6})
    m = Match(s)
    m.apply("first", offer((2, 2, 1), (2, 1, 1)))
    system, user = play_prompt(agent(), m, "first")
    blob = system + user
    for v in ("913", "917", "919"):
        assert v not in blob
    system2, user2 = play_prompt(agent(), m, "second")
    assert "913" in user2 and '"tea": 1,' not in user2


def test_play_calls_get_no_old_transcripts():
    llm = ScriptedLLM([offer((3, 0, 1), (1, 3, 1)), {"action": "accept", "offer_id": "o1", "you_get": None,
                                                     "they_get": None, "message": "ok"}])
    rec = play_duel("d1", {"first": agent("a"), "second": agent("b")}, SCEN, llm, "t")
    assert rec["status"] == "agreed"
    llm2 = ScriptedLLM([offer((3, 0, 1), (1, 3, 1))] * 8)
    play_duel("d2", {"first": agent("a"), "second": agent("b")}, SCEN, llm2, "t")
    assert all("d1" not in c["system"] + c["user"] for c in llm2.calls)


# --- memory -----------------------------------------------------------------------------------
def test_memory_limit_and_eviction():
    a = agent(lessons=[f"Lesson {i}." for i in range(1, 6)])
    r = a.apply_update({"decision": "add", "lesson": "Sixth."}, "coach")
    assert not r["valid"] and len(a.lessons) == MEMORY_SLOTS and a.version == 1
    r = a.apply_update({"decision": "replace", "replace_slot": 2, "lesson": "New two."}, "coach")
    assert r["valid"] and r["evicted"] == "Lesson 2." and a.lessons[1] == "New two." and a.version == 2
    r = a.apply_update({"decision": "discard", "lesson": "Not kept."}, "self")
    assert r["valid"] and a.version == 2 and "Not kept." not in a.lessons
    assert [h["version"] for h in a.history] == [1, 1, 2, 2]


def test_lesson_word_limit():
    a = agent()
    r = a.apply_update({"decision": "add", "lesson": "word " * (LESSON_MAX_WORDS + 1)}, "coach")
    assert not r["valid"] and len(a.lessons) == 1


def test_eval_flag_forbids_memory_writes():
    a = agent()
    with pytest.raises(MemoryLocked):
        a.apply_update({"decision": "add", "lesson": "x"}, "coach", eval_mode=True)
    with pytest.raises(MemoryLocked):
        update_memory(a, [], ScriptedLLM([]), "note", eval_mode=True)


def test_frozen_version_replay():
    a = agent(lessons=["A."])
    a.apply_update({"decision": "add", "lesson": "B."}, "coach")
    assert a.at_version(1).lessons == ["A."] and a.lessons == ["A.", "B."]


# --- incidents and isolation ------------------------------------------------------------------
def test_incident_is_not_scored():
    llm = ScriptedLLM([offer((3, 0, 1), (1, 3, 1)), ExecutionIncident("cli_error", "network", [])])
    with pytest.raises(ExecutionIncident):
        play_duel("d", {"first": agent("a"), "second": agent("b")}, SCEN, llm, "t")


def test_cli_isolation_flags_and_env(monkeypatch):
    cmd = build_cmd("sys", "user", {"type": "object"})
    for flag in ("--system-prompt", "--tools", "--strict-mcp-config", "--setting-sources", "--safe-mode",
                 "--no-session-persistence", "--json-schema"):
        assert flag in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and "--bare" not in cmd
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-pass")
    assert "ANTHROPIC_API_KEY" not in child_env()


# --- concordance between logs, rescoring and the page ----------------------------------------
def test_logs_rescore_and_page_agree():
    duels = ROOT / "corpus" / "duels.jsonl"
    page = ROOT / "site" / "data" / "corpus.json"
    if not duels.exists():
        pytest.skip("no recorded corpus yet")
    from scripts.rescore import rescore
    report = rescore()
    assert report["mismatches"] == [], report["mismatches"]
    if page.exists():
        data = json.loads(page.read_text())
        by_id = {d["id"]: d for d in data["duels"]}
        for rec in (json.loads(l) for l in duels.read_text().splitlines() if l.strip()):
            assert by_id[rec["id"]]["scores"] == rec["scores"]


# --- corrections after review -----------------------------------------------------------------
def test_reject_must_name_the_open_offer():
    m = Match(SCEN)
    m.apply("first", offer((3, 0, 1), (1, 3, 1)))
    e = m.apply("second", {"action": "reject", "offer_id": "o99", "message": ""})
    assert not e["valid"] and m.open_offer["id"] == "o1"
    m.apply("first", offer((3, 0, 1), (1, 3, 1)))  # o2
    assert m.apply("second", {"action": "reject", "offer_id": "o2", "message": ""})["valid"]


def test_memory_refuses_eval_records_even_without_flag():
    a = agent()
    with pytest.raises(MemoryLocked):
        update_memory(a, [{"id": "cal1-r1", "eval": True}], ScriptedLLM([]), "note")


def test_memory_char_cap_duplicates_and_boolean_slot():
    from duel.agents import LESSON_MAX_CHARS
    a = agent(lessons=["Hold your offer once."])
    assert not a.apply_update({"decision": "add", "lesson": "x" * (LESSON_MAX_CHARS + 1)}, "coach")["valid"]
    assert not a.apply_update({"decision": "add", "lesson": "hold your offer   once"}, "coach")["valid"]
    r = a.apply_update({"decision": "replace", "replace_slot": True, "lesson": "Something new."}, "coach")
    assert not r["valid"] and a.lessons == ["Hold your offer once."]


class KeyedLLM:
    """Healthy duels end in two calls (offer, accept); any prompt naming 'Quota' hits an exhausted quota."""

    def __init__(self, quota_on_call=1, accept=True, delay=0.0):
        self.quota_on_call, self.seen, self.accept, self.delay = quota_on_call, {}, accept, delay

    def call(self, system, user, schema):
        import time
        from duel.llm import CallResult, QuotaExhausted
        time.sleep(self.delay)
        if "Quota" in system:
            k = self.seen.get("q", 0) + 1
            self.seen["q"] = k
            if k >= self.quota_on_call:
                raise QuotaExhausted("quota", "usage limit reached", [{"kind": "quota"}])
        view = json.loads(user[user.index("{"): user.rindex("}") + 1])
        if self.accept and view["open_offer"] and view["open_offer"]["by"] == "them":
            a = {"action": "accept", "offer_id": view["open_offer"]["id"], "you_get": None, "they_get": None, "message": "ok"}
        else:
            a = offer((3, 0, 1), (1, 3, 1))
        return CallResult(a, json.dumps(a), {"input_tokens": 3, "output_tokens": 2}, "fake", 1, 1, 0.0)


def test_quota_stops_cleanly_and_keeps_finished_duels(tmp_path, monkeypatch):
    import scripts.season as season
    monkeypatch.setattr(season, "CORPUS", tmp_path)
    jobs = [("h1", agent("a"), agent("b"), SCEN), ("q1", agent("quota"), agent("b"), SCEN),
            ("h2", agent("a"), agent("b"), SCEN), ("h3", agent("a"), agent("b"), SCEN)]
    from duel.llm import QuotaExhausted
    with pytest.raises(QuotaExhausted):
        season.run_batch(jobs, False, "t", llm=KeyedLLM(delay=0.05), workers=1)
    saved = [json.loads(l)["id"] for l in (tmp_path / "duels.jsonl").read_text().splitlines()]
    # h1 finished before the quota and is saved; a duel already running may finish; the rest is cancelled
    assert saved[0] == "h1" and "h3" not in saved
    inc = [json.loads(l) for l in (tmp_path / "incidents.jsonl").read_text().splitlines()]
    assert inc[0]["duel"] == "q1" and inc[0]["kind"] == "quota"


def test_incident_keeps_partial_calls_for_the_cost_log(tmp_path, monkeypatch):
    import scripts.season as season
    monkeypatch.setattr(season, "CORPUS", tmp_path)
    jobs = [("q1", agent("quota"), agent("b"), SCEN)]
    from duel.llm import QuotaExhausted
    with pytest.raises(QuotaExhausted):
        season.run_batch(jobs, False, "t", llm=KeyedLLM(quota_on_call=2, accept=False), workers=1)
    inc = json.loads((tmp_path / "incidents.jsonl").read_text().splitlines()[0])
    assert len(inc["partial_calls"]) == 2 and inc["partial_calls"][0]["usage"]["output_tokens"] == 2
