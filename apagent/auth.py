"""Sign-in with the wallet and role checks for the API (spec X2).

The browser asks for a challenge, the person signs it in their wallet (EIP-4361 "Sign-In with Ethereum" text,
personal_sign), and the server issues a session for the address that signed. The role comes from the deployment
record, never from the request: the owner's address is the owner, the approver's address is the finance manager,
and so on. Anyone else may sign in as a viewer.

Sessions live in memory: a restart signs everyone out, which is fine for a desk with a handful of people.
AUTH=off turns the checks off for scripted runs and offline tests.
"""
from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_defunct

NONCE_TTL = 300  # seconds to sign the challenge
SESSION_TTL = 8 * 3600  # one working day

# Deployment role -> API role. The API uses the deployment's names; the UI shows the glossary names.
ROLE_ORDER = ("owner", "approver", "underwriter", "arbiter")


@dataclass
class User:
    address: str
    role: str  # owner, approver, underwriter, arbiter, viewer; "*" when AUTH=off
    expires: float

    def can(self, *roles: str) -> bool:
        return self.role == "*" or self.role in roles


def enabled() -> bool:
    return os.environ.get("AUTH", "on").lower() not in ("off", "0", "false", "no")


def role_of(address: str, roles: dict) -> str:
    a = address.lower()
    for r in ROLE_ORDER:
        if (roles.get(r) or "").lower() == a:
            return r
    return "viewer"


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Auth:
    def __init__(self):
        self.challenges: dict[str, tuple[str, float, str]] = {}  # nonce -> (address, expires, message)
        self.sessions: dict[str, User] = {}

    def challenge(self, address: str, domain: str, uri: str, chain_id: int, company: str) -> dict:
        now = time.time()
        self.challenges = {n: c for n, c in self.challenges.items() if c[1] > now}
        nonce = secrets.token_hex(12)
        msg = (f"{domain} wants you to sign in with your Ethereum account:\n{address}\n\n"
               f"Sign in to the {company} payables desk.\n\n"
               f"URI: {uri}\nVersion: 1\nChain ID: {chain_id}\nNonce: {nonce}\n"
               f"Issued At: {_iso(now)}\nExpiration Time: {_iso(now + NONCE_TTL)}")
        self.challenges[nonce] = (address.lower(), now + NONCE_TTL, msg)
        return {"nonce": nonce, "message": msg}

    def login(self, nonce: str, signature: str, roles: dict) -> tuple[str, User]:
        c = self.challenges.pop(nonce, None)  # a challenge can be used once
        if c is None or c[1] < time.time():
            raise PermissionError("the sign-in request expired; try again")
        address, _, msg = c
        try:
            signer = Account.recover_message(encode_defunct(text=msg), signature=signature)
        except Exception as e:  # noqa: BLE001 - malformed signature
            raise PermissionError(f"the signature could not be read: {str(e)[:80]}")
        if signer.lower() != address:
            raise PermissionError("the signature is not from the address that asked to sign in")
        token = secrets.token_urlsafe(32)
        user = User(signer, role_of(signer, roles), time.time() + SESSION_TTL)
        self.sessions[token] = user
        return token, user

    def user(self, token: Optional[str]) -> Optional[User]:
        if not token:
            return None
        u = self.sessions.get(token)
        if u is None or u.expires < time.time():
            self.sessions.pop(token, None)
            return None
        return u

    def logout(self, token: Optional[str]) -> None:
        self.sessions.pop(token or "", None)
