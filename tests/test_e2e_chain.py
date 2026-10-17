"""End to end on a local Hardhat node: redeploy, then every scripted task must pass.

Needs `npx hardhat node` running on 127.0.0.1:8545 (see README). Skipped otherwise.
"""
import subprocess

import httpx
import pytest

from apagent.config import CHAIN_DIR


def _node_up() -> bool:
    try:
        httpx.post("http://127.0.0.1:8545", json={"jsonrpc": "2.0", "method": "eth_chainId", "params": [], "id": 1}, timeout=2)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _node_up(), reason="local hardhat node not running")


def test_all_scripted_tasks_pass():
    subprocess.run(["npx", "hardhat", "run", "scripts/deploy.js", "--network", "localhost"], cwd=CHAIN_DIR,
                   check=True, capture_output=True)
    from apagent.tasks import Runner

    r = Runner("localhost")
    r.ch.advance(301)
    for day in (r.day1, r.day2, r.day3, r.day4):
        day()
    failed = [(e.task, e.error) for e in r.out if not e.ok]
    assert not failed, failed
