"""Replay simulated bills through the real checker and injection flag to build calibration records.

For each bill we record the score features, whether the checker passed, the payable amount and the
loss if the bill were paid alone: loss = max(0, amount - true amount owed). l = loss / V is in [0, 1].
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from .. import checker, injection
from ..config import SETTINGS, Settings
from ..domain import Bill
from ..sim import SimWorld
from .features import featurize, vector


@dataclass
class Record:
    idx: int
    date: str
    supplier_id: str
    group: str
    value: float  # V: the payable amount (computed:erp_bounded)
    loss: float  # dollars lost if paid alone
    passed: bool  # checker passed
    injection_p: float
    codes: list
    flags: list
    x: np.ndarray
    features: dict

    @property
    def ell(self) -> float:
        return self.loss / self.value if self.value > 0 else 0.0

    def eligible(self, cfg: Settings = SETTINGS) -> bool:
        """Could go T1 at all: checker passed, under P-CAP, not flagged."""
        return self.passed and 0 < self.value <= cfg.p_cap_usd and self.injection_p < cfg.injection_threshold


def replay(world: SimWorld, cfg: Settings = SETTINGS) -> list[Record]:
    led = copy.deepcopy(world.ledger)
    out: list[Record] = []
    for ev in world.events:
        bill = Bill(bill_id=f"B{ev.idx:05d}", received=ev.invoice.date, source="photo" if ev.invoice.photo else "pdf",
                    read=copy.deepcopy(ev.read))
        res = checker.check(led, bill, cfg)
        inj = injection.score(ev.read.raw_text)["p"]
        f = featurize(led, bill, res, ev.invoice.photo)
        amount = res.amount.value
        loss = round(max(0.0, amount - ev.true_owed), 2)
        out.append(Record(ev.idx, ev.invoice.date, ev.invoice.supplier_id, res.group, amount, loss, res.passed,
                          inj, res.codes, ev.flags, vector(f), f))
        # A person resolves whatever the checker held; the bill then counts as billed.
        bill.supplier_id = res.supplier.id if res.supplier else None
        if "duplicate" in res.codes or res.supplier is None:
            bill.status = "rejected"
        else:
            bill.status = "paid"
            bill.amount_usd = amount
            res.supplier.bills_paid += 1
        led.bills[bill.bill_id] = bill
    return out
