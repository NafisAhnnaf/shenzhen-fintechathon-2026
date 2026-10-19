"""Monthly budgets per cost centre (spec D5).

Each material belongs to a cost centre. The owner sets a monthly budget per centre; a bill that would take a centre
over its budget cannot be paid by the agent alone and goes to the finance manager with the numbers. Budgets only
add scrutiny: they never let the agent pay something it otherwise could not.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from .domain import Bill, Ledger

CENTRE = {"CU-ROD": "Raw metals", "AL-SHEET": "Raw metals", "ZN-ALLOY": "Raw metals", "NI-ANODE": "Raw metals",
          "SN-SOLDER": "Raw metals", "ABS-RESIN": "Plastics", "CARTON": "Packaging", "FASTENER": "Consumables",
          "LUBE": "Consumables", "PCB": "Electronics"}


def centre_of(item: str) -> str:
    return CENTRE.get(item, "General")


def split(bill: Bill, amount: Optional[float] = None) -> dict[str, float]:
    """A bill's amount shared across cost centres in proportion to its lines."""
    gross = sum(l.amount for l in bill.read.lines) or 1.0
    amt = bill.amount_usd if amount is None else amount
    out: dict[str, float] = defaultdict(float)
    for l in bill.read.lines:
        out[centre_of(l.item)] += amt * l.amount / gross
    return dict(out)


def spent(led: Ledger, month: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for b in led.bills.values():
        if b.status in ("paid", "partial") and (b.paid_on or "")[:7] == month:
            for c, v in split(b).items():
                out[c] += v
    return {c: round(v, 2) for c, v in out.items()}


def check(led: Ledger, budgets: dict[str, float], bill: Bill, amount: float) -> Optional[str]:
    """The reason this bill would break a budget, or None."""
    if not budgets:
        return None
    month = led.today[:7]
    used = spent(led, month)
    for c, v in split(bill, amount).items():
        cap = budgets.get(c)
        if cap is not None and used.get(c, 0.0) + v > cap + 1e-6:
            return (f"{c} budget for {month}: ${used.get(c, 0.0):,.2f} of ${cap:,.2f} used; this bill adds "
                    f"${v:,.2f}")
    return None


def overview(led: Ledger, budgets: dict[str, float], month: Optional[str] = None) -> list[dict]:
    month = month or led.today[:7]
    used = spent(led, month)
    centres = sorted(set(CENTRE.values()) | set(budgets) | set(used))
    return [{"centre": c, "budget": budgets.get(c), "spent": used.get(c, 0.0),
             "left": round(budgets[c] - used.get(c, 0.0), 2) if c in budgets else None} for c in centres]
