"""Plan templates (plan 3.6). Code fills a fixed template for the intent; no model writes plans.

Preview lists every step. Nothing with an external effect runs before the user taps Run (S9).
Each step re-checks state and policies when it runs; if anything changed since the preview, the step stops.
Cancel stops the remaining steps. Every step writes a log line with the plan ID.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Optional

from .. import checker
from ..agent import Agent
from ..domain import Bill
from .router import Route



@dataclass
class Step:
    n: int
    kind: str  # pay, hold, release, query, probation, settings, pause, resume, answer
    bill: Optional[str] = None
    supplier: Optional[str] = None
    amount: Optional[float] = None
    tier: Optional[str] = None
    reason: str = ""
    status: str = "planned"  # planned, done, stopped, skipped, needs_signature, failed
    result: dict = field(default_factory=dict)
    effect: bool = True


@dataclass
class Plan:
    plan_id: str
    intent: str
    value: Optional[str]
    summary: str
    steps: list[Step]
    totals: dict = field(default_factory=dict)
    status: str = "preview"  # preview, running, done, cancelled
    answer: Optional[dict] = None
    snapshot: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ selection helpers
def _in_window(b: Bill, window: str, today: str) -> bool:
    t = date.fromisoformat(today)
    due = date.fromisoformat(b.read.due_date)
    if window == "today":
        return due <= t
    if window == "this_week":
        return due <= t + timedelta(days=6 - t.weekday())
    if window == "next_week":
        return due <= t + timedelta(days=13 - t.weekday())
    if window == "this_month":
        return due.year == t.year and due.month == t.month or due <= t
    if window == "overdue":
        return due < t
    return True


def select_bills(agent: Agent, value: Optional[str], window: str = "all", statuses=("received", "held", "approved")) -> list[Bill]:
    led = agent.led
    # Bills that arrived but were not checked yet: check and decide now (T0, nothing is paid).
    for b in list(led.bills.values()):
        if b.status == "received" and b.supplier_id is None and not b.bill_id.startswith("H"):
            agent.process(b.bill_id, auto_pay=False)
    out = []
    for b in led.bills.values():
        if b.status not in statuses or not b.supplier_id:
            continue
        if value and value != "ALL":
            if value.startswith("MAT:"):
                if not any(l.item == value[4:] for l in b.read.lines):
                    continue
            elif b.supplier_id != value:
                continue
        if not _in_window(b, window, led.today):
            continue
        out.append(b)
    return sorted(out, key=lambda b: (b.read.due_date, b.bill_id))


def _excluded(agent: Agent, b: Bill, exclusions: list[str]) -> Optional[str]:
    sup = agent.led.suppliers[b.supplier_id]
    if "disputed" in exclusions and (b.disputed or b.fair_price):
        return "disputed"
    if "flagged" in exclusions and (b.injection_p >= agent.cfg.injection_threshold or b.fair_price):
        return "flagged"
    if "probation" in exclusions and sup.probation_left > 0:
        return "on probation"
    if "above_cap" in exclusions and b.amount_usd > agent.cfg.p_cap_usd:
        return "above cap"
    return None


def _label(agent: Agent, value: Optional[str]) -> str:
    if value in (None, "ALL"):
        return "all suppliers"
    if value.startswith("MAT:"):
        return agent.led.materials[value[4:]].name.lower() + " bills"
    if value in agent.led.suppliers:
        return agent.led.suppliers[value].name
    return value


# ------------------------------------------------------------------ build
def build(agent: Agent, route: Route, bill_alias: Optional[dict] = None) -> Plan:
    """bill_alias maps short bill numbers (as users type them) to bill IDs."""
    intent, value = route.intent, route.value
    if value and bill_alias and value in bill_alias:
        value = bill_alias[value]
    agent.n_plans += 1
    pid = f"P-{agent.n_plans:04d}"
    steps: list[Step] = []
    label = _label(agent, value)
    plan = Plan(pid, intent, value, "", steps)

    if intent == "PAY_SET":
        bills = select_bills(agent, value, route.window)
        total_t1 = total_t2 = 0.0
        n = 0
        for b in bills:
            ex = _excluded(agent, b, route.exclusions)
            if b.tier is None or b.status == "received":
                agent.process(b.bill_id, auto_pay=False, plan_id=pid)  # check and decide, no payment yet
            if ex:
                steps.append(Step(len(steps) + 1, "skip", b.bill_id, b.supplier_id, b.amount_usd, b.tier, f"excluded: {ex}", "skipped", effect=False))
                continue
            amount = b.resolution["amount"] if b.tier == "T2" and b.resolution else b.amount_usd
            tier = b.tier if b.tier in ("T1", "T2") else b.tier
            if tier in ("reject", "hold"):
                steps.append(Step(len(steps) + 1, "skip", b.bill_id, b.supplier_id, b.amount_usd, tier, "; ".join(b.reasons), "skipped", effect=False))
                continue
            steps.append(Step(len(steps) + 1, "pay", b.bill_id, b.supplier_id, amount, tier,
                              "; ".join(b.reasons[:2]) if tier == "T2" else "routine, inside all caps"))
            n += 1
            if tier == "T1":
                total_t1 += amount
            else:
                total_t2 += amount
        plan.totals = {"t1": round(total_t1, 2), "t2_needs_signature": round(total_t2, 2), "count": n,
                       "cash_after": round(agent.led.cash_usd - total_t1 - total_t2, 2), "cash_floor": agent.cfg.cash_floor_usd}
        n_t1 = sum(1 for s in steps if s.kind == "pay" and s.tier == "T1")
        parts = []
        if n_t1:
            parts.append(f"{n_t1} {'bill' if n_t1 == 1 else 'bills'} for ${total_t1:,.2f} on its own")
        if n - n_t1:
            parts.append(f"{n - n_t1} {'bill' if n - n_t1 == 1 else 'bills'} for ${total_t2:,.2f} after the finance manager signs")
        plan.summary = (f"Pay {label}: " + " and ".join(parts) + ".") if parts else f"Nothing to pay for {label}."
    elif intent == "HOLD_SET":
        for b in select_bills(agent, value, "all"):
            steps.append(Step(len(steps) + 1, "hold", b.bill_id, b.supplier_id, b.amount_usd, "P", "held on request"))
        plan.summary = f"Hold {len(steps)} open bill(s) for {label}."
    elif intent == "RELEASE":
        for b in select_bills(agent, value, "all", statuses=("held",)):
            steps.append(Step(len(steps) + 1, "release", b.bill_id, b.supplier_id, b.amount_usd, None,
                              "re-check, then normal tiers (a fair-price hold always goes to T2)"))
        plan.summary = f"Release {len(steps)} held bill(s) for {label} and re-check each."
    elif intent == "QUERY_SUPPLIER":
        b = agent.led.bills[value]
        steps.append(Step(1, "query", b.bill_id, b.supplier_id, None, "T2", f"templated query about the {route.topic}"))
        plan.summary = f"Draft a query to {agent.led.suppliers[b.supplier_id].contact} about the {route.topic} on {b.read.inv_no}; send with one tap."
    elif intent == "TIGHTEN":
        steps.append(Step(1, "probation", None, value, None, "P", f"next {agent.cfg.probation_bills} bills go to a person"))
        plan.summary = f"Put {label} on probation: the next {agent.cfg.probation_bills} bills go to a person."
    elif intent == "SET_DIAL":
        prop = agent.propose_bundle(value)
        steps.append(Step(1, "settings", None, None, None, "T3", f"bundle '{value}'", "needs_signature", {"proposal": prop}))
        plan.summary = (f"Switch to '{value}': loss budget {prop['beta']:.1%}, about {prop['t1_share']:.0%} paid alone, "
                        f"daily cap ${prop['p_day_usd']:,.0f} / {prop['p_nday']} payments, reserve K ${prop['K_usd']:,.0f} "
                        f"(r ${prop['r_usd']:,.0f} per payment). The owner signs.")
    elif intent == "PAUSE":
        steps.append(Step(1, "pause", reason="all bills go to a person until the owner resumes", tier="P"))
        plan.summary = "Pause the agent on-chain. Only the owner can resume."
    elif intent == "RESUME":
        steps.append(Step(1, "resume", reason="owner signs the unpause transaction", tier="T3", status="needs_signature"))
        plan.summary = "Resume the agent (owner signature)."
    elif intent in ("ASK_STATUS", "ASK_WHY", "WHAT_IF"):
        plan.answer = answer(agent, route, value)
        plan.summary = plan.answer["text"]
        plan.status = "done"
    return plan


# ------------------------------------------------------------------ T0 answers
def answer(agent: Agent, route: Route, value: Optional[str]) -> dict:
    led = agent.led
    if route.intent == "ASK_WHY":
        b = led.bills[value]
        card = agent.bill_card(value)
        why = card["reasons"] or ["It was paid alone: checks passed and the risk score was under the cut-off."]
        return {"text": f"Bill {value} ({b.read.inv_no}, {card['supplier']}): {b.status}. " + " ".join(why),
                "card": card}
    bills = select_bills(agent, value, route.window)
    total = round(sum(b.amount_usd or b.read.total for b in bills), 2)
    if route.intent == "ASK_STATUS":
        return {"text": f"Open with {_label(agent, value)} ({route.window.replace('_', ' ')}): {len(bills)} bill(s), "
                        f"${total:,.2f} (computed from ERP-bounded amounts).",
                "bills": [agent.bill_card(b.bill_id) for b in bills], "total": total}
    # WHAT_IF: the payment planner as a simulation
    sched = agent.plan_dates(bills, led.cash_usd)
    after = round(led.cash_usd - total, 2)
    return {"text": f"Paying {len(bills)} bill(s) for {_label(agent, value)} now (${total:,.2f}) leaves cash at ${after:,.2f} "
                    f"(floor ${agent.cfg.cash_floor_usd:,.0f}).",
            "cash_before": led.cash_usd, "cash_after": after, "below_floor": after < agent.cfg.cash_floor_usd, "schedule": sched}


# ------------------------------------------------------------------ run
def run(agent: Agent, plan: Plan, cancel_after: Optional[int] = None, actor: str = "owner") -> Plan:
    """Run the steps in order after the user tapped Run. cancel_after simulates Cancel after k steps."""
    if plan.status not in ("preview",):
        return plan
    plan.status = "running"
    agent.log.add(actor, "plan_run", {"intent": plan.intent, "steps": len(plan.steps)}, plan_id=plan.plan_id)
    done = 0
    for st in plan.steps:
        if st.status in ("skipped",):
            continue
        if cancel_after is not None and done >= cancel_after:
            st.status = "stopped"
            continue
        _run_step(agent, plan, st)
        if st.status == "done":
            done += 1
    if cancel_after is not None and any(s.status == "stopped" for s in plan.steps):
        plan.status = "cancelled"
        agent.log.add(actor, "plan_cancel", {"done": done}, plan_id=plan.plan_id)
    else:
        plan.status = "done"
    return plan


def step_next(agent: Agent, plan: Plan, actor: str = "owner") -> Optional[Step]:
    """Run one step (the UI calls this repeatedly so Cancel can stop between steps)."""
    if plan.status == "preview":
        plan.status = "running"
        agent.log.add(actor, "plan_run", {"intent": plan.intent, "steps": len(plan.steps)}, plan_id=plan.plan_id)
    if plan.status != "running":
        return None
    for st in plan.steps:
        if st.status == "planned":
            _run_step(agent, plan, st)
            return st
    plan.status = "done"
    return None


def cancel(agent: Agent, plan: Plan, actor: str = "owner") -> Plan:
    """Stop the remaining steps. Payments already sent stay sent."""
    n = 0
    for st in plan.steps:
        if st.status == "planned":
            st.status = "stopped"
            n += 1
    plan.status = "cancelled"
    agent.log.add(actor, "plan_cancel", {"stopped": n}, plan_id=plan.plan_id)
    return plan


def _run_step(agent: Agent, plan: Plan, st: Step) -> None:
    pid = plan.plan_id
    led = agent.led
    if st.kind == "pay":
        b = led.bills[st.bill]
        # Re-check: if anything changed since the preview, stop this step and ask.
        res = checker.check(led, b, agent.cfg)
        sup = led.suppliers[b.supplier_id]
        changed = (b.status not in ("held", "approved", "received") or sup.frozen
                   or abs(res.amount.value - b.amount_usd) > 0.01 and st.tier == "T1")
        if changed:
            st.status = "stopped"
            st.result = {"reason": "state changed since the preview; please review"}
            agent.log.add("agent", "step_stopped", st.result, plan_id=pid, bill_id=st.bill)
            return
        if st.tier == "T1":
            r = agent.pay_t1(st.bill, plan_id=pid, from_request=True, confirmed=True)
            st.result = r
            st.status = "done" if r.get("tier") == "T1" else "needs_signature"
            if st.status == "needs_signature":
                st.tier = "T2"
        else:
            st.status = "needs_signature"
            st.result = {"card": agent.bill_card(st.bill)}
    elif st.kind == "hold":
        st.result = agent.hold(st.bill, "held on request", plan_id=pid)
        st.status = "done"
    elif st.kind == "release":
        b = led.bills[st.bill]
        was_fair = b.fair_price is not None
        b.status = "received"
        b.hold_reason = None
        r = agent.process(st.bill, auto_pay=not was_fair, plan_id=pid)
        st.result = r
        st.tier = r.get("tier")
        st.status = "done" if r.get("tier") == "T1" else "needs_signature"
    elif st.kind == "query":
        q = agent.draft_query(st.bill, "price")
        st.result = {"draft": q}
        st.status = "needs_signature"  # one tap to send
    elif st.kind == "probation":
        st.result = agent.probation(st.supplier, reason="owner request")
        st.status = "done"
    elif st.kind == "pause":
        st.result = agent.pause_self("Owner request")
        st.status = "done"
    elif st.kind in ("settings", "resume"):
        st.status = "needs_signature"
    agent.log.add("agent", f"step_{st.kind}", {"n": st.n, "status": st.status}, plan_id=pid, bill_id=st.bill,
                  tx_hash=(st.result.get("tx") or {}).get("tx_hash") if isinstance(st.result.get("tx"), dict) else None)
