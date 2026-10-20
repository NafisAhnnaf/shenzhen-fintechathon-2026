"""Create the two demo sign-ins for the video and for judges: an owner and a finance manager in one company, each
with its signing wallet linked (the public Hardhat test keys, local chain only).

    .venv/bin/python scripts/demo_accounts.py [--url http://127.0.0.1:8000] [--company "Harbour Precision Demo"]

Run it with the app running (./run_local.sh, email sign-in). It is safe to run again: existing accounts sign in
instead of signing up, and an existing membership or wallet is kept.
"""
from __future__ import annotations

import argparse
import re
import sys

import httpx
from eth_account import Account
from eth_account.messages import encode_defunct

PASSWORD = "Harbour-Demo-Desk-2026"
PEOPLE = {
    # role: (name, email, Hardhat test key: account 0 is the owner, account 3 the finance manager)
    "owner": ("Demo Owner", "demo.owner@harbour-demo.test",
              "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"),
    "finance_manager": ("Demo Finance Manager", "demo.finance@harbour-demo.test",
                        "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"),
}


def session(url: str, name: str, email: str) -> httpx.Client:
    c = httpx.Client(base_url=url, timeout=120, headers={"Origin": url})
    r = c.post("/api/auth/sign-in/email", json={"email": email, "password": PASSWORD, "rememberMe": True})
    if r.status_code != 200:
        r = c.post("/api/auth/sign-up/email", json={"name": name, "email": email, "password": PASSWORD})
        r.raise_for_status()
    return c


def link_wallet(c: httpx.Client, key: str) -> str:
    me = c.get("/api/me").json()
    acct = Account.from_key(key)
    if (me.get("address") or "").lower() == acct.address.lower():
        return acct.address
    ch = c.post("/api/me/wallet/challenge", json={"address": acct.address})
    ch.raise_for_status()
    ch = ch.json()
    sig = acct.sign_message(encode_defunct(text=ch["message"])).signature.hex()
    c.post("/api/me/wallet", json={"nonce": ch["nonce"], "signature": "0x" + sig.removeprefix("0x")}).raise_for_status()
    return acct.address


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--company", default="Harbour Precision Demo")
    a = ap.parse_args()

    oname, oemail, okey = PEOPLE["owner"]
    owner = session(a.url, oname, oemail)
    orgs = owner.get("/api/auth/organization/list").json() or []
    org = next((o for o in orgs if o["name"] == a.company), None)
    if org is None:
        slug = re.sub(r"[^a-z0-9]+", "-", a.company.lower()).strip("-")
        r = owner.post("/api/auth/organization/create", json={"name": a.company, "slug": slug})
        r.raise_for_status()
        org = r.json()
    owner.post("/api/auth/organization/set-active", json={"organizationId": org["id"]}).raise_for_status()
    print("company", a.company, "- loading the sample records and deploying its contracts (about a minute)")
    owner.get("/api/me").raise_for_status()
    print("owner wallet", link_wallet(owner, okey))

    fname, femail, fkey = PEOPLE["finance_manager"]
    fm = session(a.url, fname, femail)
    if not any(o["id"] == org["id"] for o in (fm.get("/api/auth/organization/list").json() or [])):
        inv = owner.post("/api/auth/organization/invite-member",
                         json={"email": femail, "role": "finance_manager", "resend": True})
        inv.raise_for_status()
        fm.post("/api/auth/organization/accept-invitation", json={"invitationId": inv.json()["id"]}).raise_for_status()
    fm.post("/api/auth/organization/set-active", json={"organizationId": org["id"]}).raise_for_status()
    print("finance manager wallet", link_wallet(fm, fkey))

    for role, c in (("owner", owner), ("finance_manager", fm)):
        me = c.get("/api/me").json()
        print(f"{role:16} {me['email']:34} role={me['role']:16} signs_as={me.get('signs_as')}")
    print(f"\nPassword for both: {PASSWORD}\nOpen {a.url}/login")
    return 0


if __name__ == "__main__":
    sys.exit(main())
