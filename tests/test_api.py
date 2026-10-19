"""API on the local chain in SIGNING=client mode. The test plays the people's wallets: it signs the EIP-712
typed data the API returns with the finance manager's key, and sends the owner's transactions itself."""
import os

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
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


def _login(c, key: str) -> dict:
    """Sign-in with the wallet: sign the server's challenge with personal_sign, get a session token."""
    acct = Account.from_key(key)
    ch = c.post("/api/auth/challenge", json={"address": acct.address}).json()
    sig = "0x" + Account.sign_message(encode_defunct(text=ch["message"]), key).signature.hex().removeprefix("0x")
    r = c.post("/api/auth/login", json={"nonce": ch["nonce"], "signature": sig})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def client():
    """A client signed in as the owner by default; ROLE_HEADERS has the other people's sessions."""
    from apagent.chain import hardhat_keys
    os.environ["SIGNING"] = "client"
    os.environ.pop("AUTH", None)
    from apagent import api
    api.SIGNING = "client"
    api._session = None
    c = TestClient(api.app)
    keys = hardhat_keys()
    ROLE_HEADERS.update(owner=_login(c, keys[0]), fm=_login(c, keys[3]), bank=_login(c, keys[4]),
                        viewer=_login(c, keys[5]))
    c.cookies.clear()
    c.headers.update(ROLE_HEADERS["owner"])
    assert c.post("/api/admin/reset").status_code == 200
    return c, api


ROLE_HEADERS: dict = {}
FM = lambda: ROLE_HEADERS["fm"]  # noqa: E731


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
    # Only the finance manager's session may approve.
    assert c.post(f"/api/bills/{bill}/approve", json={}).status_code == 403
    # Without a signature the server cannot approve: it does not hold the manager's key.
    assert c.post(f"/api/bills/{bill}/approve", json={}, headers=FM()).status_code == 428
    req = c.get(f"/api/bills/{bill}/approval", headers=FM()).json()
    sig = _wallet_sign(hardhat_keys()[3], req["typed_data"])  # finance manager (approver) key
    # A signature from the wrong key is refused.
    bad = _wallet_sign(hardhat_keys()[5], req["typed_data"])
    assert "error" in c.post(f"/api/bills/{bill}/approve", json={"signature": bad, "expiry": req["expiry"]}, headers=FM()).json()
    out = c.post(f"/api/bills/{bill}/approve", json={"signature": sig, "expiry": req["expiry"]}, headers=FM()).json()
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


# ------------------------------------------------------------------ sign-in, roles, replay, final states (spec X2-X4)
def test_sign_in_required_and_roles_enforced(client):
    c, api = client
    anon = TestClient(api.app)
    assert anon.get("/api/state").status_code == 401
    assert anon.get("/api/public").status_code == 200  # the sign-in page needs it
    me = c.get("/api/auth/me", headers=ROLE_HEADERS["viewer"]).json()
    assert me["role"] == "viewer"
    assert c.get("/api/bills", headers=ROLE_HEADERS["viewer"]).status_code == 200
    assert c.post("/api/pause", headers=ROLE_HEADERS["viewer"]).status_code == 403
    assert c.get("/api/dial/tx", params={"bundle": "careful"}, headers=FM()).status_code == 403
    assert c.post("/api/admin/reset", headers=FM()).status_code == 403


def test_challenge_cannot_be_reused_or_signed_by_someone_else(client):
    from apagent.chain import hardhat_keys
    c, _ = client
    keys = hardhat_keys()
    owner = Account.from_key(keys[0]).address
    ch = c.post("/api/auth/challenge", json={"address": owner}).json()
    forged = "0x" + Account.sign_message(encode_defunct(text=ch["message"]), keys[5]).signature.hex().removeprefix("0x")
    assert c.post("/api/auth/login", json={"nonce": ch["nonce"], "signature": forged}).status_code == 401
    # The nonce was used up by the failed attempt.
    good = "0x" + Account.sign_message(encode_defunct(text=ch["message"]), keys[0]).signature.hex().removeprefix("0x")
    assert c.post("/api/auth/login", json={"nonce": ch["nonce"], "signature": good}).status_code == 401


def test_request_role_comes_from_the_wallet(client):
    c, _ = client
    # The finance manager claims to be the owner in the body; the server uses the session's role.
    r = c.post("/api/request", json={"text": "Be more careful this month", "role": "owner"}, headers=FM()).json()
    assert r["kind"] == "question" and r["route"]["question"]["kind"] == "role"


def test_old_owner_transaction_cannot_be_replayed(client):
    from apagent.chain import hardhat_keys
    c, api = client
    tx = c.get("/api/dial/tx", params={"bundle": "standard"}).json()["tx"]
    h = _wallet_send(api.S().chain, hardhat_keys()[0], tx)
    assert c.post("/api/dial", json={"bundle": "standard", "tx_hash": h}).json()["active"]
    # The same transaction passed off as a different setting is refused...
    assert "error" in c.post("/api/dial", json={"bundle": "most", "tx_hash": h}).json()
    # ...and so is using it a second time, or as an unpause.
    assert "error" in c.post("/api/dial", json={"bundle": "standard", "tx_hash": h}).json()
    assert "error" in c.post("/api/resume", json={"tx_hash": h}).json()
    st = c.get("/api/state").json()
    assert st["bundle"] == "standard" and st["consistency"]["ok"]


def test_paid_bill_cannot_be_rejected(client):
    c, _ = client
    paid = [b for b in c.get("/api/bills").json() if b["status"] == "paid"]
    assert paid
    out = c.post(f"/api/bills/{paid[0]['bill']}/reject").json()
    assert "error" in out
    assert c.get(f"/api/bills/{paid[0]['bill']}").json()["status"] == "paid"
