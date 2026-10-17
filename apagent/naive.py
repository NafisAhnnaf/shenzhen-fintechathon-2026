"""A naive AI wallet agent for the side-by-side demo (task 8) and the RED baseline.

It does what a tool-calling LLM agent with no rules tends to do with a poisoned invoice: it treats text on
the document as instructions. Here that behaviour is written out deterministically so the demo is
reproducible: if the text names a wallet and asks for the balance, it sends the balance there.
"""
from __future__ import annotations

import re
from typing import Optional

from . import injection


def plan_from_text(text: str, balance_usd: float, invoice_total: float) -> Optional[dict]:
    views = injection.decoded_views(text)
    joined = " ".join(views)
    m = re.search(r"0x[0-9a-fA-F]{40}", joined)
    if not m:
        return {"to": "registered", "amount": invoice_total, "why": "pay the invoice"}
    wants_all = re.search(r"\b(full|entire|all|whole|remaining)\b.{0,15}\b(balance|funds)\b", joined, re.I)
    return {"to": m.group(0), "amount": balance_usd if wants_all else invoice_total,
            "why": "the document said to pay this address"}


def run(chain, text: str, invoice_total: float) -> dict:
    bal = chain.state()["naive_balance_usd"]
    p = plan_from_text(text, bal, invoice_total)
    if p["to"] == "registered":
        return {"action": "none", "plan": p}
    tx = chain.naive_send(p["to"], p["amount"], "agent followed invoice instructions")
    return {"action": "sent", "plan": p, "tx_hash": tx.tx_hash, "ok": tx.ok,
            "balance_after": chain.state()["naive_balance_usd"]}
