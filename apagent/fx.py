"""Currencies (spec C5). Orders and the vault are in USD; a bill in HKD or CNY is converted at intake with the rate
of the invoice date, and the original currency, amount, rate and its source stay on the bill.

Where the rate comes from, first match wins:
  FX_<CUR>=rate              a fixed rate set by the company (for example its bank's contract rate)
  data/fx_rates.json         rates already fetched or loaded: {"YYYY-MM-DD": {"HKD": 7.82, ...}} (month keys
                             "YYYY-MM" also accepted, for official fixings loaded by hand)
  the ECB reference rates    fetched for that date from the Frankfurter service (api.frankfurter.dev, free, the
                             European Central Bank's daily rates; the last published day before a weekend or holiday)
  a fixed reference rate     only if the service cannot be reached; the bill says so
FX_SOURCE=off skips the service (offline runs and tests).
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from typing import Optional

from .config import DATA_DIR
from .domain import InvLine, Read

# Fallback only: HKD 7.80 is the centre of the Linked Exchange Rate band (7.75-7.85); the CNY figure is indicative.
DEFAULT = {"USD": 1.0, "HKD": 7.80, "CNY": 7.20}
RATES_FILE = DATA_DIR / "fx_rates.json"
SERVICE = os.environ.get("FX_SERVICE_URL", "https://api.frankfurter.dev/v1")
SOURCE_ECB = "ECB reference rate"
SOURCE_FALLBACK = "fixed reference rate (rate service unreachable)"
_lock = threading.Lock()


def _table() -> dict:
    try:
        return json.loads(RATES_FILE.read_text()) if RATES_FILE.exists() else {}
    except (OSError, ValueError):
        return {}


def _fetch(cur: str, on: str) -> Optional[tuple[float, str]]:
    import httpx

    try:
        r = httpx.get(f"{SERVICE}/{on}", params={"base": "USD", "symbols": cur}, timeout=5, follow_redirects=True)
        r.raise_for_status()
        d = r.json()
        return float(d["rates"][cur]), d.get("date", on)
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None


def rate_info(currency: str, on: str) -> Optional[dict]:
    """{"rate": units of `currency` per USD on `on` (YYYY-MM-DD), "source", "date": the rate's own date}, or None if
    the currency is not supported."""
    cur = (currency or "USD").upper()
    if cur == "USD":
        return {"rate": 1.0, "source": "USD", "date": on}
    if os.environ.get(f"FX_{cur}"):
        return {"rate": float(os.environ[f"FX_{cur}"]), "source": f"company rate (FX_{cur})", "date": on}
    table = _table()
    for key in (on, on[:7]):
        if cur in (table.get(key) or {}):
            v = table[key][cur]
            if isinstance(v, dict):
                return {"rate": float(v["rate"]), "source": v.get("source", SOURCE_ECB), "date": v.get("date", key)}
            return {"rate": float(v), "source": "loaded rate table", "date": key}
    if os.environ.get("FX_SOURCE", "on").lower() != "off":
        got = _fetch(cur, on)
        if got:
            with _lock:  # keep it, so each date is fetched once
                t = _table()
                t.setdefault(on, {})[cur] = {"rate": got[0], "source": SOURCE_ECB, "date": got[1]}
                RATES_FILE.parent.mkdir(parents=True, exist_ok=True)
                RATES_FILE.write_text(json.dumps(t, indent=1, sort_keys=True))
            return {"rate": got[0], "source": SOURCE_ECB, "date": got[1]}
    if cur in DEFAULT:
        return {"rate": DEFAULT[cur], "source": SOURCE_FALLBACK, "date": on}
    return None


def rate(currency: str, on: str) -> Optional[float]:
    """Units of `currency` per USD on date `on` (YYYY-MM-DD), or None if the currency is not supported."""
    info = rate_info(currency, on)
    return info["rate"] if info else None


def to_usd(read: Read, fx: float) -> Read:
    """The same bill in USD. Line prices keep four decimals; the total is recomputed from the converted lines so
    the arithmetic check sees the same bill the supplier sent."""
    lines = [InvLine(l.item, l.desc, l.unit, l.qty, round(l.price / fx, 4)) for l in read.lines]
    credit = round(read.credit / fx, 2)
    total = round(sum(l.amount for l in lines) - credit, 2)
    return replace(read, lines=lines, credit=credit, total=total, currency="USD")
