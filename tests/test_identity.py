"""Email sign-in through the login service (auth/, Better Auth) and what the API does with it: the role comes from
the membership row, each company has its own desk, a clerk cannot approve, a wallet is linked by signing, and the
bank keeps its wallet sign-in. Runs the real login service against a local Postgres, never the production one."""
import base64
import hashlib
import hmac
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from apagent import identity as I

ROOT = Path(__file__).resolve().parents[1]
URL = os.environ.get("TEST_AUTH_DATABASE_URL", "postgresql://apagent@/apagent_auth_test?host=/tmp&port=5544")
SECRET = "test-auth-secret-" + "x" * 32
PORT = 3191
ORIGIN = "http://testserver"


def test_cookie_signature_is_checked():
    sig = base64.b64encode(hmac.new(b"k", b"tok123", hashlib.sha256).digest()).decode()
    assert I.token_from_cookie(f"tok123.{sig}", "k") == "tok123"
    assert I.token_from_cookie(f"tok123.{sig}".replace("+", "%2B").replace("/", "%2F").replace("=", "%3D"), "k") == "tok123"
    assert I.token_from_cookie(f"tok124.{sig}", "k") is None
    assert I.token_from_cookie(f"tok123.{sig}", "other") is None
    assert I.token_from_cookie("tok123", "k") is None and I.token_from_cookie(None, "k") is None


def _ready() -> bool:
    try:
        import psycopg
        with psycopg.connect(URL, connect_timeout=3):
            pass
    except Exception:
        return False
    from tests.test_e2e_chain import _node_up
    return bool(shutil.which("node")) and (ROOT / "auth" / "node_modules").exists() and _node_up()


@pytest.fixture(scope="module")
def desk():
    if not _ready():
        pytest.skip("needs the local test Postgres, node with auth/ installed, and the local hardhat node")
    import psycopg
    with psycopg.connect(URL, autocommit=True) as c:
        c.execute("drop schema public cascade")
        c.execute("create schema public")
    env = {**os.environ, "DATABASE_URL": URL, "BETTER_AUTH_SECRET": SECRET, "PUBLIC_URL": ORIGIN,
           "AUTH_PORT": str(PORT), "SMTP_HOST": "", "AUTH_RATE_LIMIT": "off"}
    subprocess.run(["node", "server.mjs", "--migrate"], cwd=ROOT / "auth", env=env, check=True, capture_output=True)
    proc = subprocess.Popen(["node", "server.mjs"], cwd=ROOT / "auth", env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    import httpx
    for _ in range(50):
        try:
            if httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    mp = pytest.MonkeyPatch()
    for k, v in {"STATE_STORE": "postgres", "DATABASE_URL": URL, "BETTER_AUTH_SECRET": SECRET, "LOGIN": "accounts",
                 "AUTH": "on", "AUTH_SERVICE_URL": f"http://127.0.0.1:{PORT}", "SIGNING": "client"}.items():
        mp.setenv(k, v)
    from apagent import session as S
    mp.setattr(S, "_STORE", None)
    from apagent import api
    api._sessions.clear()
    mp.setattr(api, "_directory", None)
    yield api, proc
    api._sessions.clear()
    mp.undo()
    proc.terminate()
    proc.wait(5)


def _client(api):
    from fastapi.testclient import TestClient
    return TestClient(api.app, headers={"origin": ORIGIN})


def _sign_up(api, email, name):
    c = _client(api)
    r = c.post("/api/auth/sign-up/email", json={"email": email, "password": "a long passphrase 42!", "name": name})
    assert r.status_code == 200, r.text
    return c


def test_people_sign_in_with_email_and_get_the_role_of_their_membership(desk):
    api, _ = desk
    owner = _sign_up(api, "owner@harbour.test", "Mei Owner")
    me = owner.get("/api/me").json()
    assert me["kind"] == "account" and me["role"] == "none" and me["company"] is None
    assert owner.get("/api/state").status_code == 403  # no company open yet
    org = owner.post("/api/auth/organization/create", json={"name": "Harbour Precision", "slug": "harbour"}).json()
    owner.post("/api/auth/organization/set-active", json={"organizationId": org["id"]})
    me = owner.get("/api/me").json()
    assert me["role"] == "owner" and me["company"] == org["id"] and me["companies"][0]["role"] == "owner"
    st = owner.get("/api/state").json()
    assert st["consistency"]["ok"]

    # the owner invites a clerk; the clerk signs up, accepts and opens the company
    inv = owner.post("/api/auth/organization/invite-member", json={"email": "clerk@harbour.test", "role": "clerk"})
    assert inv.status_code == 200, inv.text
    clerk = _sign_up(api, "clerk@harbour.test", "Kit Clerk")
    assert clerk.post("/api/auth/organization/accept-invitation", json={"invitationId": inv.json()["id"]}).status_code == 200
    clerk.post("/api/auth/organization/set-active", json={"organizationId": org["id"]})
    assert clerk.get("/api/me").json()["role"] == "clerk"
    assert clerk.get("/api/bills").status_code == 200
    assert clerk.post("/api/inbox/documents/t13_net30").status_code == 200  # a clerk brings invoices in
    assert clerk.post("/api/admin/reset").status_code == 403
    assert clerk.post("/api/bills/X/approve", json={}).status_code == 403
    assert clerk.post("/api/request", json={"text": "pay everything"}).status_code == 403
    team = owner.get("/api/team").json()
    assert {m["email"]: m["role"] for m in team["members"]} == {"owner@harbour.test": "owner", "clerk@harbour.test": "clerk"}

    # the clerk cannot raise their own role
    r = clerk.post("/api/auth/organization/update-member-role", json={"memberId": "x", "role": "owner"})
    assert r.status_code >= 400


def test_each_company_has_its_own_desk(desk):
    api, _ = desk
    a = _sign_up(api, "a@one.test", "A")
    b = _sign_up(api, "b@two.test", "B")
    for c, slug in ((a, "one"), (b, "two")):
        org = c.post("/api/auth/organization/create", json={"name": slug.title(), "slug": slug}).json()
        c.post("/api/auth/organization/set-active", json={"organizationId": org["id"]})
    a.post("/api/inbox/documents/t01_routine")
    count = lambda c: sum(1 for x in c.get("/api/bills").json() if not str(x.get("id", "")).startswith("H"))
    assert count(a) == count(b) + 1
    # b cannot open a's company by naming it
    a_id = a.get("/api/me").json()["company"]
    assert b.post("/api/auth/organization/set-active", json={"organizationId": a_id}).status_code >= 400
    assert b.get("/api/me").json()["company"] != a_id


def test_wallet_linking_and_outside_signers(desk):
    api, _ = desk
    from eth_account import Account
    from eth_account.messages import encode_defunct

    c = _sign_up(api, "fm@three.test", "Fen Manager")
    org = c.post("/api/auth/organization/create", json={"name": "Three", "slug": "three"}).json()
    c.post("/api/auth/organization/set-active", json={"organizationId": org["id"]})
    acct = Account.create()
    ch = c.post("/api/me/wallet/challenge", json={"address": acct.address}).json()
    assert "Link this wallet to fm@three.test" in ch["message"]
    sig = Account.sign_message(encode_defunct(text=ch["message"]), acct.key).signature.hex()
    r = c.post("/api/me/wallet", json={"nonce": ch["nonce"], "signature": sig})
    assert r.status_code == 200 and r.json()["wallet"] == acct.address
    assert c.get("/api/me").json()["address"] == acct.address
    # the same signature cannot be used twice
    assert c.post("/api/me/wallet", json={"nonce": ch["nonce"], "signature": sig}).status_code == 400

    # company staff cannot use wallet sign-in; the bank can, for the company it names
    from apagent.chain import hardhat_keys
    keys = {Account.from_key(k).address.lower(): k for k in hardhat_keys()}
    roles = c.get("/api/team").json()["signers"]

    def wallet_login(role):
        anon = _client(api)
        ch = anon.post("/api/wallet/challenge", json={"address": roles[role], "company": org["id"]}).json()
        sig = Account.sign_message(encode_defunct(text=ch["message"]), keys[roles[role].lower()]).signature.hex()
        return anon, anon.post("/api/wallet/login", json={"nonce": ch["nonce"], "signature": sig})

    _, r = wallet_login("owner")
    assert r.status_code == 401 and "email" in r.json()["detail"]
    bank, r = wallet_login("underwriter")
    assert r.status_code == 200 and r.json()["role"] == "underwriter"
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    assert bank.get("/api/bank", headers=headers).status_code == 200
    assert bank.post("/api/admin/reset", headers=headers).status_code == 403
    assert _client(api).post("/api/wallet/challenge", json={"address": roles["owner"], "company": "nope"}).status_code == 404


def test_a_forged_cookie_is_refused(desk):
    api, _ = desk
    c = _client(api)
    c.cookies.set("desk.session_token", "made-up-token.c2lnbmF0dXJl")
    assert c.get("/api/me").status_code == 401


def test_login_service_mail_needs_the_shared_secret(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from apagent import api, mail
    monkeypatch.setenv("BETTER_AUTH_SECRET", SECRET)
    monkeypatch.setattr(mail, "OUTBOX_DIR", tmp_path)
    c = TestClient(api.app)
    body = {"to": "new@harbour.test", "subject": "You are invited", "text": "Accept: http://x/accept-invitation/1"}
    assert c.post("/api/internal/mail", json=body).status_code == 403
    assert c.post("/api/internal/mail", json=body, headers={"x-internal-token": "wrong"}).status_code == 403
    bad = {**body, "to": "a@b.test\nBcc: c@d.test"}
    assert c.post("/api/internal/mail", json=bad, headers={"x-internal-token": SECRET}).status_code == 400
    assert c.post("/api/internal/mail", json=body, headers={"x-internal-token": SECRET}).status_code == 200
    assert len(list(tmp_path.glob("*.eml"))) == 1
