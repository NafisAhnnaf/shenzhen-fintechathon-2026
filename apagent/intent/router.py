"""Intent router and conformal clarification (plan 3.6; KnowNo, Ren et al. 2023).

Calibration score: 1 - p(true option). q_hat is the ceil((n+1)(1-alpha))/n quantile of the scores.
At run time the set holds every option with p >= 1 - q_hat. If new requests resemble calibration requests,
the true intent is in the intent set with probability >= 1 - alpha_I and the true key slot value is in its set
with probability >= 1 - alpha_S, whatever the decider's own calibration.

One intent and one slot value: show the plan. Two or three: one question with buttons. More, or only
UNSUPPORTED: say what the agent can do. Never more than one question per turn.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from ..config import DATA_DIR, SETTINGS
from ..policies import check_router_input
from . import decide as D
from .catalogue import CATALOGUE, INTENTS, WHAT_IT_CAN_DO
from .requests_data import R, request_state, split

QHAT_FILE = DATA_DIR / "intent_qhat.json"  # the rule decider's calibration


def qhat_file(name: str):
    return QHAT_FILE if name == "rules" else DATA_DIR / f"intent_qhat_{name}.json"


def slot_options(slot: str, state: dict) -> list[str]:
    if slot == "supplier":
        mats = sorted({m for s in state["suppliers"].values() for m in s["materials"]})
        return list(state["suppliers"]) + [f"MAT:{m}" for m in mats] + ["ALL"]
    if slot == "bill":
        return list(state["bills"])
    if slot == "bundle":
        return ["careful", "standard", "more", "most"]
    raise KeyError(slot)


def qhat(scores: list[float], alpha: float) -> float:
    n = len(scores)
    k = math.ceil((n + 1) * (1 - alpha))
    if k > n:
        return 1.0  # not enough calibration data for this alpha: every option is in the set
    return float(np.sort(scores)[k - 1])


@dataclass
class Route:
    text: str
    intent_probs: dict
    intent_set: list
    slot: Optional[str]
    slot_probs: dict
    slot_set: list
    window: str
    exclusions: list
    topic: str
    outcome: str  # plan, ask_intent, ask_slot, missing_slot, unsupported
    question: Optional[dict] = None
    intent: Optional[str] = None
    value: Optional[str] = None

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Router:
    decider: object = field(default_factory=D.default_decider)
    q_intent: float = 1.0
    q_slot: float = 1.0
    alpha_intent: float = SETTINGS.alpha_intent
    alpha_slot: float = SETTINGS.alpha_slot

    # ------------------------------------------------------------------ calibration
    def calibrate(self, rows: list, state: dict) -> dict:
        si, ss = [], []
        for text, intent, key, *_ in rows:
            st = {**state, "text": text}
            pi = self.decider.decide(D.Schema("intent", INTENTS), st)
            si.append(1 - pi.get(intent, 0.0))
            slot = CATALOGUE[intent].key_slot
            if slot and key is not None:
                ps = self.decider.decide(D.Schema(slot, slot_options(slot, state)), st)
                ss.append(1 - ps.get(key, 0.0))
        self.q_intent = qhat(si, self.alpha_intent)
        self.q_slot = qhat(ss, self.alpha_slot)
        out = {"q_intent": self.q_intent, "q_slot": self.q_slot, "n_intent": len(si), "n_slot": len(ss),
               "alpha_intent": self.alpha_intent, "alpha_slot": self.alpha_slot, "decider": self.decider.name}
        return out

    def save(self) -> None:
        qhat_file(self.decider.name).write_text(json.dumps({
            "q_intent": self.q_intent, "q_slot": self.q_slot, "alpha_intent": self.alpha_intent,
            "alpha_slot": self.alpha_slot, "decider": self.decider.name}))

    @staticmethod
    def load(decider=None) -> "Router":
        r = Router(decider or D.default_decider())
        r.q_by = {}
        rules = qhat_file("rules")
        if rules.exists():
            d = json.loads(rules.read_text())
            r.q_by["rules"] = (d["q_intent"], d["q_slot"])
        if isinstance(r.decider, D.FallbackDecider):
            f = qhat_file(r.decider.name)
            if f.exists():
                d = json.loads(f.read_text())
                r.q_by[r.decider.name] = (d["q_intent"], d["q_slot"])
                r.provisional = False
            else:
                # Not calibrated on the model yet (python -m apagent.intent.calibrate_llm does it, about 100 model
                # calls): use the rule decider's thresholds until then, and say so.
                r.q_by[r.decider.name] = r.q_by.get("rules", (1.0, 1.0))
                r.provisional = True
            r.q_intent, r.q_slot = r.q_by[r.decider.name]
            return r
        if "rules" in r.q_by and r.decider.name == "rules":
            r.q_intent, r.q_slot = r.q_by["rules"]
            return r
        r.calibrate(split()[0], request_state())
        r.save()
        return r

    def _q(self) -> tuple[float, float]:
        """Thresholds for whichever decider answered (the model, or the rules when it fell back)."""
        last = getattr(self.decider, "last", self.decider.name)
        return getattr(self, "q_by", {}).get(last, (self.q_intent, self.q_slot))

    # ------------------------------------------------------------------ routing
    def route(self, text: str, state: dict, role: str = "owner") -> Route:
        check_router_input(state)  # S8: trusted state only, never raw supplier text
        st = {**state, "text": text}
        pi = self.decider.decide(D.Schema("intent", INTENTS), st)
        q_intent = self._q()[0]
        iset = sorted([k for k, p in pi.items() if p >= 1 - q_intent], key=lambda k: -pi[k])
        window, excl, topic = D.window_of(text), D.exclusions_of(text), D.topic_of(text)
        base = dict(text=text, intent_probs=pi, window=window, exclusions=excl, topic=topic)
        supported = [i for i in iset if i != "UNSUPPORTED"]
        if not supported or len(iset) > 3:
            return Route(**base, intent_set=iset, slot=None, slot_probs={}, slot_set=[], outcome="unsupported",
                         question={"kind": "unsupported", "text": "I can't do that here. Here is what I can do:",
                                   "examples": WHAT_IT_CAN_DO})
        if len(iset) > 1:
            return Route(**base, intent_set=iset, slot=None, slot_probs={}, slot_set=[], outcome="ask_intent",
                         question={"kind": "intent", "text": "Which do you mean?",
                                   "options": [{"intent": i, "label": CATALOGUE[i].example} for i in iset]})
        intent = iset[0]
        spec = CATALOGUE[intent]
        if role not in spec.roles:
            return Route(**base, intent_set=iset, slot=None, slot_probs={}, slot_set=[], outcome="unsupported",
                         intent=intent, question={"kind": "role", "text": f"Only the owner can do this ({intent}).",
                                                   "examples": WHAT_IT_CAN_DO})
        if spec.key_slot is None:
            return Route(**base, intent_set=iset, slot=None, slot_probs={}, slot_set=[], outcome="plan", intent=intent)
        opts = slot_options(spec.key_slot, state)
        ps = self.decider.decide(D.Schema(spec.key_slot, opts), st)
        evidence = bool(ps) and max(ps.values()) > 1.0 / len(opts) + 1e-9
        sset = sorted([k for k, p in ps.items() if p >= 1 - self._q()[1]], key=lambda k: -ps[k]) if evidence else []
        if not sset:
            if spec.required:
                top = sorted(ps, key=lambda k: -ps[k])[:3] if evidence else []
                return Route(**base, intent_set=iset, slot=spec.key_slot, slot_probs=ps, slot_set=[], outcome="missing_slot",
                             intent=intent, question={"kind": "slot", "slot": spec.key_slot,
                                                      "text": f"Which {spec.key_slot}?", "options": top})
            return Route(**base, intent_set=iset, slot=spec.key_slot, slot_probs=ps, slot_set=["ALL"], outcome="plan",
                         intent=intent, value="ALL")
        if len(sset) == 1:
            return Route(**base, intent_set=iset, slot=spec.key_slot, slot_probs=ps, slot_set=sset, outcome="plan",
                         intent=intent, value=sset[0])
        if len(sset) <= 3:
            return Route(**base, intent_set=iset, slot=spec.key_slot, slot_probs=ps, slot_set=sset, outcome="ask_slot",
                         intent=intent, question={"kind": "slot", "slot": spec.key_slot,
                                                  "text": f"Which {spec.key_slot} do you mean?", "options": sset})
        top = sset[:3]
        return Route(**base, intent_set=iset, slot=spec.key_slot, slot_probs=ps, slot_set=sset, outcome="missing_slot",
                     intent=intent, question={"kind": "slot", "slot": spec.key_slot,
                                              "text": f"Which {spec.key_slot}? I see several.", "options": top})


def evaluate(router: Router, rows: list, state: dict) -> dict:
    """Coverage of the sets, question rate, accuracy when no question is asked, UNSUPPORTED refusals."""
    cov_i = cov_s = n_s = asked = acc_n = acc_ok = unsup_ok = unsup_n = 0
    for text, intent, key, *_ in rows:
        r = router.route(text, state)
        in_i = intent in r.intent_set or (intent == "UNSUPPORTED" and r.outcome == "unsupported")
        cov_i += in_i
        if CATALOGUE[intent].key_slot and key is not None and r.intent == intent:
            n_s += 1
            cov_s += key in r.slot_set
        if r.outcome in ("ask_intent", "ask_slot", "missing_slot"):
            asked += 1
        elif r.outcome == "plan":
            acc_n += 1
            acc_ok += r.intent == intent and (key is None or r.value == key or CATALOGUE[intent].key_slot is None)
        if intent == "UNSUPPORTED":
            unsup_n += 1
            unsup_ok += r.outcome == "unsupported"
    n = len(rows)
    return {"n": n, "intent_coverage": cov_i / n, "slot_coverage": cov_s / max(1, n_s), "question_rate": asked / n,
            "accuracy_without_question": acc_ok / max(1, acc_n), "unsupported_refused": unsup_ok / max(1, unsup_n),
            "q_intent": router.q_intent, "q_slot": router.q_slot}
