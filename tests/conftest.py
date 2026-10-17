import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apagent import demo  # noqa: E402
from apagent.domain import Ledger  # noqa: E402
from apagent.risk.calibrate import CALIBRATION_FILE, Calibration, run as calibrate_run  # noqa: E402


@pytest.fixture(scope="session")
def calib() -> Calibration:
    if not CALIBRATION_FILE.exists():
        calibrate_run()
    return Calibration.load()


@pytest.fixture(scope="session")
def demo_world():
    if not (demo.DEMO_DIR / "ledger.json").exists() or not (demo.DOCS_DIR / "t01_routine.json").exists():
        demo.build()
    return Ledger.load(demo.DEMO_DIR / "ledger.json"), demo.load_docs()


@pytest.fixture()
def ledger(demo_world):
    return copy.deepcopy(demo_world[0])


@pytest.fixture()
def docs(demo_world):
    return demo_world[1]
