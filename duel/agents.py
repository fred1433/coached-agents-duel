"""Agents: a personality, a memory of at most five lessons (50 words each), and the
step that turns feedback into a stored lesson.

Each model call receives only: personality, current lessons, its own values,
the rules, the public state and the transcript of the match in progress. No old
transcript, raw feedback or summary is ever passed to a play call.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field

from .engine import GOODS, TOTAL_ACTIONS, public_view

MEMORY_SLOTS = 5
LESSON_MAX_WORDS = 50


class MemoryLocked(Exception):
    """Raised when something tries to write memory during an evaluation match."""


def word_count(text: str) -> int:
    return len(text.split())


@dataclass
class Agent:
    id: str
    name: str
    style: str
    personality: str
    learning: str  # coached | self | none
    lessons: list = field(default_factory=list)
    version: int = 1
    history: list = field(default_factory=list)  # every memory version, append-only

    def __post_init__(self):
        assert len(self.lessons) <= MEMORY_SLOTS
        if not self.history:
            self.history.append({"version": self.version, "lessons": list(self.lessons), "change": "initial"})

    def snapshot(self) -> dict:
        return {"id": self.id, "version": self.version, "lessons": list(self.lessons)}

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "style": self.style, "personality": self.personality,
                "learning": self.learning, "lessons": list(self.lessons), "version": self.version,
                "history": copy.deepcopy(self.history)}

    @staticmethod
    def from_dict(d: dict) -> "Agent":
        return Agent(d["id"], d["name"], d["style"], d["personality"], d["learning"], list(d["lessons"]),
                     d["version"], copy.deepcopy(d["history"]))

    def at_version(self, version: int) -> "Agent":
        """A frozen copy of this agent as it was at `version` (for replays and evaluation)."""
        for h in self.history:
            if h["version"] == version:
                a = copy.deepcopy(self)
                a.lessons, a.version = list(h["lessons"]), version
                return a
        raise KeyError(version)

    def apply_update(self, update: dict, source: str, eval_mode: bool = False) -> dict:
        """Apply a lesson decision {decision, lesson, replace_slot}. Enforces the limits.

        Returns a record of what happened. Invalid decisions leave memory unchanged.
        """
        if eval_mode:
            raise MemoryLocked("eval=true: evaluation matches never write memory")
        before = list(self.lessons)
        decision = update.get("decision")
        lesson = (update.get("lesson") or "").strip()
        rec = {"source": source, "decision": decision, "lesson": lesson, "valid": True, "error": None,
               "before_version": self.version, "before": before}
        if decision in ("add", "replace") and not lesson:
            rec.update(valid=False, error="empty lesson")
        elif decision in ("add", "replace") and word_count(lesson) > LESSON_MAX_WORDS:
            rec.update(valid=False, error=f"lesson has {word_count(lesson)} words, limit {LESSON_MAX_WORDS}")
        elif decision == "add":
            if len(self.lessons) >= MEMORY_SLOTS:
                rec.update(valid=False, error="memory full: add is not allowed, replace or discard")
            else:
                self.lessons.append(lesson)
        elif decision == "replace":
            slot = update.get("replace_slot")
            if not isinstance(slot, int) or not (1 <= slot <= len(self.lessons)):
                rec.update(valid=False, error=f"replace_slot {slot!r} out of range")
            else:
                rec["evicted"] = self.lessons[slot - 1]
                rec["slot"] = slot
                self.lessons[slot - 1] = lesson
        elif decision == "discard":
            pass  # the agent refuses the new lesson; memory unchanged but the decision is logged
        else:
            rec.update(valid=False, error=f"unknown decision {decision!r}")
        if rec["valid"] and decision != "discard":
            self.version += 1
        assert len(self.lessons) <= MEMORY_SLOTS
        assert all(word_count(l) <= LESSON_MAX_WORDS for l in self.lessons)
        rec["after_version"] = self.version
        rec["after"] = list(self.lessons)
        self.history.append({"version": self.version, "lessons": list(self.lessons), "change": rec})
        return rec


RULES = f"""How the duel works:
- Two traders split a pool of goods: tea, silk and saffron, in whole units. Every unit must go to one side.
- Each side has private values per unit. You know only yours. The whole pool is worth 30 points to you.
- There are {TOTAL_ACTIONS} actions in total, alternating between the two sides. Then the duel ends.
- On your action you may: make an offer (a complete split; it replaces any open offer), accept the other side's
  open offer by its id, or reject the other side's open offer (this closes it).
- Your message is talk only. Nothing in a message is binding; only offers and acceptances count.
- An invalid action (impossible split, wrong id, accepting your own offer) wastes your action.
- If no offer is accepted by the end, you receive only your impasse value.
- Your score is the value of what you receive divided by the value of the whole pool to you.
  Your only goal is to maximise your own score."""

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["offer", "accept", "reject"]},
        "offer_id": {"type": ["string", "null"], "description": "id of the other side's open offer, for accept or reject"},
        "you_get": {"type": ["object", "null"], "properties": {g: {"type": "integer"} for g in GOODS},
                    "required": list(GOODS), "additionalProperties": False},
        "they_get": {"type": ["object", "null"], "properties": {g: {"type": "integer"} for g in GOODS},
                     "required": list(GOODS), "additionalProperties": False},
        "message": {"type": "string", "description": "one or two sentences to the other trader"},
    },
    "required": ["action", "offer_id", "you_get", "they_get", "message"],
    "additionalProperties": False,
}

LESSON_SCHEMA = {
    "type": "object",
    "properties": {
        "lesson": {"type": "string", "description": f"one lesson, at most {LESSON_MAX_WORDS} words"},
        "decision": {"type": "string", "enum": ["add", "replace", "discard"]},
        "replace_slot": {"type": ["integer", "null"], "description": "1-based slot to overwrite when decision is replace"},
        "reason": {"type": "string"},
    },
    "required": ["lesson", "decision", "replace_slot", "reason"],
    "additionalProperties": False,
}


def lessons_block(lessons: list) -> str:
    if not lessons:
        return "Your memory is empty."
    return "Your memory (lessons you chose to keep):\n" + "\n".join(f"{i}. {l}" for i, l in enumerate(lessons, 1))


def play_prompt(agent: Agent, match, role: str) -> tuple[str, str]:
    """System and user prompt for one action. Only this agent's private values appear."""
    system = (f"You are {agent.name}, a trader in a negotiation duel.\n{agent.personality}\n\n{RULES}\n\n"
              f"{lessons_block(agent.lessons)}\n\nAnswer with exactly one action in the required JSON format.")
    view = public_view(match, role)
    user = ("Current state of the duel (from your side):\n" + json.dumps(view, indent=1) +
            f"\n\nIt is action {view['action_number']} of {view['total_actions']}. Choose your action.")
    return system, user


def lesson_prompt(agent: Agent, batch_summary: str, feedback: str | None) -> tuple[str, str]:
    """Prompt for the memory update. Coached and self-reflective branches get the same inputs,
    except that the coached one also gets the coach's note."""
    system = (f"You are {agent.name}, a trader in negotiation duels.\n{agent.personality}\n\n{RULES}\n\n"
              f"{lessons_block(agent.lessons)}\n\nYour memory holds at most {MEMORY_SLOTS} lessons of at most "
              f"{LESSON_MAX_WORDS} words. Write one new lesson, then decide: add it (only if a slot is free), "
              f"replace an existing slot, or discard the new lesson if your current lessons are better.")
    if feedback:
        task = f"Your coach read the transcripts and wrote this note:\n\"{feedback}\"\n\nTurn the note into one lesson."
    else:
        task = "Nobody coaches you. Review your own duels and write one lesson for yourself."
    user = f"Your last batch of duels, with the other side's values revealed:\n{batch_summary}\n\n{task}"
    return system, user
