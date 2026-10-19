"""decide(schema, state) -> {option: p}: one interface, several backends (plan 3.8).

- RuleDecider: deterministic, offline. Keyword and fuzzy-match features, softmax over options.
- LLMDecider: OpenAI-compatible chat model with a JSON schema whose keys are exactly the options.
- JevDecider: TypeSafe AI's Jev, one Choice question per schema (DECIDER=jev, TYPESAFE_API_KEY).
Whatever the backend, the answer is always an option from the list; a wrong option is handled by the conformal
sets and the preview.
"""
from __future__ import annotations

import difflib
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Optional

from ..config import load_env
from .catalogue import BUNDLES, CATALOGUE, EXCLUSIONS, INTENTS, TOPICS, WINDOWS


@dataclass
class Schema:
    name: str
    options: list[str]


def softmax(scores: dict[str, float], temp: float = 1.0) -> dict[str, float]:
    if not scores:
        return {}
    m = max(scores.values())
    ex = {k: math.exp((v - m) / temp) for k, v in scores.items()}
    z = sum(ex.values())
    return {k: v / z for k, v in ex.items()}


# --------------------------------------------------------------------------- intent rules
INTENT_RULES: dict[str, list[tuple[str, float]]] = {
    "ASK_STATUS": [(r"\bhow much\b", 3), (r"\bwhat do we owe\b", 4), (r"\bowe\b", 2.5), (r"\b(status|outstanding|unpaid|open bills?|balance)\b", 2),
                   (r"\b(show|list|tell me)\b", 1.5), (r"\btotal\b", 1), (r"^(what|which|how many)\b", 1), (r"\bdo we have\b", 1.5)],
    "ASK_WHY": [(r"\bwhy\b", 4), (r"\b(reason|explain)\b", 3), (r"\b(held|flagged|stuck|blocked|not paid|on hold)\b", 1.5), (r"\bwhat happened\b", 2)],
    "WHAT_IF": [(r"\bwhat (if|happens)\b", 4), (r"\b(simulate|scenario|impact|effect)\b", 3), (r"\bif we (paid|pay)\b", 3),
                (r"\b(cash|cash ?flow|runway)\b", 1.5), (r"\bwould\b", 1)],
    "PAY_SET": [(r"^(please )?(pay|settle|clear)\b", 4), (r"\b(pay|settle|clear)\b", 2.5), (r"\b(run|process|send) (the )?payments?\b", 3),
                (r"\bexcept\b|\bbut not\b|\bexcluding\b|\bapart from\b|\bleave out\b", 1.5), (r"\bdue\b", 1), (r"\bgo ahead and pay\b", 2)],
    "HOLD_SET": [(r"^(please )?(hold|park)\b", 4), (r"\bhold\b", 2), (r"\b(don'?t|do not) pay\b", 3.5), (r"\buntil\b", 1.5),
                 (r"\bput .* on hold\b", 3), (r"\bwait\b", 1), (r"\bstop paying\b", 3)],
    "RELEASE": [(r"\brelease\b", 4.5), (r"\b(unhold|lift the hold|remove the hold|take .* off hold)\b", 4), (r"\bgo ahead with\b", 2)],
    "QUERY_SUPPLIER": [(r"^(please )?(ask|email|query|chase|contact|message|write to)\b", 4), (r"\b(ask|query|chase|contact|email|write to)\b", 2.5),
                       (r"\b(dispute|question|challenge)\b", 1.5), (r"\babout the (price|quantity|credit)\b", 1.5)],
    "TIGHTEN": [(r"\b(careful|cautious|strict|stricter) with\b", 4), (r"\bwatch\b", 2), (r"\b(extra|more) checks? on\b", 3.5),
                (r"\bprobation\b", 3), (r"\bdon'?t trust\b", 3), (r"\bkeep an eye on\b", 3)],
    "SET_DIAL": [(r"\bmore careful\b", 3), (r"\b(less careful|loosen|relax)\b", 3), (r"\bpay more on its own\b", 4), (r"\b(autonomy|risk level|risk dial|dial)\b", 3),
                 (r"\b(this|next) (month|quarter)\b", 1), (r"\b(tighten up|safer|tighter)\b", 2), (r"\b(standard|normal|default) (settings|mode|level)\b", 3),
                 (r"\bon its own\b", 1.5), (r"\bby itself\b", 1.5), (r"\bfewer approvals\b", 3), (r"\bmore approvals\b", 3)],
    "PAUSE": [(r"\b(stop|halt|freeze|pause) (all|every|everything|the agent|payments)\b", 4.5), (r"\bpause\b", 3), (r"\bemergency\b", 2),
              (r"\bstop everything\b", 4.5), (r"\bkill switch\b", 4)],
    "RESUME": [(r"\b(resume|unpause|restart)\b", 4.5), (r"\bstart (again|paying again|payments again)\b", 4.5), (r"\bturn .* back on\b", 4)],
    "UNSUPPORTED": [(r"\b(add|create|register|set up) (a |an |this |the )?(new )?(bank|account|payee|supplier|vendor|wallet)\b", 5),
                    (r"\b(change|update|edit) .{0,20}\b(bank|account|wallet|details|address)\b", 5), (r"\b(withdraw|move|transfer)\b.{0,30}\b(funds|money|vault|pool|balance)\b", 5),
                    (r"\bsend .{0,20}\bto 0x[0-9a-f]+", 5), (r"\b(delete|remove) (the )?(supplier|payee|log)\b", 4.5), (r"\b(buy|sell|trade|invest|hedge)\b", 3),
                    (r"\bincrease .{0,15}\b(cap|limit)\b", 4.5), (r"\bpassword|seed phrase|private key\b", 5), (r"\bpay\b.{0,20}\b(cash|personally|my)\b", 3)],
}
PRIOR = {k: 0.0 for k in INTENTS}
PRIOR["UNSUPPORTED"] = 0.4


def intent_scores(text: str) -> dict[str, float]:
    t = text.lower().strip()
    return {k: PRIOR[k] + sum(w for pat, w in INTENT_RULES[k] if re.search(pat, t)) for k in INTENTS}


# --------------------------------------------------------------------------- slot rules
MATERIAL_WORDS = {
    "CU-ROD": ["copper"], "AL-SHEET": ["aluminium", "aluminum"], "ZN-ALLOY": ["zinc"], "NI-ANODE": ["nickel", "plating"],
    "SN-SOLDER": ["solder", "tin"], "ABS-RESIN": ["resin", "plastic", "plastics", "abs"], "CARTON": ["carton", "cartons", "packaging", "boxes"],
    "FASTENER": ["fastener", "fasteners", "screws", "bolts"], "LUBE": ["lubricant", "lube", "oil"], "PCB": ["pcb", "circuit", "boards"],
}
STOP = {"ltd", "co", "co.", "company", "limited", "the", "hk", "(hk)", "trading", "supply", "supplies", "works", "products", "&"}
MATERIAL_TOKENS = {w for ws in MATERIAL_WORDS.values() for w in ws} | {"metals", "alloys", "wire"}


def _name_tokens(name: str) -> list[str]:
    """Distinctive name words. Material words are not names: 'copper' alone must not pick a supplier."""
    return [w for w in re.findall(r"[a-z]+", name.lower()) if w not in STOP and w not in MATERIAL_TOKENS and len(w) > 2]


def supplier_scores(text: str, state: dict) -> dict[str, float]:
    """Options: supplier ids, 'MAT:<code>' (all suppliers of a material), 'ALL'."""
    t = text.lower()
    words = set(re.findall(r"[a-z]+", t))
    scores: dict[str, float] = {}
    for sid, s in state["suppliers"].items():
        toks = _name_tokens(s["name"])
        hit = 0.0
        for tok in toks:
            if tok in words:
                hit += 3.0
            elif any(difflib.SequenceMatcher(None, tok, w).ratio() > 0.85 for w in words if len(w) > 3):
                hit += 2.0
        if hit:
            scores[sid] = hit
    named = set(scores)
    singular = re.search(r"\b(supplier|vendor|guy|guys|people|company|one)\b", t) is not None
    for code, mw in MATERIAL_WORDS.items():
        if not any(re.search(rf"\b{w}\b", t) for w in mw):
            continue
        holders = [sid for sid, s in state["suppliers"].items() if code in s["materials"]]
        named_holders = [sid for sid in holders if sid in named]
        if named_holders:  # "Shatin PCB", "Ganjiang Copper": the material confirms the named supplier
            for sid in named_holders:
                scores[sid] += 1.0
        elif singular and holders:
            for sid in holders:
                scores[sid] = scores.get(sid, 0.0) + 2.5
        else:
            scores[f"MAT:{code}"] = scores.get(f"MAT:{code}", 0.0) + 3.5
    if not scores:
        # No supplier or material named: the request is about all suppliers.
        scores["ALL"] = 3.5 if re.search(r"\b(all|every|everything|everyone|any|total)\b", t) else 2.5
    return scores


def bill_scores(text: str, state: dict) -> dict[str, float]:
    t = text.lower()
    scores: dict[str, float] = {}
    nums = re.findall(r"\b(?:bill|invoice|inv|#)?\s*([a-z]{0,3}-?\d{3,8})\b", t)
    for bno, b in state["bills"].items():
        for n in nums:
            n = n.strip("-")
            if n == bno.lower() or n == b["inv_no"].lower() or (n.isdigit() and bno.endswith(n)):
                scores[bno] = scores.get(bno, 0.0) + 5.0
    if not scores:
        # "the held one from Acme", "the copper bill": fall back to supplier match over open bills
        sup = supplier_scores(text, state)
        for bno, b in state["bills"].items():
            if b["supplier_id"] in sup:
                scores[bno] = sup[b["supplier_id"]] * 0.6 + (1.0 if b.get("status") == "held" else 0.0)
    return scores


def bundle_scores(text: str) -> dict[str, float]:
    t = text.lower()
    s = {b: 0.0 for b in BUNDLES}
    if re.search(r"\b(more careful|safer|tighter|tighten|cautious|stricter|more approvals)\b", t):
        s["careful"] += 4
    if re.search(r"\b(less careful|loosen|relax|pay more on its own|more on its own|fewer approvals|more autonomy)\b", t):
        s["more"] += 4
    if re.search(r"\b(maximum|max|most) (autonomy|on its own)\b|\bas much as possible\b", t):
        s["most"] += 5
    if re.search(r"\b(standard|normal|default|usual|back to)\b", t):
        s["standard"] += 4
    return s


def window_of(text: str) -> str:
    t = text.lower()
    for w, pat in [("today", r"\btoday\b"), ("this_week", r"\bthis week\b"), ("next_week", r"\bnext week\b"),
                   ("this_month", r"\bthis month\b"), ("overdue", r"\b(overdue|late|past due)\b")]:
        if re.search(pat, t):
            return w
    return "all"


def exclusions_of(text: str) -> list[str]:
    t = text.lower()
    m = re.search(r"\b(except|but not|excluding|apart from|leave out|other than|without)\b(.*)", t)
    if not m:
        return []
    tail = m.group(2)
    out = []
    for ex, pat in [("disputed", r"disput|query|queried|contested"), ("flagged", r"flag|suspicious"),
                    ("probation", r"probation"), ("above_cap", r"large|big|above (the )?cap|over")]:
        if re.search(pat, tail):
            out.append(ex)
    return out


def topic_of(text: str) -> str:
    t = text.lower()
    for tp in TOPICS:
        if tp in t:
            return tp
    return "price"


# --------------------------------------------------------------------------- deciders
class RuleDecider:
    name = "rules"

    def __init__(self, temp: float = 1.0):
        self.temp = temp

    def decide(self, schema: Schema, state: dict) -> dict[str, float]:
        text = state["text"]
        if schema.name == "intent":
            raw = intent_scores(text)
        elif schema.name == "supplier":
            raw = supplier_scores(text, state)
        elif schema.name == "bill":
            raw = bill_scores(text, state)
        elif schema.name == "bundle":
            raw = bundle_scores(text)
        elif schema.name == "reply":
            raw = reply_scores(text)
        else:
            raise KeyError(schema.name)
        raw = {k: v for k, v in raw.items() if k in schema.options}
        if not raw:
            return {}
        # Options with no evidence get a floor so the distribution covers the whole list.
        full = {o: raw.get(o, -3.0) for o in schema.options} if len(schema.options) <= 32 else raw
        return softmax(full, self.temp)


class LLMDecider:
    """OpenAI-compatible chat endpoint; the JSON schema lists exactly the options. Never sees supplier text
    for intent/slot schemas (S8): the caller passes the user's request and trusted state only."""

    name = "llm"

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None):
        load_env()
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("gemini_api_key", "")
        key = api_key if api_key is not None else (os.environ.get("LLM_API_KEY") or gemini_key or "")
        is_gemini = bool(gemini_key) and (key == gemini_key or not os.environ.get("LLM_API_KEY"))
        default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai" if is_gemini else "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
        default_model = "gemini-3.6-flash" if is_gemini else "qwen-plus"

        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", default_base_url)).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", default_model)
        self.api_key = key

    def available(self) -> bool:
        return bool(self.api_key)

    def decide(self, schema: Schema, state: dict) -> dict[str, float]:
        import httpx

        opts = schema.options
        js = {"type": "object", "additionalProperties": False, "required": opts,
              "properties": {o: {"type": "number", "minimum": 0, "maximum": 1} for o in opts}}
        ctx = {k: v for k, v in state.items() if k != "text"}
        prompt = (f"Choose the {schema.name} for this request from the options. Return a probability for every option; "
                  f"they must sum to 1.\nRequest: {state['text']}\nContext (trusted): {json.dumps(ctx)[:6000]}")
        r = httpx.post(f"{self.base_url}/chat/completions", timeout=60,
                       headers={"Authorization": f"Bearer {self.api_key}"},
                       json={"model": self.model, "temperature": 0, "messages": [{"role": "user", "content": prompt}],
                             "response_format": {"type": "json_schema", "json_schema": {"name": schema.name, "schema": js, "strict": True}}})
        r.raise_for_status()
        p = json.loads(r.json()["choices"][0]["message"]["content"])
        p = {k: max(0.0, float(p.get(k, 0.0))) for k in opts}
        z = sum(p.values()) or 1.0
        return {k: v / z for k, v in p.items()}


INTENT_TEXT = {
    "ASK_STATUS": "Asks how much is owed or which bills are open; reads only, changes nothing",
    "ASK_WHY": "Asks why a specific bill was held, flagged or not paid",
    "WHAT_IF": "Asks what would happen (for example to cash) if some bills were paid; a hypothetical, not an order",
    "PAY_SET": "Orders payment of a supplier's or a group's bills now",
    "HOLD_SET": "Orders that some bills are not paid yet, put on hold",
    "RELEASE": "Orders that an existing hold is lifted",
    "QUERY_SUPPLIER": "Asks the agent to contact a supplier about a bill (price, quantity or credit)",
    "TIGHTEN": "Asks for extra caution or checks on one supplier",
    "SET_DIAL": "Changes how much the agent pays on its own overall (more careful, standard, more autonomy)",
    "PAUSE": "Stops all payments immediately",
    "RESUME": "Restarts payments after a pause",
    "UNSUPPORTED": "Anything else: adding or changing payees or bank details, moving funds, trading, raising caps, secrets",
}
BUNDLE_TEXT = {"careful": "More careful: fewer payments on its own, more approvals",
               "standard": "Standard or default settings",
               "more": "Less careful: pays more on its own, fewer approvals",
               "most": "Maximum autonomy"}
JEV_QUESTION = {"intent": "What the accounts-payable request asks the agent to do",
                "supplier": "Which supplier or group of suppliers the request is about",
                "bill": "Which bill the request is about",
                "bundle": "Which autonomy setting the request asks for",
                "reply": "What the supplier's reply says"}
REPLY_TEXT = {"credit_note": "The supplier agrees to issue or attaches a credit note",
              "bank_change": "The supplier asks to pay into new or changed bank details",
              "other": "Anything else"}


def jev_criteria(schema: Schema, state: dict) -> dict[str, str]:
    """A description for every option: Jev reads the option names and their descriptions."""
    sups = state.get("suppliers", {})
    out = {}
    for o in schema.options:
        if schema.name == "intent":
            out[o] = f"{INTENT_TEXT[o]}. Example: {CATALOGUE[o].example}"
        elif schema.name == "bundle":
            out[o] = BUNDLE_TEXT[o]
        elif schema.name == "reply":
            out[o] = REPLY_TEXT[o]
        elif schema.name == "supplier":
            if o == "ALL":
                out[o] = "All suppliers; the request names no supplier or material"
            elif o.startswith("MAT:"):
                code = o[4:]
                out[o] = f"Every supplier of {' / '.join(MATERIAL_WORDS.get(code, [code]))} ({code})"
            else:
                s = sups[o]
                out[o] = f"The supplier {s['name']} (sells {', '.join(s['materials'])})"
        elif schema.name == "bill":
            b = state["bills"][o]
            name = sups.get(b["supplier_id"], {}).get("name", b["supplier_id"])
            out[o] = f"Bill {o}, invoice {b['inv_no']} from {name}, status {b.get('status', 'open')}"
        else:
            raise KeyError(schema.name)
    return out


class JevDecider:
    """TypeSafe AI's Jev (System One model): one Choice question over exactly the options, with a probability for
    every option. Same S8 rule as the LLM backend: the state is the user's request and trusted context only."""

    name = "jev"

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or os.environ.get("JEV_BASE_URL", "https://api.typesafe.ai/v1")).rstrip("/")
        self.model = model or os.environ.get("JEV_MODEL", "jev-latest")
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY", "")

    def available(self) -> bool:
        return bool(self.api_key)

    def decide(self, schema: Schema, state: dict) -> dict[str, float]:
        import httpx

        opts = schema.options
        q = {"type": "choice", "instructions": JEV_QUESTION.get(schema.name, f"Which {schema.name} the request refers to"),
             "criteria": jev_criteria(schema, state)}
        body = {"model": self.model, "state": {"request": state["text"]}, "questions": {schema.name: q}}
        r = httpx.post(f"{self.base_url}/systemone", json=body, timeout=30,
                       headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        p = r.json()["answers"][schema.name]["probabilities"]
        p = {k: max(0.0, float(p.get(k, 0.0))) for k in opts}
        z = sum(p.values()) or 1.0
        return {k: v / z for k, v in p.items()}


def default_decider():
    choice = os.environ.get("DECIDER", "rules")
    for backend in (JevDecider, LLMDecider):
        if choice == backend.name and backend().available():
            return backend()
    return RuleDecider()


# --------------------------------------------------------------------------- supplier replies
REPLY_CLASSES = ["credit_note", "bank_change", "other"]


def reply_scores(text: str) -> dict[str, float]:
    t = text.lower()
    s = {"credit_note": 0.0, "bank_change": 0.0, "other": 0.5}
    if re.search(r"\bcredit note\b|\bcredit memo\b|\bwe (will )?(issue|have issued|attach)\b.*\bcredit\b", t):
        s["credit_note"] += 4
    if re.search(r"\b(new|updated|changed|different) (bank|account|payment) (details|account|instructions)\b"
                 r"|\bpay\b.{0,40}\b(to|into)\b.{0,12}\bnew (account|bank|wallet)\b"
                 r"|\b(changed|change|switched|moved) (our )?(bank|account|banks)\b", t):
        s["bank_change"] += 5
    return s


def classify_reply(text: str, decider=None) -> str:
    d = decider or RuleDecider()
    p = d.decide(Schema("reply", REPLY_CLASSES), {"text": text})
    return max(p, key=p.get)
