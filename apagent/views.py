"""Read views for the desk (spec section 9): what each screen shows, computed from the ledger, the journal and
the chain. Nothing here changes state."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import date
from typing import Optional

from . import demo
from .audit import merkle_proof, verify_proof
from .domain import Bill

# UI status for a bill (spec section 4).
STAGES = ("received", "scheduled", "needs_approval", "on_hold", "paid", "rejected")


def stage(b: Bill) -> str:
    if b.status in ("paid", "partial"):
        return "paid"
    if b.status == "rejected":
        return "rejected"
    if b.status == "approved":
        return "scheduled" if b.tier == "T1" else "needs_approval"
    if b.status == "held":
        return "on_hold" if b.tier == "hold" else "needs_approval"
    return "received"


def paid_by(b: Bill) -> Optional[str]:
    if b.status not in ("paid", "partial"):
        return None
    return {"T1": "agent", "T2": "finance_manager", "history": "history"}.get(b.tier, b.tier)


def _in(d: Optional[str], frm: Optional[str], to: Optional[str]) -> bool:
    return bool(d) and (not frm or d >= frm) and (not to or d <= to)


# ------------------------------------------------------------------ payments register (E3)
def payments(s, frm: Optional[str] = None, to: Optional[str] = None, by: Optional[str] = None,
             supplier: Optional[str] = None) -> dict:
    """Every payment in the period: who paid it (agent, finance manager, or ERP history from before the agent),
    the rail and the transaction. Totals cover the whole period whatever the payer filter."""
    led = s.led
    rows = []
    for b in led.bills.values():
        who = paid_by(b)
        if who is None or not _in(b.paid_on, frm, to) or b.paid_on > led.today:
            continue
        if supplier and b.supplier_id != supplier:
            continue
        sup = led.suppliers.get(b.supplier_id)
        rows.append({"date": b.paid_on, "bill": b.bill_id, "inv_no": b.read.inv_no, "supplier_id": b.supplier_id,
                     "supplier": sup.name if sup else b.read.supplier_name, "amount": round(b.amount_usd, 2),
                     "by": who, "rail": sup.rail if sup else None, "tx_hash": b.tx_hash, "erp_ref": b.erp_ref,
                     "plan_id": b.plan_id, "group": b.group})
    totals = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for r in rows:
        totals[r["by"]]["amount"] += r["amount"]
        totals[r["by"]]["count"] += 1
        totals["all"]["amount"] += r["amount"]
        totals["all"]["count"] += 1
    for t in totals.values():
        t["amount"] = round(t["amount"], 2)
    shown = [r for r in rows if not by or by == "all" or r["by"] == by]
    shown.sort(key=lambda r: (r["date"], r["bill"]), reverse=True)
    return {"from": frm, "to": to, "today": led.today, "totals": dict(totals), "rows": shown}


# ------------------------------------------------------------------ verify a journal line (E4)
def journal(s, limit: int = 300, bill: Optional[str] = None, actor: Optional[str] = None,
            security: bool = False, frm: Optional[float] = None, to: Optional[float] = None) -> list[dict]:
    out = []
    for i, l in enumerate(s.agent.log.lines):
        if bill and l.bill_id != bill or actor and l.actor != actor or security and not l.security:
            continue
        if frm is not None and l.ts < frm or to is not None and l.ts > to:
            continue
        out.append({"index": i, **asdict(l), "anchored": anchor_for(s, i) is not None})
    return out[-limit:]


def anchor_for(s, index: int) -> Optional[dict]:
    for a in s.agent.__dict__.get("anchors", []):
        if index < a["lines"]:
            return a
    return None


def verify(s, index: int) -> dict:
    """Merkle proof that journal line `index` is part of a root stored on-chain."""
    lines = s.agent.log.lines
    if not 0 <= index < len(lines):
        raise KeyError(f"no journal line {index}")
    a = anchor_for(s, index)
    leaf = lines[index].leaf()
    if a is None:
        return {"index": index, "leaf": "0x" + leaf.hex(), "anchored": False,
                "message": "Not anchored yet. The journal is anchored at the end of each day."}
    leaves = [l.leaf() for l in lines[:a["lines"]]]
    proof = merkle_proof(leaves, index)
    root = bytes.fromhex(a["root"][2:])
    on_chain = None
    if s.chain:
        on_chain = s.chain.anchor.functions.roots(a["day"]).call()
    ok = verify_proof(leaf, proof, root) and (on_chain is None or on_chain == root)
    return {"index": index, "anchored": True, "ok": ok, "leaf": "0x" + leaf.hex(),
            "proof": ["0x" + p.hex() for p in proof], "root": a["root"],
            "root_on_chain": ("0x" + on_chain.hex()) if on_chain is not None else None,
            "anchor_tx": a["tx"], "anchor_date": a["date"], "lines_covered": a["lines"],
            "message": "This line is in the root stored on-chain." if ok else "The proof does not match the anchored root."}


# ------------------------------------------------------------------ disputes with timelines (V6)
CASE_LABEL = {"missed_credit": "Missed credit", "bank_change": "Bank details change", "injection": "Hidden instruction",
              "duplicate": "Duplicate", "fair_price": "Price above market"}


def disputes(s) -> list[dict]:
    """Open and closed cases, plus open price queries, each with a timeline from the journal."""
    led, ag = s.led, s.agent
    out = []
    for c in led.cases.values():
        bill_id = c.detail.get("bill")
        rec = led.receivables.get(bill_id) if bill_id else None
        events = [l for l in ag.log.lines
                  if (bill_id and l.bill_id == bill_id) or l.detail.get("case") == c.case_id
                  or (c.kind == "bank_change" and l.kind in ("freeze_payee", "unfreeze_payee") and l.detail.get("supplier") == c.supplier_id)]
        claim = _claim(s, bill_id) if bill_id and rec else None
        out.append({"id": c.case_id, "kind": c.kind, "label": CASE_LABEL.get(c.kind, c.kind), "status": c.status,
                    "supplier_id": c.supplier_id, "supplier": led.suppliers[c.supplier_id].name, "created": c.created,
                    "bill": bill_id, "detail": c.detail,
                    "receivable": asdict(rec) if rec else None, "claim": claim,
                    "emails": [e for e in ag._emails() if e.get("bill") == bill_id] if bill_id else
                    [e for e in ag._emails() if e["supplier"] == c.supplier_id and e["template"] == "bank_change_alert"],
                    "timeline": [{"ts": l.ts, "actor": l.actor, "kind": l.kind, "detail": l.detail, "tx_hash": l.tx_hash}
                                 for l in events]})
    for q in ag.queries.values():
        if q["status"] in ("sent", "needs_manager", "draft"):
            b = led.bills[q["bill"]]
            out.append({"id": q["id"], "kind": "query", "label": "Supplier query", "status": q["status"],
                        "supplier_id": b.supplier_id, "supplier": led.suppliers[b.supplier_id].name,
                        "created": b.received, "bill": b.bill_id, "detail": {"topic": q["topic"], "amount": q.get("amount")},
                        "receivable": None, "claim": None,
                        "emails": [e for e in ag._emails() if e.get("bill") == b.bill_id],
                        "timeline": [{"ts": l.ts, "actor": l.actor, "kind": l.kind, "detail": l.detail, "tx_hash": l.tx_hash}
                                     for l in ag.log.lines if l.bill_id == b.bill_id]})
    out.sort(key=lambda d: (d["status"] not in ("open", "sent", "needs_manager", "draft"), d["created"]), reverse=False)
    return out


CLAIM_STATUS = ["none", "locked", "released", "filed", "disputed", "resolved", "paid"]


def _claim(s, bill_id: str) -> Optional[dict]:
    if not s.chain:
        return None
    from .chain import b32
    from .config import units_to_usd
    l = s.chain.pool.functions.locks(b32(bill_id)).call()
    amount, r, locked_at, mode, status, loss, dispute_until, claim_paid, recovered = l[:9]
    return {"status": CLAIM_STATUS[status], "reserve_usd": units_to_usd(r), "loss_usd": units_to_usd(loss),
            "dispute_until": dispute_until, "paid_usd": units_to_usd(claim_paid), "recovered_usd": units_to_usd(recovered),
            "mode": {1: "self_reserve", 2: "bonded"}.get(mode)}


# ------------------------------------------------------------------ bank (underwriter) console (E7)
def bank(s) -> dict:
    """What the bank sees: the pool, what is locked against which payment, claims to review, premiums due."""
    led, ag = s.led, s.agent
    st = s.chain.state() if s.chain else {}
    b = ag.cal.bundle(ag.gov.bundle_name)
    locks, premiums = [], 0.0
    for bill in led.bills.values():
        if bill.bill_id.startswith("H") or bill.tier != "T1" or bill.status not in ("paid", "partial"):
            continue
        d = ag.decisions.get(bill.bill_id)
        premiums += d.premium if d else 0.0
        c = _claim(s, bill.bill_id)
        if c and c["status"] != "none":
            locks.append({"bill": bill.bill_id, "supplier": led.suppliers[bill.supplier_id].name, "amount": bill.amount_usd,
                          "paid_on": bill.paid_on, "premium": d.premium if d else 0.0, **c})
    return {"pool": {k: st.get(k) for k in ("pool_balance_usd", "pool_locked_usd", "pool_free_usd", "pool_owed_usd",
                                             "pool_paused", "mode", "r_usd", "p_day_usd", "p_nday", "p_cap_usd")},
            "setting": {"name": ag.gov.bundle_name, "beta": b.beta, "K_usd": b.K_usd, "max_exposure_usd": b.max_exposure_usd,
                        "t1_share": b.t1_share},
            "premiums_due_usd": round(premiums, 2), "locks": locks,
            "claims_to_review": [l for l in locks if l["status"] == "filed"],
            "pending_settings": ag._pending_bundle}


# ------------------------------------------------------------------ month-end close pack (E5)
def close_pack(s, month: Optional[str] = None) -> dict:
    """One month in numbers: what was paid and by whom, what was caught, recovered and anchored."""
    led, ag = s.led, s.agent
    month = month or led.today[:7]
    frm, to = f"{month}-01", f"{month}-31"
    pay = payments(s, frm, to)
    bills = [b for b in led.bills.values() if not b.bill_id.startswith("H") and _in(b.received, frm, to)]
    by_stage = defaultdict(int)
    for b in bills:
        by_stage[stage(b)] += 1
    held_back = sum((b.fair_price or {}).get("overcharge", 0.0) for b in bills)
    dups = sum(b.read.total for b in bills if b.status == "rejected")
    recovered = sum(o.get("amount", 0.0) for b in bills for o in b.offsets)
    cases = [c for c in led.cases.values() if _in(c.created, frm, to)]
    anchors = [a for a in ag.__dict__.get("anchors", []) if _in(a["date"], frm, to)]
    emails = [e for e in ag._emails() if _in(e.get("created"), frm, to)]
    return {"month": month, "company": led.company, "payments": pay["totals"], "bills": dict(by_stage),
            "bills_received": len(bills), "overcharges_held_usd": round(held_back, 2),
            "duplicates_rejected_usd": round(dups, 2), "recovered_usd": round(recovered, 2),
            "cases": {"opened": len(cases), "open": sum(c.status == "open" for c in cases)},
            "security_events": len([l for l in ag.log.lines if l.security]),
            "emails_sent": sum(e["status"] == "sent" for e in emails),
            "anchors": anchors, "consistency": s.consistency()}


# ------------------------------------------------------------------ pay-date schedule (P3)
def schedule(s) -> list[dict]:
    """Bills cleared or waiting, with the date the planner would pay them (discounts first, cash floor kept)."""
    led, ag = s.led, s.agent
    open_bills = [b for b in led.bills.values() if not b.bill_id.startswith("H") and b.status in ("approved", "held")
                  and b.supplier_id]
    rows = ag.plan_dates(open_bills) if open_bills else []
    out = []
    for r in rows:
        b = led.bills[r["bill"]]
        out.append({**r, "supplier": led.suppliers[b.supplier_id].name, "inv_no": b.read.inv_no, "due": b.read.due_date,
                    "terms": b.read.terms, "stage": stage(b)})
    return sorted(out, key=lambda r: r["pay_on"])


def supplier_rows(s) -> list[dict]:
    """The registry with on-chain payee state, for the Suppliers screen."""
    led = s.led
    out = []
    for sid, sp in led.suppliers.items():
        if sid not in demo.DEMO_SUPPLIERS:
            continue
        p = s.chain.payee(sid) if s.chain else {}
        paid = [b for b in led.bills.values() if b.supplier_id == sid and b.status == "paid"]
        out.append({"id": sid, "name": sp.name, "contact": sp.contact, "domain": sp.domain, "rail": sp.rail,
                    "frozen": p.get("frozen", sp.frozen), "active": p.get("active"), "active_at": p.get("active_at"),
                    "probation_left": sp.probation_left, "confirmed_errors": sp.confirmed_errors,
                    "signing_key": getattr(sp, "signing_key", ""),
                    "paid_ytd": round(sum(b.amount_usd for b in paid if (b.paid_on or "")[:4] == led.today[:4]), 2),
                    "open_cases": [c.case_id for c in led.cases.values() if c.supplier_id == sid and c.status == "open"]})
    return out


def first_of_month(d: str) -> str:
    return date.fromisoformat(d).replace(day=1).isoformat()
