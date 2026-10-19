"""Market watch (plan 9.3, spec C10): a price range for next month, an alert when a large move has become more
likely, and a buy-ahead comparison. It suggests and drafts; it never buys.

Range. Direction is hard to forecast for metals, so the centre is the no-change forecast and the work goes into the
width. Adaptive conformal inference (Gibbs & Candes, NeurIPS 2021) sets the width from past absolute log-returns and
adjusts its own miscoverage level after every month, so long-run coverage stays near the target even when a series
changes behaviour (split conformal assumes exchangeability, which a price series breaks).

Alert. Each signal uses the series' own history, so there is nothing to tune by hand:
  1. volatility of the last 6 monthly returns is in the top 10% of its history;
  2. a two-sided CUSUM on standardised returns fired in the last 3 months;
  3. the range is wider than 90% of its past widths.
An alert needs two of three.

Buy ahead. For each option (buy all now, buy half now, wait) the cost of the next months' need is computed over
scenarios drawn from the series' past monthly returns; the suggestion minimises the average of the worst 10%
(CVaR), provided its expected extra cost stays within the hedge budget. Otherwise: wait.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np

from . import market

ALPHA = 0.10  # 90% range
GAMMA = 0.005  # ACI step size
WARMUP = 60  # months of history before the first range
STORAGE_PER_MONTH = 0.01  # storage and capital cost, share of the value per month
HEDGE_BUDGET = 0.01  # the owner accepts up to 1% expected extra cost for protection


def _months(s: dict[str, float], until: Optional[str]) -> tuple[list[str], np.ndarray]:
    keys = sorted(k for k in s if until is None or k <= until)
    return keys, np.array([s[k] for k in keys], dtype=float)


@dataclass
class Range:
    series: str
    month: str  # last month with data
    price: float
    low: float
    high: float
    alpha_t: float
    coverage: float  # realised coverage of the ACI ranges over the whole backtest
    n_backtest: int
    widths: list = field(default_factory=list)


def aci(series_name: str, until: Optional[str] = None, alpha: float = ALPHA, gamma: float = GAMMA) -> Range:
    """Run ACI over the series up to `until` and return the range for the following month."""
    keys, p = _months(market.series()[series_name], until)
    r = np.abs(np.diff(np.log(p)))  # score: absolute log-return of the no-change forecast
    a_t, hits, n, widths = alpha, 0, 0, []
    for t in range(WARMUP, len(r)):
        level = min(1.0, max(0.0, 1 - a_t))
        q = float(np.quantile(r[:t], level)) if level < 1 else float("inf")
        covered = r[t] <= q
        widths.append(q)
        hits += covered
        n += 1
        a_t = a_t + gamma * (alpha - (0 if covered else 1))
    level = min(1.0, max(0.0, 1 - a_t))
    q = float(np.quantile(r, level)) if level < 1 else float(r.max())
    return Range(series_name, keys[-1], float(p[-1]), float(p[-1] * math.exp(-q)), float(p[-1] * math.exp(q)),
                 round(a_t, 4), round(hits / n, 4) if n else float("nan"), n, widths + [q])


def signals(series_name: str, until: Optional[str] = None) -> dict:
    keys, p = _months(market.series()[series_name], until)
    ret = np.diff(np.log(p))
    vol = np.array([ret[max(0, i - 6):i].std() for i in range(6, len(ret) + 1)])
    vol_now = float(vol[-1])
    vol_hi = vol_now >= float(np.quantile(vol, 0.9))
    # CUSUM on returns standardised by their trailing 36-month mean and spread.
    k, h = 0.5, 4.0
    sp = sn = 0.0
    fired = []
    for i in range(36, len(ret)):
        w = ret[i - 36:i]
        z = (ret[i] - w.mean()) / (w.std() or 1e-9)
        sp, sn = max(0.0, sp + z - k), max(0.0, sn - z - k)
        if sp > h or sn > h:
            fired.append(i)
            sp = sn = 0.0
    cusum = bool(fired) and fired[-1] >= len(ret) - 3
    rg = aci(series_name, until)
    wide = rg.widths[-1] >= float(np.quantile(rg.widths[:-1], 0.9)) if len(rg.widths) > 10 else False
    count = int(vol_hi) + int(cusum) + int(wide)
    return {"volatility_top10": vol_hi, "volatility": round(vol_now, 4), "cusum_fired": cusum, "wide_range": wide,
            "signals": count, "alert": count >= 2}


def buy_ahead(series_name: str, need_t_per_month: float, months: int = 2, until: Optional[str] = None,
              cash_available: Optional[float] = None) -> dict:
    """Compare buying the next `months` of need now, half now, or waiting, in index $/t terms."""
    keys, p = _months(market.series()[series_name], until)
    ret = np.diff(np.log(p))[-240:]  # the last 20 years of monthly moves as scenarios
    price = float(p[-1])
    need = need_t_per_month * months
    # Scenario price paths for the months ahead, from blocks of consecutive past returns.
    paths = np.array([[price * math.exp(ret[i:i + m].sum()) for m in range(1, months + 1)]
                      for i in range(len(ret) - months)])
    later = paths.mean(axis=1)  # buying month by month: the average price over the period
    options = {"buy_all": 1.0, "buy_half": 0.5, "wait": 0.0}
    out = {}
    for name, share in options.items():
        now_qty = need * share
        storage = now_qty * price * STORAGE_PER_MONTH * (months / 2)
        cost = now_qty * price + (need - now_qty) * later + storage
        worst = np.sort(cost)[-max(1, len(cost) // 10):]
        out[name] = {"now_t": round(now_qty, 3), "expected": round(float(cost.mean()), 2), "cvar_10": round(float(worst.mean()), 2),
                     "storage": round(storage, 2), "cash_now": round(now_qty * price, 2)}
    base = out["wait"]["expected"]
    feasible = {k: v for k, v in out.items() if v["expected"] - base <= HEDGE_BUDGET * base
                and (cash_available is None or v["cash_now"] <= cash_available)}
    pick = min(feasible, key=lambda k: feasible[k]["cvar_10"]) if feasible else "wait"
    lo, hi = np.quantile(later, [0.05, 0.95])
    return {"series": series_name, "month": keys[-1], "price": round(price, 2), "need_t": round(need, 3), "months": months,
            "scenarios": len(later), "range_90": [round(float(lo), 2), round(float(hi), 2)], "options": out,
            "suggestion": pick, "worst_case_saving": round(out["wait"]["cvar_10"] - out[pick]["cvar_10"], 2)}


def watch(led, until: Optional[str] = None) -> list[dict]:
    """One card per indexed material the company buys: range, signals, and (on an alert) a buy-ahead comparison.
    Need per month is the company's average monthly purchase of the material over the last 6 months (from the
    ERP's purchase orders, converted to tonnes), a stand-in for the production plan."""
    until = until or led.today[:7]
    cards = []
    for item, mat in led.materials.items():
        if not mat.series:
            continue
        start = date.fromisoformat(led.today).replace(day=1)
        six = f"{start.year - (1 if start.month <= 6 else 0)}-{(start.month - 6 - 1) % 12 + 1:02d}"
        qty = sum(l.qty for po in led.pos.values() if six <= po.date[:7] <= until for l in po.lines if l.item == item)
        need = round(qty * mat.tonnes_per_unit / 6, 3)  # index prices are per tonne
        rg = aci(mat.series, until)
        sig = signals(mat.series, until)
        card = {"item": item, "material": mat.name, "series": mat.series, "source": market.SOURCE, "month": rg.month,
                "price": round(rg.price, 2), "range_90": [round(rg.low, 2), round(rg.high, 2)],
                "aci_alpha_t": rg.alpha_t, "backtest_coverage": rg.coverage, "backtest_months": rg.n_backtest,
                "need_t_per_month": need, "unit": mat.unit, "tonnes_per_unit": mat.tonnes_per_unit, **sig}
        if sig["alert"] and need > 0:
            card["buy_ahead"] = buy_ahead(mat.series, need, until=until)
        cards.append(card)
    return cards


def backtest(alpha: float = ALPHA) -> dict:
    """Realised coverage of the ACI ranges for every series (the guarantee is about the long run)."""
    return {name: {"coverage": aci(name, alpha=alpha).coverage, "months": aci(name, alpha=alpha).n_backtest, "target": 1 - alpha}
            for name in market.series()}
