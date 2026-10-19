"""Mainland e-invoice (fapiao) check (spec C6).

A bill from a mainland supplier may quote its fapiao number. The agent asks a verification service whether that
fapiao exists, is still valid (not void or reversed), was issued by this supplier's tax ID, and matches the billed
total. FAPIAO_REQUIRED=on also holds mainland bills that quote no fapiao.

    FAPIAO_API_URL   a verification provider: POST {"number", "date", "total"} -> {"status", "seller_tax_id", "total"}
    otherwise        the demo's simulated registry, data/demo/fapiao_registry.json (clearly not the tax bureau)
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .config import DATA_DIR

REGISTRY = DATA_DIR / "demo" / "fapiao_registry.json"


def required() -> bool:
    return os.environ.get("FAPIAO_REQUIRED", "off").lower() in ("on", "1", "true", "yes")


def lookup(number: str, on: str, total: float) -> Optional[dict]:
    url = os.environ.get("FAPIAO_API_URL", "").strip()
    if url:
        import httpx
        r = httpx.post(url, json={"number": number, "date": on, "total": total}, timeout=20)
        return r.json() if r.status_code == 200 else None
    if not REGISTRY.exists():
        return None
    return json.loads(REGISTRY.read_text()).get(number)


def verify(number: str, on: str, total: float, seller_tax_id: str) -> Optional[str]:
    """The problem with this fapiao, or None if it checks out."""
    try:
        f = lookup(number, on, total)
    except Exception as e:  # noqa: BLE001 - a service outage holds the bill rather than letting it through
        return f"fapiao service unavailable ({type(e).__name__})"
    if f is None:
        return f"fapiao {number} was not found"
    if f.get("status") != "normal":
        return f"fapiao {number} is {f.get('status')}"
    if f.get("seller_tax_id") != seller_tax_id:
        return f"fapiao {number} was issued by another seller"
    if abs(float(f.get("total", 0)) - total) > 0.01:
        return f"fapiao {number} is for {float(f['total']):,.2f}, the bill says {total:,.2f}"
    return None
