"""Currencies (spec C5). Orders and the vault are in USD; a bill in HKD or CNY is converted at intake with a dated
reference rate, and the original currency and amounts stay on the bill for display.

Rates are units of the currency per USD. The defaults are reference rates for the demo: HKD 7.80 is the centre
of the Linked Exchange Rate band (7.75-7.85); the CNY rate is illustrative. In production, load the official
fixings (HKMA, CFETS) into data/fx_rates.json as {"YYYY-MM": {"HKD": 7.8, "CNY": 7.1}} or set FX_<CUR>=rate.
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Optional

from .config import DATA_DIR
from .domain import InvLine, Read

DEFAULT = {"USD": 1.0, "HKD": 7.80, "CNY": 7.20}
RATES_FILE = DATA_DIR / "fx_rates.json"


def rate(currency: str, on: str) -> Optional[float]:
    """Units of `currency` per USD on date `on` (YYYY-MM-DD), or None if the currency is not supported."""
    cur = (currency or "USD").upper()
    if os.environ.get(f"FX_{cur}"):
        return float(os.environ[f"FX_{cur}"])
    if RATES_FILE.exists():
        table = json.loads(RATES_FILE.read_text())
        month = table.get(on[:7]) or {}
        if cur in month:
            return float(month[cur])
    return DEFAULT.get(cur)


def to_usd(read: Read, fx: float) -> Read:
    """The same bill in USD. Line prices keep four decimals; the total is recomputed from the converted lines so
    the arithmetic check sees the same bill the supplier sent."""
    lines = [InvLine(l.item, l.desc, l.unit, l.qty, round(l.price / fx, 4)) for l in read.lines]
    credit = round(read.credit / fx, 2)
    total = round(sum(l.amount for l in lines) - credit, 2)
    return replace(read, lines=lines, credit=credit, total=total, currency="USD")
