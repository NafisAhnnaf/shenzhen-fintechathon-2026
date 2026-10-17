"""Score features. Typed facts only: confidences, check margins, supplier record, novelty, value."""
from __future__ import annotations

import math
from datetime import date

import numpy as np

from ..checker import CheckResult
from ..domain import Bill, Ledger

FEATURES = [
    "low_conf",  # 1 - lowest field confidence
    "credit_doubt",  # 1 - confidence on the credit field
    "price_margin",  # 1 - margin to the price tolerance (0 = far inside, 1 = at the edge)
    "qty_margin",  # 1 - margin on received quantity
    "fair_excess",  # largest fair-price excess, if any
    "error_rate",  # supplier's confirmed errors per bill
    "new_item",  # item not bought from this supplier before
    "short_tenure",  # 1 / log(tenure in days)
    "photo",  # document came in as a phone photo
    "log_value",  # log10 of the amount
]


def featurize(led: Ledger, bill: Bill, res: CheckResult, photo: bool) -> dict[str, float]:
    r = bill.read
    sup = res.supplier
    conf = r.confidence
    m = res.margins
    new_item = 0.0
    tenure = 1.0
    err = 0.0
    if sup is not None:
        new_item = float(any(led.last_price(sup.id, l.item, before=r.date) is None for l in r.lines))
        tenure_days = max(2.0, (date.fromisoformat(r.date) - date.fromisoformat(sup.since)).days)
        tenure = 1.0 / math.log(tenure_days)
        err = sup.confirmed_errors / (sup.bills_paid + 1)
    return {
        "low_conf": 1.0 - r.min_confidence,
        "credit_doubt": 1.0 - conf.get("credit", 1.0),
        "price_margin": 1.0 - max(0.0, min(1.0, m.get("price", 1.0))),
        "qty_margin": 1.0 - max(0.0, min(1.0, m.get("qty", 1.0))),
        "fair_excess": max([max(0.0, f.excess) for f in res.fair] or [0.0]),
        "error_rate": err,
        "new_item": new_item,
        "short_tenure": tenure,
        "photo": float(photo),
        "log_value": math.log10(max(1.0, res.amount.value if res.amount else r.total)),
    }


def vector(f: dict[str, float]) -> np.ndarray:
    return np.array([f[k] for k in FEATURES], dtype=float)
