"""Duel engine: a rule-scored, alternating-offer negotiation over three goods.

The model never decides anything here. It only proposes actions; this module
validates them, keeps the state, and computes the scores.

Rules (also written in README.md):
- Three goods with public integer stocks. Each side has private integer values
  per good. The value of the whole pool is the same for both sides (30).
- 8 actions in total, alternating: the first mover acts on actions 1, 3, 5, 7,
  the second mover on 2, 4, 6, 8.
- An offer is a complete allocation in whole units: every unit of every good goes
  to one side. A new offer replaces the open offer (it is a counter-offer).
- An acceptance names the id of the opponent's current open offer. Accepting your
  own offer, a superseded offer, or when nothing is open is invalid.
- A rejection names the id of the opponent's open offer and closes it; nothing is
  on the table until the next offer. Rejecting a wrong id, or when no opponent
  offer is open, is invalid.
- An invalid action costs the turn (it still counts as one of the 8) and is logged.
- The message attached to an action is cheap talk and binds nothing.
- An agreement is terminal. With no agreement after 8 actions, both sides get the
  impasse value fixed before the match.
- Score = value received / value of the whole pool, for each side, in [0, 1].
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field

GOODS = ("tea", "silk", "saffron")
TOTAL_ACTIONS = 8
POOL_VALUE = 30
ROLES = ("first", "second")


class MatchOver(Exception):
    """Raised when an action is submitted after the match has ended."""


@dataclass(frozen=True)
class Scenario:
    id: str
    stock: dict
    values: dict  # role -> {good: int}
    impasse: dict  # role -> int (value units, fixed before the match)

    def max_value(self, role: str) -> int:
        return sum(self.stock[g] * self.values[role][g] for g in GOODS)

    def to_dict(self) -> dict:
        return {"id": self.id, "stock": dict(self.stock), "values": copy.deepcopy(self.values),
                "impasse": dict(self.impasse)}

    @staticmethod
    def from_dict(d: dict) -> "Scenario":
        return Scenario(d["id"], d["stock"], d["values"], d["impasse"])

    def mirrored(self, new_id: str) -> "Scenario":
        """Same goods, values swapped between roles: used to play both sides of a pairing."""
        return Scenario(new_id, dict(self.stock),
                        {"first": dict(self.values["second"]), "second": dict(self.values["first"])},
                        {"first": self.impasse["second"], "second": self.impasse["first"]})


def make_scenarios(seed: int, n: int, stock=None, impasse: int = 6) -> list[Scenario]:
    """Seeded generator of private-value configurations (the model has no seed; this does)."""
    stock = stock or {"tea": 4, "silk": 3, "saffron": 2}
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        vals = {}
        for role in ROLES:
            while True:
                v = {g: rng.randint(0, 10) for g in GOODS}
                if sum(stock[g] * v[g] for g in GOODS) == POOL_VALUE and sum(1 for g in GOODS if v[g] > 0) >= 2:
                    vals[role] = v
                    break
        if vals["first"] == vals["second"]:
            continue
        out.append(Scenario(f"S{len(out) + 1}", dict(stock), vals, {r: impasse for r in ROLES}))
    return out


def other(role: str) -> str:
    return "second" if role == "first" else "first"


@dataclass
class Match:
    scenario: Scenario
    actions: list = field(default_factory=list)  # every submitted action, valid or not
    open_offer: dict | None = None
    offers: dict = field(default_factory=dict)  # id -> offer
    status: str = "open"  # open | agreed | impasse
    agreement: dict | None = None  # role -> {good: units}

    @property
    def turn(self) -> int:
        return len(self.actions)  # 0-based index of the next action

    @property
    def actor(self) -> str:
        return ROLES[self.turn % 2]

    @property
    def over(self) -> bool:
        return self.status != "open"

    def _validate(self, role: str, act: dict) -> tuple[bool, str, dict | None]:
        kind = act.get("action")
        if kind == "offer":
            yg, tg = act.get("you_get"), act.get("they_get")
            if not isinstance(yg, dict) or not isinstance(tg, dict):
                return False, "offer without a complete allocation", None
            alloc = {role: {}, other(role): {}}
            for g in GOODS:
                a, b = yg.get(g), tg.get(g)
                if not (isinstance(a, int) and isinstance(b, int)) or isinstance(a, bool) or isinstance(b, bool):
                    return False, f"non-integer quantity for {g}", None
                if a < 0 or b < 0:
                    return False, f"negative quantity for {g}", None
                if a + b != self.scenario.stock[g]:
                    return False, f"{g}: {a}+{b} does not equal the stock of {self.scenario.stock[g]}", None
                alloc[role][g], alloc[other(role)][g] = a, b
            return True, "", alloc
        if kind == "accept":
            oid = act.get("offer_id")
            if not isinstance(oid, str):
                return False, "offer_id must be a string", None
            if self.open_offer is None:
                return False, "accept with no open offer", None
            if oid != self.open_offer["id"]:
                if oid in self.offers:
                    if self.offers[oid]["by"] == role:
                        return False, "cannot accept your own offer", None
                    return False, f"offer {oid} is no longer open", None
                return False, f"unknown offer id {oid!r}", None
            if self.open_offer["by"] == role:
                return False, "cannot accept your own offer", None
            return True, "", None
        if kind == "reject":
            if not isinstance(act.get("offer_id"), str):
                return False, "offer_id must be a string", None
            if self.open_offer is None or self.open_offer["by"] == role:
                return False, "nothing from the other side to reject", None
            if act.get("offer_id") != self.open_offer["id"]:
                return False, f"reject must name the open offer {self.open_offer['id']}, not {act.get('offer_id')!r}", None
            return True, "", None
        return False, f"unknown action {kind!r}", None

    def apply(self, role: str, act: dict | None, raw: str | None = None) -> dict:
        """Apply one action for `role`. `act=None` means the model output was unusable."""
        if self.over:
            raise MatchOver("the match has ended; no further action is accepted")
        if role != self.actor:
            raise ValueError(f"it is {self.actor}'s turn, not {role}'s")
        n = self.turn + 1
        entry = {"n": n, "role": role, "valid": False, "error": None, "action": None,
                 "message": "", "offer_id": None, "open_after": None}
        if act is not None and not isinstance(act, dict):
            act = None
        if act is None:
            entry["error"] = "unparseable output"
        else:
            entry["message"] = str(act.get("message", ""))[:600]
            ok, err, alloc = self._validate(role, act)
            entry["action"] = act.get("action")
            if not ok:
                entry["error"] = err
                entry["submitted"] = {k: act.get(k) for k in ("action", "offer_id", "you_get", "they_get")}
            else:
                entry["valid"] = True
                if act["action"] == "offer":
                    oid = f"o{len(self.offers) + 1}"
                    offer = {"id": oid, "by": role, "alloc": alloc, "at": n}
                    self.offers[oid] = offer
                    self.open_offer = offer
                    entry["offer_id"] = oid
                    entry["alloc"] = alloc
                elif act["action"] == "accept":
                    entry["offer_id"] = self.open_offer["id"]
                    self.agreement = copy.deepcopy(self.open_offer["alloc"])
                    self.status = "agreed"
                elif act["action"] == "reject":
                    entry["offer_id"] = self.open_offer["id"]
                    self.open_offer = None
        if raw is not None:
            entry["raw"] = raw
        entry["open_after"] = self.open_offer["id"] if self.open_offer else None
        self.actions.append(entry)
        if self.status == "open" and len(self.actions) >= TOTAL_ACTIONS:
            self.status = "impasse"
        return entry

    def value(self, role: str) -> int:
        if self.status == "agreed":
            return sum(self.agreement[role][g] * self.scenario.values[role][g] for g in GOODS)
        if self.status == "impasse":
            return self.scenario.impasse[role]
        raise ValueError("match not finished")

    def scores(self) -> dict:
        return {r: score(self.scenario, self.status, self.agreement, r) for r in ROLES}


def score(scenario: Scenario, status: str, agreement: dict | None, role: str) -> float:
    """Utility obtained over maximum possible utility (the whole pool). Pure function."""
    mx = scenario.max_value(role)
    if status == "agreed":
        got = sum(agreement[role][g] * scenario.values[role][g] for g in GOODS)
    elif status == "impasse":
        got = scenario.impasse[role]
    else:
        raise ValueError(f"no score for status {status!r}")
    return round(got / mx, 6)


def public_view(match: Match, role: str) -> dict:
    """What `role` may see: stock, its own values, the action log. Never the opponent's values."""
    s = match.scenario
    log = []
    for a in match.actions:
        who = "you" if a["role"] == role else "them"
        item = {"n": a["n"], "by": who, "valid": a["valid"], "action": a["action"], "message": a["message"]}
        if a.get("alloc"):
            item["you_get"] = a["alloc"][role]
            item["they_get"] = a["alloc"][other(role)]
            item["offer_id"] = a["offer_id"]
        elif a["offer_id"]:
            item["offer_id"] = a["offer_id"]
        if not a["valid"]:
            item["error"] = a["error"]
        log.append(item)
    open_offer = None
    if match.open_offer:
        o = match.open_offer
        open_offer = {"id": o["id"], "by": "you" if o["by"] == role else "them",
                      "you_get": o["alloc"][role], "they_get": o["alloc"][other(role)]}
    return {"stock": dict(s.stock), "your_values": dict(s.values[role]), "pool_value_to_you": s.max_value(role),
            "impasse_value": s.impasse[role], "action_number": match.turn + 1, "total_actions": TOTAL_ACTIONS,
            "you_move": role, "log": log, "open_offer": open_offer}
