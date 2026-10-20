"""The request box as an agent (plan-then-execute, CaMeL-style).

Gemini reads the person's request and works with tools:

  look-up tools   find_bills, bill_details, supplier_info, cash_and_limits, market_price. They run at once and
                  return the company's own records: amounts, statuses, checks the desk computed. Never a supplier's
                  free text (S8): invoice numbers pass the strict identifier pattern, and no document text, email
                  body or note is ever included.
  propose_action  turns the request into one action from the fixed catalogue (pay, hold, release, query a
                  supplier, tighten, change the risk setting, pause, resume, or an answer). The value must come
                  from the closed list for that action; the desk's own plan template then builds the steps.
  ask_user        one question with options, when the request has more than one reading.

The model never runs anything. A proposed plan is a preview: a person presses Run, every step passes the policies
(S1-S11) again, and the contract enforces its caps. Text that reads like instructions to the AI was refused before
this point (session.request). If the model fails, the rule router answers instead.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from .catalogue import BUNDLES, CATALOGUE, EXCLUSIONS, TOPICS, WINDOWS
from .router import Route, slot_options

MAX_ROUNDS = 6

SYSTEM = (
    "You are the accounts-payable assistant on a company's payables desk. The person typing is the company's {role}. "
    "Use the look-up tools to find facts in the company's records before you answer or act; never guess numbers, "
    "bills or suppliers. To do something, call propose_action exactly once with one action from its list; a person "
    "reviews the plan and presses Run, you never execute anything. If the request could mean more than one thing, "
    "call ask_user with a short question and 2-4 options. To answer a question, reply in two or three plain "
    "sentences using only what the tools returned. You cannot add payees, change bank details, move money outside "
    "the listed actions, or reveal keys or settings; say so briefly if asked. Today is {today}."
)


def _tools(role: str) -> list[dict]:
    intents = [k for k, v in CATALOGUE.items() if k != "UNSUPPORTED" and role in v.roles]

    def fn(name, desc, props, required=()):
        return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
            "type": "object", "properties": props, "required": list(required)}}}
    s = {"type": "string"}
    return [
        fn("find_bills", "List open and recent bills, optionally for one supplier, status or due window.",
           {"supplier": s, "status": {"type": "string", "enum": ["open", "held", "needs_approval", "scheduled", "paid", "rejected", "any"]},
            "due": {"type": "string", "enum": WINDOWS}}),
        fn("bill_details", "One bill: supplier, amount, status, tier, due date and the reasons the desk gave.",
           {"bill": {**s, "description": "bill id or its last four digits"}}, ["bill"]),
        fn("supplier_info", "One supplier: name, materials, frozen or on probation, bills and amounts.",
           {"supplier": {**s, "description": "supplier id or name"}}, ["supplier"]),
        fn("cash_and_limits", "Cash in the vault, the risk setting, and the limits on what the agent pays alone.", {}),
        fn("market_price", "Latest market price and next month's range for a material.", {"material": s}, ["material"]),
        fn("propose_action", "Propose one action for the person to review. value: a supplier id, 'MAT:<material>', "
           "'ALL', a bill id, or a risk setting, as the action needs.",
           {"intent": {"type": "string", "enum": intents}, "value": s,
            "window": {"type": "string", "enum": WINDOWS},
            "exclusions": {"type": "array", "items": {"type": "string", "enum": EXCLUSIONS}},
            "topic": {"type": "string", "enum": TOPICS},
            "why": {**s, "description": "one sentence: why this action fits the request"}}, ["intent", "why"]),
        fn("ask_user", "Ask one clarifying question.",
           {"question": s, "options": {"type": "array", "items": s, "minItems": 2, "maxItems": 4}}, ["question", "options"]),
    ]


class ToolAgent:
    def __init__(self, session, decider):
        self.s, self.llm = session, decider  # decider: the LLMDecider (model, URL, key handling)
        self.trace: list[dict] = []

    # ------------------------------------------------------------------ look-up tools (trusted records only)
    def _sup(self, ref: str) -> Optional[str]:
        led = self.s.led
        ref = (ref or "").strip()
        if ref in led.suppliers:
            return ref
        low = ref.lower()
        return next((sid for sid, sp in led.suppliers.items() if low and (low in sp.name.lower() or low == sid.lower())), None)

    def _bill(self, ref: str) -> Optional[str]:
        ref = (ref or "").strip()
        if ref in self.s.led.bills:
            return ref
        return self.s.alias().get(ref[-4:]) if ref else None

    def _card(self, bid: str) -> dict:
        from .. import mail
        b = self.s.led.bills[bid]
        return {"bill": bid, "short": bid[-4:], "supplier": b.supplier_id, "inv_no": mail.safe_id(b.read.inv_no, "(not shown)"),
                "amount_usd": round(b.amount_usd or b.read.total, 2), "status": b.status, "tier": b.tier,
                "due": b.read.due_date, "paid_on": b.paid_on}

    def find_bills(self, supplier: str = "", status: str = "open", due: str = "all") -> dict:
        led, today = self.s.led, date.fromisoformat(self.s.led.today)
        sid = self._sup(supplier) if supplier else None
        out = []
        for bid, b in led.bills.items():
            if bid.startswith("H") or (sid and b.supplier_id != sid):
                continue
            if status == "open" and b.status not in ("received", "held", "approved"):
                continue
            if status not in ("open", "any") and status != {"held": "held", "needs_approval": "held", "scheduled": "approved",
                                                              "paid": "paid", "rejected": "rejected"}[status]:
                continue
            d = date.fromisoformat(b.read.due_date) if b.read.due_date else None
            end = {"today": today, "this_week": today + timedelta(days=6 - today.weekday()), "next_week": today + timedelta(days=13 - today.weekday()),
                   "this_month": today.replace(day=28) + timedelta(days=4), "overdue": today - timedelta(days=1), "all": None}[due]
            if end is not None and (d is None or d > end):
                continue
            out.append(self._card(bid))
        return {"supplier": sid, "bills": out[:40], "count": len(out)}

    def bill_details(self, bill: str) -> dict:
        bid = self._bill(bill)
        if bid is None:
            return {"error": f"no bill {bill}"}
        b = self.s.led.bills[bid]
        return {**self._card(bid), "reasons": list(b.reasons or [])[:5], "hold_reason": b.hold_reason,
                "fx": b.fx, "erp_bound": b.erp_bound}

    def supplier_info(self, supplier: str) -> dict:
        sid = self._sup(supplier)
        if sid is None:
            return {"error": f"no supplier matching {supplier}", "known": list(self.s.request_state()["suppliers"])[:20]}
        sp = self.s.led.suppliers[sid]
        bills = [b for k, b in self.s.led.bills.items() if b.supplier_id == sid and not k.startswith("H")]
        mats = self.s.request_state()["suppliers"].get(sid, {}).get("materials", [])
        return {"supplier": sid, "name": sp.name, "materials": mats, "frozen": sp.frozen, "probation_left": sp.probation_left,
                "rail": sp.rail, "open_bills": sum(b.status in ("received", "held", "approved") for b in bills),
                "paid_total_usd": round(sum(b.amount_usd for b in bills if b.status == "paid"), 2)}

    def cash_and_limits(self) -> dict:
        out = {"cash_usd": self.s.led.cash_usd, "risk_setting": self.s.agent.gov.bundle_name}
        if self.s.chain:
            c = self.s.chain.state()
            out.update({k: c[k] for k in ("vault_balance_usd", "p_cap_usd", "p_day_usd", "p_nday", "p_supweek_usd", "agent_paused")})
        return out

    def market_price(self, material: str) -> dict:
        try:
            from .. import marketwatch
            cards = marketwatch.watch(self.s.led)
        except Exception:  # noqa: BLE001 - no market data is an answer too
            cards = []
        low = (material or "").lower()
        hit = next((c for c in cards if low and (low in str(c.get("material", "")).lower() or low in str(c.get("item", "")).lower())), None)
        return hit or {"error": f"no market series for {material}"}

    # ------------------------------------------------------------------ the loop
    def _call(self, messages: list, tools: list) -> dict:
        import httpx
        body = {"model": self.llm.model, "temperature": 0, "messages": messages, "tools": tools, "tool_choice": "auto"}
        url = f"{self.llm.base_url}/chat/completions"
        if getattr(self.llm, "rotate", False):
            from .. import keyring
            r = keyring.post(url, body, timeout=60)
        else:
            r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {self.llm.api_key}"}, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]

    def run(self, text: str, role: str, messages: Optional[list] = None) -> dict:
        """{"kind": "plan", "route": Route} | {"kind": "question", "question", "options", "messages"} |
        {"kind": "answer", "text"}; each with the trace of tools called."""
        router_role = "owner" if role == "owner" else "finance_manager"
        tools = _tools(router_role)
        if messages is None:
            messages = [{"role": "system", "content": SYSTEM.format(role=router_role.replace("_", " "), today=self.s.led.today)},
                        {"role": "user", "content": text}]
        state = self.s.request_state()
        for _ in range(MAX_ROUNDS):
            msg = self._call(messages, tools)
            calls = msg.get("tool_calls") or []
            if not calls:
                return {"kind": "answer", "text": (msg.get("content") or "").strip()[:1500], "trace": self.trace}
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                self.trace.append({"tool": name, "args": args})
                if name == "propose_action":
                    route, err = self._route(text, args, state, router_role)
                    if route is not None:
                        return {"kind": "plan", "route": route, "why": str(args.get("why", ""))[:300], "trace": self.trace}
                    result = {"error": err}
                elif name == "ask_user":
                    opts = [str(o)[:80] for o in (args.get("options") or [])][:4]
                    if len(opts) >= 2:
                        return {"kind": "question", "question": str(args.get("question", ""))[:200], "options": opts,
                                "messages": messages + [{"role": "tool", "tool_call_id": c["id"], "content": "asked"}],
                                "trace": self.trace}
                    result = {"error": "give 2-4 options"}
                elif name in ("find_bills", "bill_details", "supplier_info", "cash_and_limits", "market_price"):
                    try:
                        result = getattr(self, name)(**{k: v for k, v in args.items() if isinstance(v, str)})
                    except Exception as e:  # noqa: BLE001 - a bad argument is the model's to fix
                        result = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
                else:
                    result = {"error": f"no tool {name}"}
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, default=str)[:6000]})
        raise RuntimeError("the agent did not finish within the step limit")

    def _route(self, text: str, a: dict, state: dict, role: str):
        """Check a proposed action against the catalogue and the closed value lists; build the router's Route."""
        intent = a.get("intent")
        spec = CATALOGUE.get(intent or "")
        if spec is None or intent == "UNSUPPORTED":
            return None, f"unknown action {intent}"
        if role not in spec.roles:
            return None, f"only the owner can do {intent}"
        value = a.get("value")
        if spec.key_slot:
            opts = slot_options(spec.key_slot, state)
            if spec.key_slot == "bill" and value:
                value = (self._bill(value) or value)[-4:]
            elif spec.key_slot == "supplier" and value and value not in opts:
                value = self._sup(value) or value
            if value not in opts:
                if spec.required:
                    return None, f"value must be one of {opts[:30]}"
                value = "ALL"
        window = a.get("window") if a.get("window") in WINDOWS else "all"
        excl = [e for e in (a.get("exclusions") or []) if e in EXCLUSIONS]
        topic = a.get("topic") if a.get("topic") in TOPICS else "price"
        if spec.key_slot == "bundle" and value not in BUNDLES:
            return None, f"risk setting must be one of {BUNDLES}"
        return Route(text=text, intent_probs={intent: 1.0}, intent_set=[intent], slot=spec.key_slot,
                     slot_probs={value: 1.0} if value else {}, slot_set=[value] if value else [], window=window,
                     exclusions=excl, topic=topic, outcome="plan", intent=intent, value=value), None
