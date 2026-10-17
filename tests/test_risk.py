"""Conformal risk control, capital bound, calibration artefact."""
import math

import numpy as np
import pytest

from apagent.risk import capital, crc


def test_cutoff_respects_bound_on_calibration():
    rng = np.random.default_rng(1)
    n = 500
    s = rng.random(n)
    loss = np.where(rng.random(n) < s * 0.1, rng.random(n) * 0.5, 0.0)  # riskier scores lose more
    e = np.ones(n, bool)
    for beta in (0.005, 0.01, 0.02):
        lam = crc.cutoff(s, loss, e, beta)
        risk = (np.sum(loss[(s <= lam)]) + 1) / (n + 1)
        assert risk <= beta + 1e-12
        lam2 = crc.cutoff(s, loss, e, beta * 2)
        assert lam2 >= lam  # monotone in beta


def test_data_limit():
    assert crc.min_n(0.01) == 99
    assert crc.cutoff(np.zeros(50), np.zeros(50), np.ones(50, bool), 0.01) == crc.NO_T1


def test_crc_holds_out_of_sample():
    """Average test loss over many splits stays under beta (the guarantee is in expectation)."""
    rng = np.random.default_rng(2)
    beta, means = 0.01, []
    for _ in range(200):
        n = 600
        s = rng.random(2 * n)
        loss = np.where(rng.random(2 * n) < 0.02 + 0.15 * s, rng.random(2 * n), 0.0)
        e = np.ones(2 * n, bool)
        lam = crc.cutoff(s[:n], loss[:n], e[:n], beta)
        means.append(crc.realised(s[n:], loss[n:], e[n:], lam)[0])
    assert np.mean(means) <= beta


def test_betting_upper_bound_covers():
    rng = np.random.default_rng(3)
    true, cover = 0.03 * 0.15, 0
    for _ in range(200):
        x = np.where(rng.random(400) < 0.03, rng.random(400) * 0.3, 0.0)
        cover += capital.betting_upper(x, 0.05) >= true
    assert cover / 200 >= 0.95


def test_bernstein_formula_and_cap():
    k = capital.bernstein_k(150, 0.006, 0.006, 0.01, 5000, 15000)
    L = math.log(100)
    assert k == pytest.approx(5000 * (150 * 0.006 + math.sqrt(2 * 150 * 0.006 * L) + 2 / 3 * L))
    assert capital.bernstein_k(150, 1.0, 1.0, 0.01, 5000, 15000) == 15000 * 30


def test_chen_style_needs_full_exposure_with_small_data():
    """With n < N/eps - 1 each payment reserves P-CAP; the total is capped by the contract's window maximum."""
    z = np.zeros(500)
    assert capital.chen_style(z, 150, 0.01, 5000, 15000) == min(150 * 5000, 15000 * 30)
    assert capital.chen_style(z, 150, 0.01, 5000, 100000) == 150 * 5000


def test_calibration_artifact(calib):
    names = [b.name for b in calib.bundles]
    assert names == ["careful", "standard", "more", "most"]
    shares = [b.t1_share for b in calib.bundles]
    assert shares == sorted(shares)  # more budget, more autonomy
    for b in calib.bundles:
        assert b.K_usd <= b.max_exposure_usd
        assert b.K_usd < b.chen_usd
        assert b.r_usd == pytest.approx(b.K_usd / (b.p_nday * 30), abs=0.01)
