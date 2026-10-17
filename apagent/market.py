"""Public price series (World Bank Commodity Price Data, monthly, nominal US$)."""
from __future__ import annotations

import json
from functools import lru_cache

from .config import DATA_DIR

RAW = DATA_DIR / "raw" / "CMO-Historical-Data-Monthly.xlsx"
CACHE = DATA_DIR / "market" / "worldbank_monthly.json"
SERIES = {"Copper": "Copper", "Aluminum": "Aluminum", "Zinc": "Zinc", "Nickel": "Nickel", "Tin": "Tin"}
SOURCE = "World Bank Commodity Price Data (Pink Sheet), monthly, $/mt"


def build_cache() -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(RAW, read_only=True)
    rows = list(wb["Monthly Prices"].iter_rows(values_only=True))
    header = rows[4]
    cols = {name: i for i, h in enumerate(header) if h for name in SERIES if str(h).strip() == name}
    out: dict[str, dict[str, float]] = {name: {} for name in cols}
    for r in rows[6:]:
        if not r[0] or "M" not in str(r[0]):
            continue
        y, m = str(r[0]).split("M")
        key = f"{y}-{int(m):02d}"
        for name, i in cols.items():
            v = r[i]
            if isinstance(v, (int, float)):
                out[name][key] = float(v)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"source": SOURCE, "series": out}))
    return out


@lru_cache(maxsize=1)
def series() -> dict[str, dict[str, float]]:
    if CACHE.exists():
        return json.loads(CACHE.read_text())["series"]
    return build_cache()


def month_key(iso_date: str, lag_months: int = 0) -> str:
    y, m = int(iso_date[:4]), int(iso_date[5:7])
    m -= lag_months
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}-{m:02d}"


def index_value(name: str, iso_date: str, lag_months: int = 0) -> float:
    s = series()[name]
    key = month_key(iso_date, lag_months)
    if key in s:
        return s[key]
    earlier = [k for k in s if k <= key]
    if not earlier:
        raise KeyError(f"{name} has no value at or before {key}")
    return s[max(earlier)]
