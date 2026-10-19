"""Bank dispute and arbiter decision on a reserve claim (spec V4), each from its own wallet, checked by the agent."""
import shutil
import subprocess

import pytest
from eth_account import Account

from apagent import demo
from apagent.config import CHAIN_DIR
from apagent.intake import parse_statement
from tests.test_e2e_chain import _node_up

pytestmark = pytest.mark.skipif(not _node_up(), reason="local hardhat node not running")


def _send(chain, key: str, tx: dict) -> str:
    acct = Account.from_key(key)
    full = {"to": tx["to"], "data": tx["data"], "chainId": tx["chainId"], "gas": int(tx["gas"], 16),
            "nonce": chain.w3.eth.get_transaction_count(acct.address), "gasPrice": chain.w3.eth.gas_price}
    h = chain.w3.eth.send_raw_transaction(acct.sign_transaction(full).raw_transaction)
    chain.w3.eth.wait_for_transaction_receipt(h)
    return "0x" + h.hex().removeprefix("0x")


def test_bank_disputes_and_arbiter_settles():
    from apagent import views
    from apagent.chain import hardhat_keys
    from apagent.session import Session

    subprocess.run([shutil.which("npx") or "npx", "hardhat", "run", "scripts/deploy.js", "--network", "localhost"],
                   cwd=CHAIN_DIR, check=True, capture_output=True)
    s = Session("localhost", signing="server")  # the manager's signatures come from the server in this test
    s.chain.advance(s.chain.cool_down + 1)
    keys = hardhat_keys()
    paid = s.ingest("t04_missed_credit")
    assert paid["tier"] == "T1"
    p = demo.STATEMENTS_DIR / "SHATINPCB-2025-12.csv"
    case = next(c for c in s.statement("SHATINPCB", p.name, p.read_bytes()) if c.kind == "missed_credit")
    out = s.agent.confirm_case(case.case_id)
    assert out["claim"]["ok"]
    bill = paid["bill"]
    assert views._claim(s, bill)["status"] == "filed"

    # The bank disputes from its wallet; the contract refuses a dispute from anyone else.
    tx = s.agent.bank_tx_request("dispute", bill)["tx"]
    with pytest.raises(Exception, match="NotAuthorized"):
        _send(s.chain, keys[0], tx)  # the owner's key
    h = _send(s.chain, keys[4], tx)
    assert s.agent.bank_action("dispute", h, bill)["ok"]
    # The same transaction cannot be passed off as the arbiter's decision.
    assert "error" in s.agent.bank_action("resolve", h, bill, 1.0)
    assert views._claim(s, bill)["status"] == "disputed"

    # The arbiter (its own key, not the owner's) approves part of the loss; the claim is then paid.
    loss = views._claim(s, bill)["loss_usd"]
    tx = s.agent.bank_tx_request("resolve", bill, round(loss / 2, 2))["tx"]
    assert s.chain.role_address("arbiter") not in (s.chain.role_address("owner"), s.chain.role_address("underwriter"))
    assert s.agent.bank_action("resolve", _send(s.chain, keys[6], tx), bill, round(loss / 2, 2))["ok"]
    assert views._claim(s, bill)["status"] == "resolved"
    assert s.agent.execute_claim(bill)["ok"]
    c = views._claim(s, bill)
    assert c["status"] == "paid" and abs(c["paid_usd"] - round(loss / 2, 2)) < 0.01
    d = next(x for x in views.disputes(s) if x["bill"] == bill and x["kind"] == "missed_credit")
    kinds = [e["kind"] for e in d["timeline"]]
    assert "claim_dispute" in kinds and "claim_resolve" in kinds
