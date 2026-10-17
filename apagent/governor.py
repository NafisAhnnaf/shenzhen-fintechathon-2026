"""Governor (plan 3.1, 8): deterministic risk service. Scores bills and co-signs every autonomous payment.

T1 needs all of: checker passed, no injection flag, value <= P-CAP, group has enough calibration data,
score <= lambda_g(beta) + d_g, supplier not on probation, payee active and not frozen, agent not paused,
supplier 7-day T1 total within P-SUPWEEK, daily caps, and (reserve modes) pool free capital >= P-CAP.
Everything else goes to T2 with reasons.
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np

from .checker import CheckResult
from .config import SETTINGS, Settings
from .domain import Bill, Ledger
from .risk.calibrate import Calibration
from .risk.features import featurize, vector


GROUP_LABEL = {"routine": "routine bills", "new_supplier": "bills from new suppliers",
               "price_change": "bills with a price change", "other": "other bills"}


@dataclass
class Decision:
    tier: str  # T1, T2, reject, hold
    reasons: list[str]
    group: str
    score: Optional[float]
    cutoff: Optional[float]
    amount: float
    premium: float = 0.0
    signature: Optional[bytes] = None
    settings_id: Optional[int] = None
    expiry: Optional[int] = None
    features: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "signature"}
        d["signed"] = self.signature is not None
        return d


@dataclass
class GovernorState:
    drift: dict = field(default_factory=lambda: defaultdict(float))  # d_g <= 0
    t1_by_supplier: list = field(default_factory=list)  # (date, supplier, usd)
    t1_by_day: dict = field(default_factory=dict)  # day -> [usd, count]
    blocked: list = field(default_factory=list)  # timestamps of blocked attempts


class Governor:
    def __init__(self, calib: Calibration, cfg: Settings = SETTINGS, chain=None):
        self.cal = calib
        self.cfg = cfg
        self.chain = chain
        self.state = GovernorState()
        self.bundle_name = "standard"

    # ------------------------------------------------------------------ score
    def score(self, led: Ledger, bill: Bill, res: CheckResult) -> tuple[float, dict]:
        f = featurize(led, bill, res, photo=bill.source == "photo")
        return float(self.cal.model.score(vector(f))[0]), f

    def cutoff(self, group: str) -> float:
        b = self.cal.bundle(self.bundle_name)
        return b.lambdas.get(group, -1.0) + self.state.drift[group]

    # ------------------------------------------------------------------ decide
    def decide(self, led: Ledger, bill: Bill, res: CheckResult, injection_p: float, today: str,
               chain_state: Optional[dict] = None) -> Decision:
        cfg = self.cfg
        amount = res.amount.value
        group = res.group
        reasons: list[str] = []
        codes = set(res.codes)
        if "duplicate" in codes:
            return Decision("reject", [f"Duplicate of bill {res.duplicate_of}"], group, None, None, 0.0)
        if res.supplier is None:
            return Decision("hold", ["Sender is not a registered supplier"], group, None, None, 0.0)
        if "bank_change" in codes:
            return Decision("hold", ["Bank details differ from the registry: payee frozen, call-back task opened"], group, None, None, 0.0)

        s, feats = self.score(led, bill, res)
        lam = self.cutoff(group)
        for m in res.mismatches:
            reasons.append(m.reason)
        if injection_p >= cfg.injection_threshold:
            reasons.append(f"Supplier text looks like instructions to the system (p={injection_p:.2f})")
        if amount > cfg.p_cap_usd:
            reasons.append(f"Amount ${amount:,.2f} is above the per-payment cap ${cfg.p_cap_usd:,.0f}")
        if amount <= 0:
            reasons.append("Nothing payable")
        label = GROUP_LABEL.get(group, group)
        if lam < 0:
            reasons.append(f"Too little history with {label} for the agent to pay them alone at this risk setting")
        elif s > lam:
            reasons.append(f"Risk score {s:.3f} is above the limit {lam:.3f} for {label}")
        sup = res.supplier
        if sup.probation_left > 0:
            reasons.append(f"Supplier on probation: {sup.probation_left} more bills go to a person")
        if sup.frozen:
            reasons.append("Payee is frozen")
        cs = chain_state or {}
        b = self.cal.bundle(self.bundle_name)
        # Caps and the reserve only matter for a bill small enough to be paid alone.
        if 0 < amount <= cfg.p_cap_usd:
            week = self._supplier_week(sup.id, today)
            if week + amount > cfg.p_supweek_usd:
                reasons.append(f"This supplier would get ${week + amount:,.2f} in 7 days without a signature "
                               f"(limit ${cfg.p_supweek_usd:,.0f}): possible limit splitting")
            day_usd, day_n = self.state.t1_by_day.get(today, [0.0, 0])
            if day_usd + amount > (cs.get("p_day_usd") or b.p_day_usd) or day_n + 1 > (cs.get("p_nday") or b.p_nday):
                reasons.append("Today's limit for payments without a signature is used up")
            if cs.get("mode", "bonded") != "standard":
                if cs.get("pool_paused") or cs.get("pool_free_usd", 1e12) < amount + (cs.get("r_usd") or b.r_usd):
                    reasons.append("The reserve pool does not have enough free capital")
        if cs.get("agent_paused"):
            reasons.append("Agent is paused: all bills go to a person")
        if chain_state is not None and self.chain is not None:
            p = self.chain.payee(sup.id)
            if not p["active"]:
                reasons.append("Payee is not active on-chain (cool-down or frozen)")

        premium = self.premium(group, amount, cs.get("r_usd") or b.r_usd)
        if reasons:
            return Decision("T2", reasons, group, round(s, 4), round(lam, 4), amount, 0.0, features=feats)
        return Decision("T1", [f"Checks passed; risk score {s:.3f} is within the limit {lam:.3f} for {label}"], group,
                        round(s, 4), round(lam, 4), amount, premium, features=feats)

    def premium(self, group: str, amount: float, r_usd: float) -> float:
        """Bonded mode: 1.2 * e_hat * V + r * rho * 30/365."""
        e = self.cal.bundle(self.bundle_name).ehat.get(group) or 0.0
        return round(self.cfg.premium_loading * e * amount + r_usd * self.cfg.capital_rate * 30 / 365, 2)

    def sign(self, d: Decision, bill_id: str, supplier_id: str, settings_id: int, input_hash: bytes, ttl: int = 900) -> Decision:
        """Co-sign a T1 decision. The signature binds bill, payee, amount, settings and the bill's input hash."""
        if d.tier != "T1" or self.chain is None:
            return d
        d.settings_id = settings_id
        d.expiry = self.chain.now() + ttl
        d.signature = self.chain.gov_signature(bill_id, supplier_id, d.amount, settings_id, d.expiry, input_hash)
        return d

    # ------------------------------------------------------------------ bookkeeping
    def record_t1(self, supplier_id: str, usd: float, today: str) -> None:
        self.state.t1_by_supplier.append((today, supplier_id, usd))
        day = self.state.t1_by_day.setdefault(today, [0.0, 0])
        day[0] += usd
        day[1] += 1

    def _supplier_week(self, supplier_id: str, today: str) -> float:
        start = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
        return sum(u for d, s, u in self.state.t1_by_supplier if s == supplier_id and start <= d <= today)

    def outcome(self, group: str, ell: float) -> None:
        """Drift guard: d_g <- min(0, d_g + eta (beta - l_t)) after each known T1 outcome."""
        beta = self.cal.bundle(self.bundle_name).beta
        d = self.state.drift[group] + self.cal.eta * (beta - ell)
        self.state.drift[group] = min(0.0, d)

    def blocked_attempt(self, now: Optional[float] = None) -> bool:
        """Count a blocked attempt; True when the circuit breaker should trip (P-BREAK)."""
        now = now if now is not None else time.time()
        self.state.blocked = [t for t in self.state.blocked if now - t <= self.cfg.break_window_s] + [now]
        return len(self.state.blocked) >= self.cfg.break_attempts
