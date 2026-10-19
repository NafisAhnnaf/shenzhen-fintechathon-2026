"""Certified capital K(beta) (plan 8.2).

P(total claims on payments open in one window > K) <= eps, with confidence 1 - delta, if errors are independent.

1. z = loss / P-CAP in [0, 1] for calibration cases that would be T1.
2. Upper confidence bounds on E[z] and E[z^2] by betting (Waudby-Smith & Ramdas, JRSS-B 2024), each at delta/(2m).
3. N = P-NDAY * 30 is the most T1 payments the contract allows in a window.
4. Bernstein: K = min(P-CAP * [N mu + sqrt(2 N nu ln(1/eps)) + (2/3) ln(1/eps)], P-DAY * 30).
"""
from __future__ import annotations

import math

import numpy as np


def betting_upper(x: np.ndarray, alpha: float, grid: int = 2000, c: float = 0.75) -> float:
    """One-sided upper confidence bound for the mean of i.i.d. values in [0, 1] (hedged-capital style).

    For a candidate mean m, the capital K(m) = prod (1 - lam_i (x_i - m)) grows when the data sit below m.
    m is rejected once K(m) >= 1/alpha (Ville). The bound is the largest m that is not rejected:
    scanning upward from the sample mean, the last m before the first rejection.
    Bets lam_i are predictable (built from x_1..x_{i-1}) with the plug-in rule of the paper.
    """
    x = np.clip(np.asarray(x, dtype=float), 0.0, 1.0)
    n = len(x)
    if n == 0:
        return 1.0
    # predictable mean and variance estimates
    csum = np.concatenate([[0.0], np.cumsum(x)[:-1]])
    i = np.arange(1, n + 1)
    mu_hat = (0.5 + csum) / i
    sq = np.concatenate([[0.0], np.cumsum((x - (0.5 + np.cumsum(x)) / (i + 1)) ** 2)[:-1]])
    var_hat = (0.25 + sq) / i
    lam_raw = np.sqrt(2 * math.log(1 / alpha) / (n * var_hat))
    lo = float(np.mean(x))
    last = lo
    for m in np.linspace(lo, 1.0, grid):
        lam = np.minimum(lam_raw, c / max(1e-12, 1 - m))
        logk = np.sum(np.log1p(-lam * (x - m)))
        if logk >= math.log(1 / alpha):
            return float(m)  # first rejected value: a conservative upper bound on the grid
        last = float(m)
    return 1.0 if last >= 1.0 - 1e-9 else last


def bernstein_k(n_window: int, mu: float, nu: float, eps: float, p_cap: float, p_day: float) -> float:
    L = math.log(1 / eps)
    k = p_cap * (n_window * mu + math.sqrt(2 * n_window * nu * L) + (2.0 / 3.0) * L)
    return min(k, p_day * 30)


def chen_style(z: np.ndarray, n_window: int, eps: float, p_cap: float, p_day: float) -> float:
    """Per-action reserves with a union bound over the window (our reading of Chen 2026).

    Each payment reserves the (1 - eps/N) conformal quantile of its own loss. With n calibration cases the
    quantile is finite only if n >= N/eps - 1; otherwise each payment must reserve its full exposure P-CAP.
    """
    n = len(z)
    level = 1 - eps / n_window
    k = math.ceil((n + 1) * level)
    per_action = p_cap if k > n else float(np.sort(z)[k - 1]) * p_cap
    return min(n_window * per_action, p_day * 30)


def naive_rules(z: np.ndarray, n_window: int, p_cap: float, p_day: float) -> dict:
    return {
        "expected_loss_only": float(n_window * p_cap * (np.mean(z) if len(z) else 0.0)),
        "ten_pct_max_exposure": 0.1 * p_day * 30,
    }


def window_exceedance(z: np.ndarray, k: float, n_window: int, p_cap: float, trials: int, rng: np.random.Generator) -> float:
    """Share of simulated windows where claims exceed K, drawing N T1 payments from held-out z."""
    if len(z) == 0:
        return 0.0
    draws = rng.choice(z, size=(trials, n_window), replace=True).sum(axis=1) * p_cap
    return float(np.mean(draws > k))


def stress_exceedance(z: np.ndarray, k: float, n_window: int, p_cap: float, supplier_cap_window: float,
                      n_hit: int, severity: float, trials: int, rng: np.random.Generator) -> float:
    """Correlated stress case: one supplier change (e.g. a new invoice layout) hits n_hit payments in one window.

    The n_hit payments fail together, each losing `severity` of P-CAP. The contract's per-supplier weekly cap
    bounds what one supplier can take alone in a window (supplier_cap_window = P-SUPWEEK * 30/7), so the shock
    is min(n_hit * P-CAP * severity, supplier_cap_window). The other N - n_hit payments are drawn from held-out z.
    Returns the share of windows where total claims exceed K.
    """
    if len(z) == 0:
        return 0.0
    n_hit = min(n_hit, n_window)
    rest = rng.choice(z, size=(trials, n_window - n_hit), replace=True).sum(axis=1) * p_cap
    shock = min(n_hit * p_cap * severity, supplier_cap_window)
    return float(np.mean(rest + shock > k))
