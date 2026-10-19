"""Demo parameters (plan sections 7.1, 8 and 17). Amounts are in US dollars unless named *_units.

On-chain amounts use tUSDC with 6 decimals, where 1 tUSDC stands for $1,000.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CHAIN_DIR = ROOT / "chain"


def load_env(env_path: Optional[Path] = None) -> None:
    """Load key-value pairs from .env into os.environ without overwriting existing environment variables."""
    p = env_path or (ROOT / ".env")
    if not p.exists():
        return
    try:
        content = p.read_text(encoding="utf-8")
    except Exception:
        return
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and ((v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'"))):
            v = v[1:-1]
        elif "#" in v:
            v = v.split("#", 1)[0].strip()
        if "${" in v:
            v = re.sub(r"\$\{([A-Za-z0-9_]+)\}", lambda m: os.environ.get(m.group(1), ""), v)
        if k and k not in os.environ:
            os.environ[k] = v


load_env()
load_env(CHAIN_DIR / ".env")

USD_PER_TUSDC = 1_000
TUSDC_DECIMALS = 6


def usd_to_units(usd: float) -> int:
    """Dollars to on-chain tUSDC base units (rounded to the cent)."""
    cents = round(usd * 100)
    return cents * 10**TUSDC_DECIMALS // (USD_PER_TUSDC * 100)


def units_to_usd(units: int) -> float:
    return round(units * USD_PER_TUSDC / 10**TUSDC_DECIMALS, 2)


@dataclass(frozen=True)
class Bundle:
    """One position of the risk dial (plan 8.2). P-CAP is fixed for the vault."""

    name: str
    beta: float  # loss budget: expected share of bill value lost on T1 payments
    p_nday: int  # daily T1 count cap
    p_day_usd: float  # daily T1 amount cap
    label: str = ""

    @property
    def n_window(self) -> int:
        return self.p_nday * 30


@dataclass
class Settings:
    p_cap_usd: float = 5_000.0  # P-CAP
    p_supweek_usd: float = 5_000.0  # P-SUPWEEK
    window_days: int = 30  # P-WINDOW used by K(beta)
    eps: float = 0.01  # P(claims in a window > K) <= eps
    delta: float = 0.05  # confidence 1 - delta for the bounds
    price_tolerance: float = 0.01  # order price tolerance
    tax_rate: float = 0.0  # Hong Kong has no VAT/GST
    fair_price_tolerance: float = 0.02  # 2 points of excess
    history_price_tolerance: float = 0.10  # no index: flag a rise above the item's usual changes, and at least 10%
    probation_bills: int = 5
    break_attempts: int = 3  # P-BREAK: blocked attempts ...
    break_window_s: int = 600  # ... within 10 minutes
    premium_loading: float = 1.2
    capital_rate: float = 0.10  # rho, per year
    cash_floor_usd: float = 150_000.0
    credit_rate: float = 0.08  # annual rate on the credit line
    alpha_intent: float = 0.03
    alpha_slot: float = 0.05
    injection_threshold: float = 0.5
    drift_eta: float = 2.0
    bundles: tuple = field(
        default_factory=lambda: (
            Bundle("careful", 0.005, 3, 10_000, "Be more careful"),
            Bundle("standard", 0.010, 5, 15_000, "Standard"),
            Bundle("more", 0.015, 8, 20_000, "Let it pay more on its own"),
            Bundle("most", 0.020, 10, 25_000, "Most autonomy"),
        )
    )

    def bundle(self, name: str) -> Bundle:
        for b in self.bundles:
            if b.name == name:
                return b
        raise KeyError(name)


SETTINGS = Settings()
