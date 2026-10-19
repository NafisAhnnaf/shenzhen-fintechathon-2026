"""Who is signed in, read from the login service's tables (auth/, Better Auth on the same Postgres).

People sign in with email and password (and an authenticator code when they turned two-factor on). Each company is
a Better Auth organisation; the member row gives the person's role in it: owner, finance_manager, clerk or viewer.
The login service sets a signed cookie; this module checks the signature with the shared BETTER_AUTH_SECRET, then
reads the session, the person and their membership of the company the session has open. Nothing about the role
comes from the request.

A person who signs payments on chain links a wallet to their membership by signing a challenge with it
(`link_wallet`); the API then knows which address is theirs. The bank and the arbiter are outside the company and
keep signing in with their wallets only (apagent/auth.py).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote

# Better Auth role -> the API's role names (the deployment's names, as in apagent/auth.py).
ROLE = {"owner": "owner", "finance_manager": "approver", "clerk": "clerk", "viewer": "viewer"}
COOKIE_NAMES = ("__Secure-desk.session_token", "desk.session_token")
CACHE_TTL = 30  # seconds a looked-up session is trusted before the database is asked again

WALLETS = """
create table if not exists desk_wallets (
  company_id text not null,
  user_id    text not null,
  address    text not null,
  linked_at  timestamptz not null default now(),
  primary key (company_id, user_id)
);
create unique index if not exists desk_wallets_address on desk_wallets (company_id, lower(address));
"""


@dataclass
class Person:
    user_id: str
    name: str
    email: str
    company_id: Optional[str]  # the organisation the session has open; None until the person picks one
    company_name: Optional[str]
    role: str  # API role name: owner, approver, clerk, viewer; "none" without a company
    member_role: Optional[str]  # Better Auth role name
    wallet: Optional[str]
    two_factor: bool
    expires: float


def secret() -> str:
    return os.environ.get("BETTER_AUTH_SECRET", "")


def token_from_cookie(raw: Optional[str], key: Optional[str] = None) -> Optional[str]:
    """The session token from Better Auth's signed cookie value ("<token>.<base64 HMAC-SHA256>"), or None if the
    signature does not match."""
    if not raw:
        return None
    v = unquote(raw)
    token, _, sig = v.rpartition(".")
    if not token or not sig:
        return None
    want = base64.b64encode(hmac.new((key or secret()).encode(), token.encode(), hashlib.sha256).digest()).decode()
    return token if hmac.compare_digest(want, sig) else None


class Directory:
    """Reads sessions and memberships. One per process; it caches lookups briefly to spare the database."""

    def __init__(self, url: str):
        import psycopg

        self.url, self._psycopg = url, psycopg
        self._cache: dict[str, tuple[float, Optional[Person]]] = {}
        self._ready = False

    def connect(self):
        return self._psycopg.connect(self.url, connect_timeout=20)

    def migrate(self) -> None:
        if not self._ready:
            with self.connect() as c:
                c.execute(WALLETS)
            self._ready = True

    def person(self, cookies: dict) -> Optional[Person]:
        for name in COOKIE_NAMES:
            token = token_from_cookie(cookies.get(name))
            if token:
                return self.by_token(token)
        return None

    def by_token(self, token: str) -> Optional[Person]:
        now = time.time()
        hit = self._cache.get(token)
        if hit and hit[0] > now:
            p = hit[1]
            return p if p is None or p.expires > now else None
        p = self._lookup(token)
        self._cache[token] = (now + CACHE_TTL, p)
        if len(self._cache) > 5000:
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
        return p

    def forget(self, token: Optional[str] = None) -> None:
        if token is None:
            self._cache.clear()
        else:
            self._cache.pop(token, None)

    def _lookup(self, token: str) -> Optional[Person]:
        self.migrate()
        with self.connect() as c:
            row = c.execute(
                'select s."expiresAt", u.id, u.name, u.email, coalesce(u."twoFactorEnabled", false), '
                's."activeOrganizationId", o.name, m.role, w.address '
                'from "session" s join "user" u on u.id = s."userId" '
                'left join organization o on o.id = s."activeOrganizationId" '
                'left join member m on m."organizationId" = s."activeOrganizationId" and m."userId" = u.id '
                'left join desk_wallets w on w.company_id = s."activeOrganizationId" and w.user_id = u.id '
                "where s.token = %s", (token,)).fetchone()
        if row is None:
            return None
        expires, uid, name, email, tfa, org, org_name, mrole, wallet = row
        if expires.timestamp() <= time.time():
            return None
        if mrole is None:  # no open company, or no longer a member of it
            org = org_name = None
        return Person(uid, name, email, org, org_name, ROLE.get(mrole or "", "none"), mrole, wallet, bool(tfa),
                      expires.timestamp())

    def companies_of(self, user_id: str) -> list[dict]:
        with self.connect() as c:
            rows = c.execute('select o.id, o.name, o.slug, m.role from member m join organization o '
                             'on o.id = m."organizationId" where m."userId" = %s order by o.name', (user_id,)).fetchall()
        return [{"id": r[0], "name": r[1], "slug": r[2], "role": r[3]} for r in rows]

    def members(self, company_id: str) -> list[dict]:
        self.migrate()
        with self.connect() as c:
            rows = c.execute(
                'select u.id, u.name, u.email, m.role, coalesce(u."twoFactorEnabled", false), w.address, m."createdAt" '
                'from member m join "user" u on u.id = m."userId" '
                'left join desk_wallets w on w.company_id = m."organizationId" and w.user_id = u.id '
                'where m."organizationId" = %s order by m."createdAt"', (company_id,)).fetchall()
        return [{"user_id": r[0], "name": r[1], "email": r[2], "role": r[3], "two_factor": r[4], "wallet": r[5],
                 "joined": r[6].isoformat()} for r in rows]

    def wallet_holder(self, company_id: str, address: str) -> Optional[dict]:
        self.migrate()
        with self.connect() as c:
            row = c.execute('select w.user_id, u.name, m.role from desk_wallets w join "user" u on u.id = w.user_id '
                            'left join member m on m."organizationId" = w.company_id and m."userId" = w.user_id '
                            "where w.company_id = %s and lower(w.address) = lower(%s)", (company_id, address)).fetchone()
        return {"user_id": row[0], "name": row[1], "role": row[2]} if row else None

    def link_wallet(self, company_id: str, user_id: str, address: str) -> None:
        self.migrate()
        holder = self.wallet_holder(company_id, address)
        if holder and holder["user_id"] != user_id:
            raise PermissionError(f"that wallet is already linked to {holder['name']}")
        with self.connect() as c:
            c.execute("insert into desk_wallets (company_id, user_id, address) values (%s,%s,%s) "
                      "on conflict (company_id, user_id) do update set address = excluded.address, linked_at = now()",
                      (company_id, user_id, address))
        self.forget()

    def unlink_wallet(self, company_id: str, user_id: str) -> None:
        with self.connect() as c:
            c.execute("delete from desk_wallets where company_id = %s and user_id = %s", (company_id, user_id))
        self.forget()
