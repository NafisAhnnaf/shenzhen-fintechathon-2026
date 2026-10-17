"""Conformal risk control cut-offs (Angelopoulos et al., ICLR 2024), plan 8.1.

T1 if s <= lambda_g, with lambda_g(beta) = max{ lambda : (sum_i L_i(lambda) + B) / (n_g + 1) <= beta }
where L_i(lambda) = l_i * 1[eligible_i and s_i <= lambda] is monotone in lambda and bounded by B = 1.
Over all bills in the group (eligible or not), E[L_new(lambda_g)] <= beta, if new bills are exchangeable
with calibration bills.
"""
from __future__ import annotations

import numpy as np

NO_T1 = -1.0  # a cut-off below every score: nothing goes T1


def min_n(beta: float) -> int:
    """Data limit: a group gets any T1 only if n_g >= 1/beta - 1."""
    return int(np.ceil(1.0 / beta - 1.0))


def cutoff(scores: np.ndarray, losses: np.ndarray, eligible: np.ndarray, beta: float, B: float = 1.0) -> float:
    n = len(scores)
    if n < min_n(beta):
        return NO_T1
    s = np.where(eligible, scores, np.inf)
    order = np.argsort(s)
    s_sorted, l_sorted = s[order], np.where(eligible, losses, 0.0)[order]
    cum = np.cumsum(l_sorted)
    best = NO_T1
    for k in range(n):
        if not np.isfinite(s_sorted[k]):
            break
        # Ties: lambda = s_sorted[k] admits every score <= it.
        if k + 1 < n and s_sorted[k + 1] == s_sorted[k]:
            continue
        risk = (cum[k] + B) / (n + 1)
        if risk <= beta:
            best = float(s_sorted[k])
        else:
            break  # L is monotone, so risk only grows with lambda
    return best


def realised(scores: np.ndarray, losses: np.ndarray, eligible: np.ndarray, lam: float) -> tuple[float, float]:
    """(loss ratio over all bills in the group, T1 share)."""
    t1 = eligible & (scores <= lam)
    if len(scores) == 0:
        return 0.0, 0.0
    return float(np.mean(np.where(t1, losses, 0.0))), float(np.mean(t1))
