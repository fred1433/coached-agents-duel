"""Reliability cases from the external review: interrupted lessons, cost of failed attempts, validation."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from duel.agents import LESSON_MAX_CHARS, LESSON_SCHEMA, Agent, lesson_prompt  # noqa: E402
from duel.cost import summarize_calls  # noqa: E402
from duel.engine import GOODS, Match, Scenario  # noqa: E402
from duel.llm import CallResult, QuotaExhausted  # noqa: E402

SCEN = Scenario("T", {"tea": 4, "silk": 3, "saffron": 2},
                {"first": {"tea": 7, "silk": 0, "saffron": 1}, "second": {"tea": 4, "silk": 2, "saffron": 4}},
                {"first": 6, "second": 6})


class PlayLLM:
    def call(self, system, user, schema):
        view = json.loads(user[user.index("{"): user.rindex("}") + 1])
        if view["open_offer"] and view["open_offer"]["by"] == "them":
            a = {"action": "accept", "offer_id": view["open_offer"]["id"], "you_get": None, "they_get": None, "message": "ok"}
        else:
            a = {"action": "offer", "offer_id": None, "you_get": dict(zip(GOODS, (3, 0, 1))),
                 "they_get": dict(zip(GOODS, (1, 3, 1))), "message": "x"}
        return CallResult(a, json.dumps(a), {"input_tokens": 1, "output_tokens": 1}, "fake", 1, 1, 0.0)


class LessonLLM:
    def __init__(self, quota_for=None):
        self.quota_for, self.called = quota_for, []

    def call(self, system, user, schema):
        name = system.split("You are ")[1].split(",")[0]
        self.called.append(name)
        if name == self.quota_for:
            raise QuotaExhausted("quota", "usage limit reached", [{"kind": "quota", "seconds": 1.0}])
        a = {"lesson": f"{name} keeps one more unit when actions remain.", "decision": "add", "replace_slot": None, "reason": "free slot"}
        return CallResult(a, json.dumps(a), {"input_tokens": 1, "output_tokens": 1}, "fake", 1, 1, 0.0)


def test_interrupted_lessons_resume_idempotently(tmp_path, monkeypatch):
    import scripts.season as season
    from duel.runner import play_duel
    monkeypatch.setattr(season, "CORPUS", tmp_path)
    season.init()
    ag = season.load_agents()
    with open(tmp_path / "duels.jsonl", "w") as f:
        for i, (x, y) in enumerate((("hollis", "marlow"), ("juno", "tamsin"))):
            f.write(json.dumps(play_duel(f"s1-{i}", {"first": ag[x], "second": ag[y]}, SCEN, PlayLLM(), "series 1")) + "\n")
    (tmp_path / "coach_notes_1.json").write_text(json.dumps({k: {"note": "Hold once.", "written_by": "test"} for k in ("hollis", "marlow")}))

    with pytest.raises(QuotaExhausted):
        season.lessons(1, llm=LessonLLM(quota_for="Marlow"))
    events = [json.loads(l) for l in (tmp_path / "memory_events.jsonl").read_text().splitlines()]
    assert [e["agent"] for e in events] == ["hollis"] and events[0]["id"] == "r1-hollis"
    snap = {d["id"]: d for d in json.loads((tmp_path / "agents.json").read_text())}
    assert snap["hollis"]["version"] == 2 and season.load_agents()["hollis"].version == 2
    inc = [json.loads(l) for l in (tmp_path / "incidents.jsonl").read_text().splitlines()]
    assert inc[0]["phase"] == "lessons" and inc[0]["agent"] == "marlow"

    llm = LessonLLM()
    season.lessons(1, llm=llm)
    assert "Hollis" not in llm.called  # already journaled: not redone
    events = [json.loads(l) for l in (tmp_path / "memory_events.jsonl").read_text().splitlines()]
    assert [e["agent"] for e in events] == ["hollis", "marlow", "juno"]
    final = season.load_agents()
    assert final["hollis"].version == 2 and final["marlow"].version == 2 and final["tamsin"].version == 1


def test_failed_attempts_count_in_cost_and_time():
    call = {"model": "claude-sonnet-5-5", "usage": {"input_tokens": 1_000_000}, "duration_ms": 1000,
            "failed_attempts": [{"kind": "cli_error", "usage": {"input_tokens": 1_000_000}, "seconds": 2.0}]}
    s = summarize_calls([call])
    assert s["tokens"]["input"] == 2_000_000 and s["equivalent_usd"] == 4.0 and s["seconds"] == 3.0
    incident = {"kind": "incident", "failed_attempts": [{"usage": {"output_tokens": 100_000}, "model": "claude-sonnet-5-5", "seconds": 1.5}]}
    s2 = summarize_calls([call, incident])
    assert s2["calls"] == 1 and s2["equivalent_usd"] == 5.0 and s2["seconds"] == 4.5


def test_unknown_price_is_flagged_not_free():
    s = summarize_calls([{"model": "some-other-model", "usage": {"input_tokens": 10}, "duration_ms": 1}])
    assert s["unpriced"] == 1


def test_non_string_offer_id_loses_the_turn_instead_of_crashing():
    m = Match(SCEN)
    m.apply("first", {"action": "offer", "offer_id": None, "you_get": dict(zip(GOODS, (3, 0, 1))),
                      "they_get": dict(zip(GOODS, (1, 3, 1))), "message": ""})
    e = m.apply("second", {"action": "accept", "offer_id": ["o1"], "message": ""})
    assert not e["valid"] and m.status == "open"
    e = m.apply("first", "not a dict")
    assert not e["valid"]


def test_lesson_as_list_is_invalid_not_a_crash():
    a = Agent("a", "A", "s", "p", "coached", ["One."])
    r = a.apply_update({"decision": "add", "lesson": ["a", "list"]}, "coach")
    assert not r["valid"] and a.lessons == ["One."]
    assert not a.apply_update(["not", "a", "dict"], "coach")["valid"]


def test_limits_apply_at_creation_and_loading():
    with pytest.raises(ValueError):
        Agent("a", "A", "s", "p", "coached", ["x" * 20000])
    good = Agent("a", "A", "s", "p", "coached", ["One."]).to_dict()
    good["lessons"] = ["One.", "one"]
    with pytest.raises(ValueError):
        Agent.from_dict(good)


def test_char_limit_in_prompt_and_schema():
    assert LESSON_SCHEMA["properties"]["lesson"]["maxLength"] == LESSON_MAX_CHARS
    system, _ = lesson_prompt(Agent("a", "A", "s", "p", "coached", []), "batch", "note")
    assert f"{LESSON_MAX_CHARS} characters" in system
