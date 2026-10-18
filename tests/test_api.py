"""API on the local chain in SIGNING=client mode. The test plays the people's wallets: it signs the EIP-712
typed data the API returns with the finance manager's key, and sends the owner's transactions itself."""
import os

import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data
from fastapi.testclient import TestClient

from tests.test_e2e_chain import _node_up

pytestmark = pytest.mark.skipif(not _node_up(), reason="local hardhat node not running")


def _wallet_sign(key: str, typed: dict) -> str:
    """What a browser wallet does with eth_signTypedData_v4."""
    msg = encode_typed_data(full_message=typed)
    return "0x" + Account.sign_message(msg, key).signature.hex().removeprefix("0x")


def _wallet_send(chain, key: str, tx: dict) -> str:
    acct = Account.from_key(key)
    full = {"to": tx["to"], "data": tx["data"], "chainId": tx["chainId"], "gas": int(tx["gas"], 16),
            "nonce": chain.w3.eth.get_transaction_count(acct.address), "gasPrice": chain.w3.eth.gas_price}
    return "0x" + chain.w3.eth.send_raw_transaction(acct.sign_transaction(full).raw_transaction).hex().removeprefix("0x")


@pytest.fixture(scope="module")
def client():
    os.environ["SIGNING"] = "client"
    from apagent import api
    api.SIGNING = "client"
    api._session = None
    c = TestClient(api.app)
    assert c.post("/api/admin/reset").status_code == 200
    return c, api


def test_state_and_server_holds_no_people_keys(client):
    c, _ = client
    st = c.get("/api/state").json()
    assert st["chain"]["mode"] == "bonded" and st["consistency"]["ok"]
    assert set(st["server_holds"]) == {"agent", "governor", "underwriter"}


def test_upload_e_invoice_pays_alone(client):
    from apagent import demo
    c, _ = client
    p = demo.DOCS_DIR / "t01_routine.json"
    r = c.post("/api/documents", files={"file": (p.name, p.read_bytes(), "application/json")}).json()
    assert r["tier"] == "T1" and r["tx"]["ok"] and r["source"] == "e-invoice"


def test_pdf_upload_without_reader_is_503(client):
    from apagent import demo
    c, _ = client
    os.environ.pop("VLM_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("gemini_api_key", None)
    p = demo.DOCS_DIR / "t13_net30.pdf"
    r = c.post("/api/documents", files={"file": (p.name, p.read_bytes(), "application/pdf")})
    assert r.status_code == 503


def test_t2_approval_signed_in_wallet(client):
    from apagent.chain import hardhat_keys
    c, _ = client
    r = c.post("/api/inbox/documents/t16_fair_price").json()
    assert r["tier"] == "T2"
    bill = r["bill"]
    # Without a signature the server cannot approve: it does not hold the manager's key.
    assert c.post(f"/api/bills/{bill}/approve", json={}).status_code == 428
    req = c.get(f"/api/bills/{bill}/approval").json()
    sig = _wallet_sign(hardhat_keys()[3], req["typed_data"])  # finance manager (approver) key
    # A signature from the wrong key is refused.
    bad = _wallet_sign(hardhat_keys()[5], req["typed_data"])
    assert "error" in c.post(f"/api/bills/{bill}/approve", json={"signature": bad, "expiry": req["expiry"]}).json()
    out = c.post(f"/api/bills/{bill}/approve", json={"signature": sig, "expiry": req["expiry"]}).json()
    assert out["tx"]["ok"] and out["amount"] == req["amount"]


def test_settings_sent_from_owner_wallet(client):
    from apagent.chain import hardhat_keys
    c, api = client
    tx = c.get("/api/dial/tx", params={"bundle": "careful"}).json()["tx"]
    h = _wallet_send(api.S().chain, hardhat_keys()[0], tx)  # owner wallet
    out = c.post("/api/dial", json={"bundle": "careful", "tx_hash": h}).json()
    assert out["active"] and out["state"]["p_nday"] == 3  # the underwriter service co-signed


def test_state_survives_restart(client):
    c, api = client
    before = c.get("/api/bills").json()
    api._session = None  # simulate a server restart: state is reloaded from disk
    after = c.get("/api/bills").json()
    assert [b["bill"] for b in before] == [b["bill"] for b in after]
    assert c.get("/api/state").json()["consistency"]["ok"]


def test_request_plan_and_attack(client):
    c, _ = client
    q = c.post("/api/request", json={"text": "pay the copper supplier"}).json()
    assert q["kind"] == "question"
    atk = c.post("/api/naive/attack").json()
    assert atk["naive"]["ok"] and atk["ours"]["tier"] == "hold"
    assert len(c.get("/api/log", params={"security": True}).json()) >= 2
