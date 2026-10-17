"""Fit the score, calibrate cut-offs per group and bundle, and compute K(beta).

Data discipline: the score model is trained on a separate simulated year (seed TRAIN_SEED).
The calibration world is split in half: calibration and test (AC-8 repeats this over 100 splits).
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from ..config import DATA_DIR, SETTINGS, Settings
from ..sim import simulate
from . import capital, crc
from .features import FEATURES
from .replay import Record, replay

TRAIN_SEED = 101
CAL_SEED = 7
GROUPS = ["routine", "new_supplier", "price_change", "other"]
CALIBRATION_FILE = DATA_DIR / "calibration.json"


@dataclass
class ScoreModel:
    mean: list
    scale: list
    coef: list
    intercept: float

    def score(self, x: np.ndarray) -> np.ndarray:
        z = (np.atleast_2d(x) - np.array(self.mean)) / np.array(self.scale)
        logit = np.clip(z @ np.array(self.coef) + self.intercept, -50, 50)
        return 1 / (1 + np.exp(-logit))


def fit_score(records: list[Record], cfg: Settings = SETTINGS) -> ScoreModel:
    rows = [r for r in records if r.eligible(cfg)]
    X = np.array([r.x for r in rows])
    y = np.array([1 if r.loss > 0 else 0 for r in rows])
    sc = StandardScaler().fit(X)
    sc.scale_[sc.scale_ == 0] = 1.0
    lr = LogisticRegression(class_weight="balanced", C=0.5, max_iter=2000).fit(sc.transform(X), y)
    return ScoreModel(sc.mean_.tolist(), sc.scale_.tolist(), lr.coef_[0].tolist(), float(lr.intercept_[0]))


def arrays(records: list[Record], model: ScoreModel, cfg: Settings = SETTINGS) -> dict:
    """Per group: scores, losses l = loss/V, eligibility. Only bills with V <= P-CAP enter calibration."""
    out = {}
    for g in GROUPS:
        rs = [r for r in records if r.group == g and 0 < r.value <= cfg.p_cap_usd]
        if not rs:
            out[g] = {"s": np.zeros(0), "l": np.zeros(0), "e": np.zeros(0, bool), "z": np.zeros(0)}
            continue
        X = np.array([r.x for r in rs])
        out[g] = {
            "s": model.score(X),
            "l": np.array([r.ell for r in rs]),
            "e": np.array([r.eligible(cfg) for r in rs]),
            "z": np.array([r.loss / cfg.p_cap_usd for r in rs]),
        }
    return out


@dataclass
class BundleCal:
    name: str
    beta: float
    p_nday: int
    p_day_usd: float
    lambdas: dict
    t1_share: float
    mu_bar: float
    nu_bar: float
    n_t1_cal: int
    K_usd: float
    r_usd: float
    chen_usd: float
    naive: dict
    max_exposure_usd: float
    smallest_beta: dict = field(default_factory=dict)
    ehat: dict = field(default_factory=dict)  # loss ratio of T1 calibration cases per group (premium)


@dataclass
class Calibration:
    model: ScoreModel
    bundles: list
    groups: list
    eps: float
    delta: float
    n_cal: int
    loss_rate_cal: float
    eta: float

    def bundle(self, name: str) -> BundleCal:
        return next(b for b in self.bundles if b.name == name)

    def save(self, path: Path = CALIBRATION_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1))

    @staticmethod
    def load(path: Path = CALIBRATION_FILE) -> "Calibration":
        d = json.loads(path.read_text())
        d["model"] = ScoreModel(**d["model"])
        d["bundles"] = [BundleCal(**b) for b in d["bundles"]]
        return Calibration(**d)


def calibrate_bundles(cal: dict, cfg: Settings = SETTINGS) -> list[BundleCal]:
    m = len(cfg.bundles)
    out = []
    for b in cfg.bundles:
        lambdas, t1, n_all = {}, 0, 0
        z_t1 = []
        ehat = {}
        for g in GROUPS:
            a = cal[g]
            lam = crc.cutoff(a["s"], a["l"], a["e"], b.beta)
            lambdas[g] = lam
            mask = a["e"] & (a["s"] <= lam)
            ehat[g] = round(float(a["l"][mask].mean()), 5) if mask.any() else None
            t1 += int(mask.sum())
            n_all += len(a["s"])
            z_t1 += a["z"][mask].tolist()
        z = np.array(z_t1)
        alpha = cfg.delta / (2 * m)
        mu = capital.betting_upper(z, alpha) if len(z) else 1.0
        nu = capital.betting_upper(z**2, alpha) if len(z) else 1.0
        N = b.n_window
        K = capital.bernstein_k(N, mu, nu, cfg.eps, cfg.p_cap_usd, b.p_day_usd)
        out.append(BundleCal(
            name=b.name, beta=b.beta, p_nday=b.p_nday, p_day_usd=b.p_day_usd, lambdas=lambdas,
            t1_share=t1 / max(1, n_all), mu_bar=mu, nu_bar=nu, n_t1_cal=len(z), K_usd=round(K, 2),
            r_usd=round(K / N, 2), chen_usd=round(capital.chen_style(z, N, cfg.eps, cfg.p_cap_usd, b.p_day_usd), 2),
            naive=capital.naive_rules(z, N, cfg.p_cap_usd, b.p_day_usd), max_exposure_usd=b.p_day_usd * 30,
            smallest_beta={g: round(1 / (len(cal[g]["s"]) + 1), 4) for g in GROUPS}, ehat=ehat,
        ))
    return out


def split(records: list[Record], seed: int) -> tuple[list[Record], list[Record]]:
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(records))
    half = len(records) // 2
    return [records[i] for i in idx[:half]], [records[i] for i in idx[half:]]


def run(cfg: Settings = SETTINGS, save: bool = True) -> tuple[Calibration, list[Record], list[Record]]:
    train = replay(simulate(TRAIN_SEED), cfg)
    model = fit_score(train, cfg)
    records = replay(simulate(CAL_SEED), cfg)
    cal_recs, test_recs = split(records, 0)
    cal = arrays(cal_recs, model, cfg)
    bundles = calibrate_bundles(cal, cfg)
    elig = [r for r in cal_recs if r.eligible(cfg)]
    loss_rate = float(np.mean([r.ell for r in elig])) if elig else 0.0
    # Drift guard step: one typical error lowers the cut-off by at least one score bin (1/50 of the range).
    typical = float(np.median([r.ell for r in elig if r.loss > 0])) if any(r.loss > 0 for r in elig) else 0.2
    eta = (1 / 50) / max(1e-6, typical - 0.01)
    c = Calibration(model, bundles, GROUPS, cfg.eps, cfg.delta, len(cal_recs), loss_rate, round(eta, 4))
    if save:
        c.save()
    return c, cal_recs, test_recs


if __name__ == "__main__":
    c, _, _ = run()
    print(f"score features: {FEATURES}")
    for b in c.bundles:
        print(f"{b.name:9s} beta={b.beta:.3%} T1 share={b.t1_share:.1%} mu={b.mu_bar:.4f} K=${b.K_usd:,.0f} "
              f"r=${b.r_usd:,.0f} Chen=${b.chen_usd:,.0f} max=${b.max_exposure_usd:,.0f} lambdas={ {k: round(v, 3) for k, v in b.lambdas.items()} }")
