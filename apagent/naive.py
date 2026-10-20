"""The no-rules baseline for the RED experiment (apagent/experiments.py) and task 8.

It plans what a tool-calling LLM agent with no rules tends to do with a poisoned invoice: it treats text on the
document as instructions. Written out deterministically so the experiment is reproducible: if the text names a
wallet and asks for the balance, the plan sends the balance there. It is a comparison column, not part of the
product; nothing here sends money.
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

