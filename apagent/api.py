"""HTTP API for the UI (FastAPI).

    NETWORK=localhost SIGNING=client uvicorn apagent.api:app --port 8000

SIGNING=client (default): the owner and the finance manager sign in their own wallets. The API returns EIP-712
typed data (approvals, receivables, claims) or unsigned transactions (settings, unpause, unfreeze) and accepts the
signature or the transaction hash back. The server holds only the agent, governor and underwriter-service keys.
SIGNING=server: the server holds every key (for scripted runs).

State is saved after every change and reloaded on start (see session.py). /api/admin/reset redeploys the contracts
and reloads the baseline ledger together.
"""
from __future__ import annotations

import contextvars
import functools
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import anyio
from web3 import Web3

from . import auth as A
from . import demo
from . import identity as I
from .config import DATA_DIR, SETTINGS
from .intake import BadDocument, ReaderUnavailable
from .intent import planner
from .session import DEFAULT_COMPANY, Session, reset as reset_session, store as state_store

NETWORK = os.environ.get("NETWORK", "localhost")
ERP = os.environ.get("ERP", "file")
SIGNING = os.environ.get("SIGNING", "client")
LOG_PATH = DATA_DIR / "state" / f"decision_log_{NETWORK}.jsonl"
# The RPC the browser wallet should use for this network.
RPC_PUBLIC = os.environ.get("RPC_PUBLIC", {"localhost": "http://127.0.0.1:8545", "fisco": "/api/rpc"}.get(NETWORK, "https://sepolia.base.org"))
# What the browser may ask the chain through /api/rpc: reads and already-signed transactions only.
RPC_ALLOWED = {"eth_chainId", "net_version", "eth_blockNumber", "eth_call", "eth_estimateGas", "eth_gasPrice",
               "eth_getTransactionCount", "eth_getTransactionReceipt", "eth_getTransactionByHash", "eth_getBlockByNumber",
               "eth_getCode", "eth_getBalance", "eth_sendRawTransaction"}

app = FastAPI(title="Bonded payables agent", version="0.5")
# The built app is served from this server (same origin). Only the Vite dev server needs CORS.
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["GET", "POST"], allow_headers=["content-type", "authorization"])

_lock = threading.RLock()
_sessions: dict[str, Session] = {}  # one desk per company, opened on first use
# The company of the person making the request; set by the `who` middleware before the endpoint runs.
_company: contextvars.ContextVar[str] = contextvars.ContextVar("company", default=DEFAULT_COMPANY)

# ------------------------------------------------------------------ sign-in and roles (spec X2)
# Company staff sign in with email and password through the login service (auth/, Better Auth); the API reads the
# session from the shared database (identity.py). The bank and the arbiter are outside the company and sign in with
# their wallets (auth.py). Without the login service (LOGIN=wallet, the default when there is no database), everyone
# signs in with a wallet and the deployment record decides the role, as before.
AUTH = A.Auth()
COOKIE = "desk_session"
LABEL = {"owner": "owner", "approver": "finance manager", "clerk": "accounts clerk", "underwriter": "bank",
         "arbiter": "arbiter", "viewer": "viewer"}
# The request router's names for the two people who can type requests.
ROUTER_ROLE = {"owner": "owner", "approver": "finance_manager"}
_directory: Optional[I.Directory] = None


def accounts() -> bool:
    """Email sign-in through the login service is on when the state is in Postgres and the shared secret is set."""
    mode = os.environ.get("LOGIN", "").lower()
    if mode in ("wallet", "accounts"):
        return mode == "accounts"
    return state_store() is not None and bool(I.secret())


def directory() -> Optional[I.Directory]:
    global _directory
    if not accounts():
        return None
    if _directory is None:
        _directory = I.Directory(os.environ["DATABASE_URL"])
    return _directory


def _resolve(request: Request) -> Optional[A.User]:
    if not A.enabled():
        return A.User("0x0000000000000000000000000000000000000000", "*", float("inf"))
    d = directory()
    if d is not None:
        p = d.person(request.cookies)
        if p is not None:
            return A.User(p.wallet or "", p.role, p.expires, company=p.company_id or "", user_id=p.user_id,
                          name=p.name, email=p.email, kind="account")
    h = request.headers.get("authorization", "")
    token = h[7:].strip() if h.lower().startswith("bearer ") else request.cookies.get(COOKIE)
    return AUTH.user(token)


@app.middleware("http")
async def who(request: Request, call_next):
    """Work out who is asking and which company's desk they use, before the endpoint runs."""
    path = request.url.path
    u = None
    if path.startswith("/api/") and not path.startswith("/api/auth/"):
        u = await anyio.to_thread.run_sync(_resolve, request)
    request.state.user = u
    if u is not None and u.company and state_store() is not None:
        _company.set(u.company)
    return await call_next(request)


def current_user(request: Request) -> A.User:
    u = getattr(request.state, "user", None)
    if u is None:
        raise HTTPException(401, "Sign in first")
    if u.role == "none":
        raise HTTPException(403, "Open a company first")
    return u


def need(*roles: str):
    def check(u: A.User = Depends(current_user)) -> A.User:
        if not u.can(*roles):
            raise HTTPException(403, f"Only the {' or '.join(LABEL[r] for r in roles)} can do this")
        return u
    return Depends(check)


def _demo_clock(u: A.User = Depends(current_user)) -> A.User:
    if NETWORK not in ("localhost", "fisco") and os.environ.get("DEMO_CONTROLS") != "on":
        raise HTTPException(403, "Demo controls are off on this network")
    if not u.can("owner"):
        raise HTTPException(403, "Only the owner can do this")
    return u


ANY = need("owner", "approver", "clerk", "underwriter", "arbiter", "viewer")
STAFF = need("owner", "approver")
INTAKE = need("owner", "approver", "clerk")  # bringing in invoices, emails, statements and ERP data
OWNER = need("owner")
FM = need("approver")
BANK = need("underwriter")
PROTECT = need("owner", "approver", "underwriter", "arbiter")
DEMO = Depends(_demo_clock)


def S() -> Session:
    """The desk of the company making this request."""
    cid = _company.get()
    s = _sessions.get(cid)
    if s is None:
        with _lock:
            s = _sessions.get(cid)
            if s is None:
                LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                s = _sessions[cid] = Session.open(NETWORK, log_path=LOG_PATH, signing=SIGNING, erp=ERP, company_id=cid)
    if s.clock() == "real" and s.led.today < time.strftime("%Y-%m-%d"):
        with _lock:
            if s.sync_clock():
                s.save()
    return s


def _ok(x):
    return json.loads(json.dumps(x, default=lambda o: ("0x" + o.hex()) if isinstance(o, (bytes, bytearray)) else (o.__dict__ if hasattr(o, "__dict__") else str(o))))


def mutating(fn):
    """Serialise changes and save state after each one."""
    @functools.wraps(fn)
    def wrap(*a, **kw):
        with _lock:
            try:
                out = fn(*a, **kw)
            except (BadDocument, ValueError, KeyError) as e:
                raise HTTPException(400, str(e))
            except ReaderUnavailable as e:
                raise HTTPException(503, str(e))
            S().save()
            return _ok(out)
    return wrap


def _sig(h: Optional[str]) -> Optional[bytes]:
    return bytes.fromhex(h.removeprefix("0x")) if h else None


def _err(out: dict):
    if isinstance(out, dict) and out.get("needs_signature"):
        raise HTTPException(428, out["error"])
    return out


class Req(BaseModel):
    text: str
    role: str = "owner"  # used only when AUTH=off; otherwise the signed-in wallet decides


class Challenge(BaseModel):
    address: str


class Login(BaseModel):
    nonce: str
    signature: str


class Choice(BaseModel):
    choice: str


class Approve(BaseModel):
    amount: Optional[float] = None
    signature: Optional[str] = None
    expiry: Optional[int] = None


class CaseConfirm(BaseModel):
    receivable_signature: Optional[str] = None
    claim_signature: Optional[str] = None
    expiry: Optional[int] = None


class TxHash(BaseModel):
    tx_hash: Optional[str] = None


class Dial(BaseModel):
    bundle: str
    mode: Optional[str] = None
    tx_hash: Optional[str] = None


class RawEmail(BaseModel):
    raw: str


# ------------------------------------------------------------------ overview
@app.get("/api/health")
def health():
    return {"ok": True, "network": NETWORK, "signing": SIGNING}


def _company_or_404(company: str) -> str:
    st = state_store()
    if st is None:
        return DEFAULT_COMPANY
    if st.company(company) is None and company != DEFAULT_COMPANY:
        raise HTTPException(404, "no such company")
    return company


@app.get("/api/public")
def public(company: str = DEFAULT_COMPANY):
    """What the sign-in page needs before anyone signs in: how people sign in, the chain for the wallet and the
    addresses of the outside signers."""
    _company.set(_company_or_404(company))
    s = S()
    return _ok({"network": NETWORK, "chain_id": s.chain.chain_id, "rpc": RPC_PUBLIC, "company": s.led.company,
                "roles": {k: v for k, v in s.chain.dep["roles"].items() if k in A.ROLE_ORDER}, "auth": A.enabled(),
                "login": "accounts" if accounts() else "wallet", "demo_date": s.led.today})


# ------------------------------------------------------------------ sign-in
# Email and password, two-factor, companies and invitations: the login service, reached through this server so the
# browser sees one origin and the cookie stays first-party.
@app.api_route("/api/auth/{path:path}", methods=["GET", "POST"], include_in_schema=False)
async def auth_service(path: str, request: Request):
    import httpx

    if not accounts():
        raise HTTPException(404, "email sign-in is not set up on this server")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length", "connection")}
    headers["x-forwarded-for"] = request.client.host if request.client else ""
    service = os.environ.get("AUTH_SERVICE_URL", "http://127.0.0.1:3001")
    async with httpx.AsyncClient(timeout=20) as c:
        try:
            r = await c.request(request.method, f"{service}/api/auth/{path}", params=request.query_params,
                                content=await request.body(), headers=headers)
        except httpx.HTTPError:
            raise HTTPException(503, "the login service is not running")
    if path.startswith(("sign-out", "organization/set-active", "organization/leave", "organization/remove-member",
                        "organization/update-member-role", "organization/accept-invitation")):
        d = directory()
        if d is not None:
            d.forget()  # the next request reads the new role or company
    out = Response(r.content, r.status_code, media_type=r.headers.get("content-type"))
    for v in r.headers.get_list("set-cookie"):
        out.headers.append("set-cookie", v)
    return out


class InternalMail(BaseModel):
    to: str
    subject: str
    text: str


@app.post("/api/internal/mail", include_in_schema=False)
def internal_mail(body: InternalMail, request: Request):
    """The login service's invitation, verification and reset mail, sent through the company mailbox. Only the login
    service, on this machine and holding the shared secret, may call it."""
    import hmac

    from . import mail

    host = request.client.host if request.client else ""
    token = request.headers.get("x-internal-token", "")
    if host not in ("127.0.0.1", "::1", "testclient") or not I.secret() or not hmac.compare_digest(token, I.secret()):
        raise HTTPException(403)
    if "\n" in body.to or "\r" in body.to or "\n" in body.subject or "\r" in body.subject:
        raise HTTPException(400, "bad header")
    return {"sent": mail.mailer(to_people=True).send(mail.build(body.to, body.subject[:200], body.text[:4000]))}


class WalletChallenge(BaseModel):
    address: str
    company: str = DEFAULT_COMPANY


@app.post("/api/wallet/challenge")
def wallet_challenge(body: WalletChallenge, request: Request):
    """Wallet sign-in for the bank and the arbiter (and for everyone when there is no login service)."""
    from web3 import Web3

    if not Web3.is_address(body.address):
        raise HTTPException(400, "not a wallet address")
    cid = _company_or_404(body.company)
    _company.set(cid)
    s = S()
    host = request.headers.get("host", "localhost")
    return AUTH.challenge(Web3.to_checksum_address(body.address), host, f"{request.url.scheme}://{host}",
                          s.chain.chain_id, s.led.company.replace(" (fictional)", ""), company_id=cid)


@app.post("/api/wallet/login")
def wallet_login(body: Login, response: Response):
    c = AUTH.challenges.get(body.nonce)
    if c is not None:
        _company.set(c[3])
    try:
        token, u = AUTH.login(body.nonce, body.signature, S().chain.dep["roles"],
                              allowed=("underwriter", "arbiter") if accounts() else None)
    except PermissionError as e:
        raise HTTPException(401, str(e))
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=A.SESSION_TTL)
    return {"address": u.address, "role": u.role, "label": LABEL.get(u.role, u.role), "token": token}


@app.post("/api/wallet/logout")
def wallet_logout(request: Request, response: Response):
    AUTH.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    """Who is signed in, their role in the open company, and the other companies they belong to."""
    u = getattr(request.state, "user", None)
    if u is None:
        raise HTTPException(401, "Sign in first")
    out = {"kind": u.kind, "address": u.address or None, "role": u.role, "label": LABEL.get(u.role, u.role),
           "name": u.name, "email": u.email, "company": u.company or None, "companies": []}
    d = directory()
    if u.kind == "account" and d is not None:
        out["companies"] = d.companies_of(u.user_id)
        p = d.person(request.cookies)
        out["two_factor"] = bool(p and p.two_factor)
        if u.company:
            dep = S().chain.dep["roles"]
            out["signs_as"] = A.role_of(u.address, dep) if u.address else None
            out["expected_wallet"] = dep.get(u.role) if u.role in ("owner", "approver") else None
    return out


@app.post("/api/me/wallet/challenge")
def link_challenge(body: Challenge, request: Request, u: A.User = Depends(current_user)):
    """A person links the wallet they sign payments with: the server asks them to sign a one-time message with it."""
    from web3 import Web3

    if u.kind != "account":
        raise HTTPException(400, "only people signed in with email link a wallet")
    if not Web3.is_address(body.address):
        raise HTTPException(400, "not a wallet address")
    s = S()
    host = request.headers.get("host", "localhost")
    return AUTH.challenge(Web3.to_checksum_address(body.address), host, f"{request.url.scheme}://{host}",
                          s.chain.chain_id, s.led.company, company_id=u.company,
                          statement=f"Link this wallet to {u.email} at {s.led.company.replace(' (fictional)', '')}.")


@app.post("/api/me/wallet")
def link_wallet(body: Login, u: A.User = Depends(current_user)):
    try:
        address, company = AUTH.verify(body.nonce, body.signature)
        if company != u.company:
            raise PermissionError("the request was for another company")
        directory().link_wallet(u.company, u.user_id, address)
    except PermissionError as e:
        raise HTTPException(400, str(e))
    return {"wallet": address, "signs_as": A.role_of(address, S().chain.dep["roles"])}


@app.post("/api/me/wallet/unlink")
def unlink_wallet(u: A.User = Depends(current_user)):
    if u.kind != "account":
        raise HTTPException(400, "only people signed in with email link a wallet")
    directory().unlink_wallet(u.company, u.user_id)
    return {"wallet": None}


@app.get("/api/team", dependencies=[ANY])
def team(u: A.User = Depends(current_user)):
    """The company's people and their roles; the on-chain signer addresses are shown next to whoever linked them."""
    d = directory()
    roles = S().chain.dep["roles"]
    people = d.members(u.company) if d is not None and u.company else []
    for p in people:
        p["signs_as"] = A.role_of(p["wallet"], roles) if p["wallet"] else None
    return {"members": people, "signers": {k: v for k, v in roles.items() if k in A.ROLE_ORDER}}


@app.get("/api/state", dependencies=[ANY])
def state():
    s = S()
    with _lock:
        ch = s.chain
        return _ok({
            "network": NETWORK, "signing": SIGNING, "today": s.led.today, "clock": s.clock(), "company": s.led.company,
            "cash_usd": s.led.cash_usd, "chain": ch.state(), "bundle": s.agent.gov.bundle_name, "money": s.agent.money,
            "contracts": ch.dep["contracts"], "roles": ch.dep["roles"], "server_holds": sorted(ch.keys),
            "chain_id": ch.chain_id, "rpc": RPC_PUBLIC,
            "suppliers": {sid: {"name": sp.name, "contact": sp.contact, "frozen": sp.frozen, "probation_left": sp.probation_left,
                                "rail": sp.rail} for sid, sp in s.led.suppliers.items() if sid in demo.DEMO_SUPPLIERS},
            "pending_settings": s.agent._pending_bundle,
            "erp": {**s.erp.describe(), "last_sync": s.erp_synced, "orders": len(s.led.pos), "suppliers": len(s.led.suppliers)},
            "explorer": "https://sepolia.basescan.org" if NETWORK == "baseSepolia" else None,
            "open_cases": [c.__dict__ for c in s.led.cases.values() if c.status == "open"],
            "consistency": s.consistency(),
        })


@app.post("/api/admin/reset", dependencies=[OWNER])
def admin_reset(confirm: str = ""):
    """Redeploy the contracts and reload the baseline ledger together. On a public network pass confirm=redeploy."""
    cid = _company.get()
    with _lock:
        try:
            s = _sessions[cid] = reset_session(NETWORK, LOG_PATH, allow_testnet=confirm == "redeploy", signing=SIGNING,
                                               erp=ERP, company_id=cid)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return _ok({"reset": True, "contracts": s.chain.dep["contracts"]})


# ------------------------------------------------------------------ ERP
@app.get("/api/erp", dependencies=[ANY])
def erp_status():
    s = S()
    return _ok({**s.erp.describe(), "last_sync": s.erp_synced, "orders": len(s.led.pos), "suppliers": len(s.led.suppliers),
                "receipts": len(s.led.receipts), "returns": len(s.led.returns)})


@app.post("/api/erp/sync", dependencies=[INTAKE])
@mutating
def erp_sync():
    """Pull the company records from the ERP now (it also happens before each new bill)."""
    return S().sync_erp() or {"source": "file", "note": "the demo file does not change"}


# ------------------------------------------------------------------ bills and documents
@app.get("/api/bills", dependencies=[ANY])
def bills(status: Optional[str] = None):
    s = S()
    with _lock:
        out = [s.agent.bill_card(b.bill_id) for b in s.led.bills.values()
               if not b.bill_id.startswith("H") and (status is None or b.status == status)]
    return _ok(sorted(out, key=lambda c: c["bill"], reverse=True))


@app.get("/api/bills/{bill_id}", dependencies=[ANY])
def bill(bill_id: str):
    s = S()
    if bill_id not in s.led.bills:
        raise HTTPException(404)
    return _ok(s.agent.bill_card(bill_id))


@app.post("/api/documents", dependencies=[INTAKE])
@mutating
def upload_document(file: UploadFile = File(...), process: bool = Form(True)):
    """A supplier document as received: .json e-invoice, .pdf, or a photo (.png/.jpg). PDFs and photos need the
    vision reader (VLM_API_KEY); without it the API answers 503 and nothing is recorded."""
    return S().ingest_file(file.filename or "upload", file.file.read(), process=process)


@app.get("/api/inbox", dependencies=[ANY])
def inbox():
    """Files waiting in the demo inbox folders (documents, emails, statements)."""
    s = S()
    used = {b.read.inv_no for b in s.led.bills.values() if not b.bill_id.startswith("H")}
    docs = [{"key": k, **d, "taken": d["inv_no"] in used} for k, d in s.docs.items()]
    emails = sorted(p.name for p in demo.INBOX_DIR.glob("*.eml") if not p.name.startswith("._"))
    stmts = sorted(p.name for p in demo.STATEMENTS_DIR.glob("*.csv") if not p.name.startswith("._"))
    return {"documents": docs, "emails": emails, "statements": stmts}


@app.get("/api/files/{kind}/{name}", dependencies=[ANY])
def file(kind: str, name: str):
    """Serve a demo inbox file (the PDF or e-invoice of a document, an email, a statement)."""
    base = {"documents": demo.DOCS_DIR, "inbox": demo.INBOX_DIR, "statements": demo.STATEMENTS_DIR}.get(kind)
    p = (base / name) if base else None
    if not p or not p.exists() or p.resolve().parent != base.resolve():
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/api/inbox/documents/{key}", dependencies=[INTAKE])
@mutating
def take_document(key: str, process: bool = True):
    """Take a document from the inbox folder through the same intake path as an upload."""
    if key not in S().docs:
        raise HTTPException(404)
    return S().ingest(key, process=process)


# ------------------------------------------------------------------ T2: approvals
@app.get("/api/bills/{bill_id}/approval", dependencies=[need("approver", "owner")])
def approval_request(bill_id: str, amount: Optional[float] = None):
    """EIP-712 PaymentApproval for the finance manager's wallet."""
    with _lock:
        return _ok(S().agent.approval_request(bill_id, amount))


@app.post("/api/bills/{bill_id}/approve", dependencies=[FM])
@mutating
def approve(bill_id: str, body: Approve):
    return _err(S().agent.approve(bill_id, body.amount, signature=_sig(body.signature), expiry=body.expiry))


class Cosign(BaseModel):
    signature: str


@app.post("/api/bills/{bill_id}/cosign", dependencies=[OWNER])
@mutating
def cosign(bill_id: str, body: Cosign):
    """The owner's second signature on an approved payment above the two-signature threshold (spec D4)."""
    return S().agent.cosign(bill_id, _sig(body.signature))


@app.post("/api/bills/{bill_id}/pay", dependencies=[STAFF])
@mutating
def pay_alone(bill_id: str):
    """Pay a bill the governor cleared for T1: the agent pays, the governor co-signs, the contract checks."""
    s = S()
    b = s.led.bills[bill_id]
    if b.status != "approved" or b.tier != "T1":
        raise HTTPException(400, "only a bill cleared to pay on its own can be paid this way")
    return s.agent.pay_t1(bill_id)


@app.post("/api/bills/{bill_id}/reject", dependencies=[STAFF])
@mutating
def reject(bill_id: str):
    return S().agent.reject(bill_id)


# ------------------------------------------------------------------ supplier queries and emails
@app.get("/api/queries", dependencies=[ANY])
def queries():
    return _ok(list(S().agent.queries.values()))


@app.post("/api/bills/{bill_id}/query", dependencies=[INTAKE])
@mutating
def draft_query(bill_id: str, topic: str = "price"):
    return S().agent.draft_query(bill_id, topic)


@app.post("/api/queries/{qid}/send", dependencies=[STAFF])
@mutating
def send_query(qid: str):
    return S().agent.send_query(qid)


@app.post("/api/emails", dependencies=[INTAKE])
@mutating
def receive_email(body: RawEmail):
    """An email as received (RFC 822 text with From/Subject). Replies quoting a query ID go to that query."""
    return S().agent.receive_email(body.raw)


@app.post("/api/emails/upload", dependencies=[INTAKE])
@mutating
def receive_email_file(file: UploadFile = File(...)):
    return S().agent.receive_email(file.file.read().decode("utf-8", errors="replace"))


@app.post("/api/inbox/emails/{name}", dependencies=[INTAKE])
@mutating
def take_email(name: str):
    p = demo.INBOX_DIR / name
    if not p.exists():
        raise HTTPException(404)
    return S().agent.receive_email(p.read_text())


# ------------------------------------------------------------------ email the agent sends and reads (spec V2, R4)
@app.get("/api/mail", dependencies=[ANY])
def mail_status():
    from . import mail
    return {"outgoing": mail.mailer().describe(), "incoming": mail.mailbox().describe(), "auto": mail.auto_email_on(),
            "auto_templates": sorted(mail.AUTO_TEMPLATES)}


@app.get("/api/outbox", dependencies=[ANY])
def outbox():
    return _ok(list(reversed(S().agent._emails())))


@app.post("/api/outbox/{email_id}/send", dependencies=[FM])
@mutating
def release_email(email_id: str):
    """The finance manager sends a drafted email that changes what we pay (policy S11)."""
    return S().agent.release_email(email_id)


@app.post("/api/mailbox/poll", dependencies=[INTAKE])
@mutating
def poll_mailbox():
    return S().poll_mailbox()


def _poll_forever(every: float) -> None:
    while True:
        time.sleep(every)
        try:
            with _lock:
                if S().poll_mailbox():
                    S().save()
        except Exception as e:  # noqa: BLE001 - keep polling; the error is in the journal
            S().agent.log.add("system", "mailbox_error", {"error": str(e)[:200]})


if float(os.environ.get("MAILBOX_POLL_SECONDS", "0") or 0) > 0:
    threading.Thread(target=_poll_forever, args=(float(os.environ["MAILBOX_POLL_SECONDS"]),), daemon=True).start()


# ------------------------------------------------------------------ public anchors (spec E6)
@app.get("/api/public-anchor", dependencies=[ANY])
def public_anchor():
    """The latest hourly anchor of every company's journal head on the public chain, and this company's proof."""
    from . import public_anchor as P
    st = state_store()
    if st is None:
        return {"enabled": False}
    out = P.proof_for(st, _company.get()) or {}
    net = os.environ.get("PUBLIC_ANCHOR_NETWORK", "")
    tx = (out.get("anchor") or {}).get("tx_hash")
    return _ok({"enabled": bool(net), "network": net, **out,
                "explorer": f"https://sepolia.basescan.org/tx/{tx}" if tx and net == "baseSepolia" else None})


if os.environ.get("PUBLIC_ANCHOR_NETWORK") and os.environ.get("STATE_STORE", "file").lower() == "postgres":
    from . import public_anchor as _P
    threading.Thread(target=_P.loop, args=(float(os.environ.get("PUBLIC_ANCHOR_SECONDS", "3600")),
                                           os.environ["PUBLIC_ANCHOR_NETWORK"]), daemon=True).start()


# ------------------------------------------------------------------ bank payment files and statements (spec M1, M2)
def _bank():
    from .bankfiles import BankDesk
    return BankDesk(S().agent)


def _company_account() -> str:
    # The company's own account the transfers are paid from (the sample company's is illustrative).
    return os.environ.get("COMPANY_BANK_ACCOUNT", "HSBC 400-123456-001")


@app.get("/api/bank-files", dependencies=[ANY])
def bank_files():
    """Approved bank transfers waiting for a file, the files made, what the bank has booked, and debits that match
    nothing the desk approved."""
    with _lock:
        return _ok({**_bank().summary(), "account": _company_account()})


@app.post("/api/bank-files")
@mutating
def make_bank_file(u: A.User = STAFF):
    """Write the waiting transfers into an ISO 20022 pain.001 file for the bank portal."""
    return _bank().make_file(ROUTER_ROLE.get(u.role, "owner") if u.role != "*" else "owner", _company_account())


@app.get("/api/bank-files/{file_id}.xml", dependencies=[STAFF])
def bank_file_xml(file_id: str):
    try:
        xml = _bank().file_xml(file_id, _company_account())
    except KeyError:
        raise HTTPException(404, "no such payment file")
    return Response(xml, media_type="application/xml",
                    headers={"content-disposition": f'attachment; filename="pain001-{file_id}.xml"'})


@app.post("/api/bank-statements", dependencies=[INTAKE])
@mutating
def bank_statement(file: UploadFile = File(...)):
    """The bank's camt.053 end-of-day statement: each debit is matched to a payment the desk approved."""
    from .bankfiles import BadStatement
    try:
        return _bank().import_statement("system", file.file.read())
    except BadStatement as e:
        raise HTTPException(400, str(e))


@app.post("/api/demo/bank-statement/{file_id}", dependencies=[DEMO])
@mutating
def demo_bank_statement(file_id: str, outside: bool = False):
    """Demo bank (local chain only): book a payment file the way a bank statement would, optionally with one debit
    nobody approved, then import it. A real bank sends this file itself."""
    from .bankfiles import camt053
    b = _bank()
    batch = next((x for x in b.batches if x["id"] == file_id), None)
    if batch is None:
        raise HTTPException(404, "no such payment file")
    day = S().led.today
    entries = [{"amount": p["amount"], "direction": "debit", "booked": day, "end_to_end": p["bill"],
                "counterparty": p["creditor"], "account": p["account"], "remittance": p["reference"],
                "bank_ref": f"BK{file_id}{i:03d}"} for i, p in enumerate(batch["payments"], 1)]
    if outside:
        sup = next(s for s in S().led.suppliers.values() if s.rail == "bank" and s.bank_account)
        entries.append({"amount": 4870.00, "direction": "debit", "booked": day, "end_to_end": "",
                        "counterparty": sup.name, "account": sup.bank_account, "remittance": "Manual transfer",
                        "bank_ref": f"BK{file_id}X01"})
    xml = camt053(_company_account(), entries, f"STMT-{file_id}", day)
    return b.import_statement("system", xml.encode())


# ------------------------------------------------------------------ statements, cases, claims
@app.post("/api/statements/{supplier_id}", dependencies=[INTAKE])
@mutating
def statement(supplier_id: str, file: UploadFile = File(...)):
    """A supplier statement (.csv: date,ref,kind,amount,against, or .json). Each unmatched line opens a case."""
    return [c.__dict__ for c in S().statement(supplier_id, file.filename or "statement.csv", file.file.read())]


@app.post("/api/inbox/statements/{name}", dependencies=[INTAKE])
@mutating
def take_statement(name: str, supplier_id: str):
    p = demo.STATEMENTS_DIR / name
    if not p.exists():
        raise HTTPException(404)
    return [c.__dict__ for c in S().statement(supplier_id, p.name, p.read_bytes())]


@app.get("/api/cases", dependencies=[ANY])
def cases():
    return _ok([c.__dict__ for c in S().led.cases.values()])


@app.get("/api/cases/{case_id}/signing", dependencies=[FM])
def case_signing(case_id: str):
    """EIP-712 messages the finance manager signs to confirm a missed credit (receivable, and claim if covered)."""
    with _lock:
        return _ok(S().agent.case_signing_request(case_id))


@app.post("/api/cases/{case_id}/confirm", dependencies=[FM])
@mutating
def confirm_case(case_id: str, body: CaseConfirm):
    return _err(S().agent.confirm_case(case_id, receivable_sig=_sig(body.receivable_signature),
                                       claim_sig=_sig(body.claim_signature), expiry=body.expiry))


@app.post("/api/claims/{bill_id}/execute", dependencies=[STAFF])
@mutating
def execute_claim(bill_id: str):
    return S().agent.execute_claim(bill_id)


# ------------------------------------------------------------------ requests and plans
# Typed requests can reach a paid model: a per-person rate and a per-company daily allowance (REQUEST_PER_MINUTE,
# REQUEST_PER_DAY). Counted in memory; a restart starts the counts again.
_request_times: dict[str, list[float]] = {}


def _request_allowance(u: A.User) -> None:
    now = time.time()
    per_min = int(os.environ.get("REQUEST_PER_MINUTE", "6"))
    per_day = int(os.environ.get("REQUEST_PER_DAY", "200"))
    me = f"{u.company}:{u.user_id or u.address}"
    mine = _request_times.setdefault(me, [])
    mine[:] = [t for t in mine if now - t < 60]
    co = _request_times.setdefault(f"{u.company}:*", [])
    co[:] = [t for t in co if now - t < 86400]
    if len(mine) >= per_min or len(co) >= per_day:
        S().agent.log.add(ROUTER_ROLE.get(u.role, u.role), "request_refused",
                          {"reason": "rate limit" if len(mine) >= per_min else "daily allowance"}, security=True)
        S().save()
        raise HTTPException(429, "Too many requests: wait a minute" if len(mine) >= per_min
                            else "Today's allowance of typed requests for this company is used up")
    mine.append(now)
    co.append(now)


@app.post("/api/request")
@mutating
def request(body: Req, u: A.User = STAFF):
    """The role comes from the signed-in person, not from the request body (spec X2)."""
    _request_allowance(u)
    return S().request(body.text, ROUTER_ROLE.get(u.role, body.role))


@app.post("/api/questions/{qid}/answer", dependencies=[STAFF])
@mutating
def answer(qid: str, body: Choice):
    return S().answer(qid, body.choice)


@app.get("/api/plans/{plan_id}", dependencies=[ANY])
def plan(plan_id: str):
    return _ok(S().plans[plan_id].to_json())


@app.post("/api/plans/{plan_id}/step", dependencies=[STAFF])
@mutating
def plan_step(plan_id: str):
    s = S()
    st = planner.step_next(s.agent, s.plans[plan_id])
    return {"step": st.__dict__ if st else None, "plan": s.plans[plan_id].to_json()}


@app.post("/api/plans/{plan_id}/run")
@mutating
def plan_run(plan_id: str, u: A.User = STAFF):
    return S().run(plan_id, actor=ROUTER_ROLE.get(u.role, "owner"))


@app.post("/api/plans/{plan_id}/cancel", dependencies=[STAFF])
@mutating
def plan_cancel(plan_id: str):
    s = S()
    return planner.cancel(s.agent, s.plans[plan_id]).to_json()


@app.get("/api/plans/{plan_id}/tx", dependencies=[OWNER])
def plan_tx(plan_id: str):
    """The owner's transaction for a plan that needs it (SET-DIAL settings, RESUME unpause)."""
    s = S()
    p = s.plans[plan_id]
    with _lock:
        if p.intent == "RESUME":
            return _ok(s.agent.owner_tx_request("unpause"))
        st = next(x for x in p.steps if x.kind == "settings")
        return _ok(s.agent.settings_tx_request(st.result["proposal"]))


@app.post("/api/plans/{plan_id}/sign", dependencies=[OWNER])
@mutating
def plan_sign(plan_id: str, body: TxHash):
    """The owner sent the plan's transaction from their wallet (tx_hash), or SIGNING=server sends it."""
    s = S()
    p = s.plans[plan_id]
    if p.intent == "RESUME":
        out = _err(s.agent.resume(tx_hash=body.tx_hash))
        p.steps[0].status, p.status = "done", "done"
        return out
    out = _err(s.sign_settings(plan_id, tx_hash=body.tx_hash))
    if out.get("active"):
        p.status = "done"
    return out


# ------------------------------------------------------------------ risk dial and settings
@app.get("/api/dial", dependencies=[ANY])
def dial():
    s = S()
    cal = s.agent.cal
    return _ok({"active": s.agent.gov.bundle_name, "bundles": [b.__dict__ for b in cal.bundles],
                "p_cap_usd": SETTINGS.p_cap_usd, "eps": cal.eps, "delta": cal.delta, "drift": dict(s.agent.gov.state.drift)})


@app.get("/api/dial/tx", dependencies=[OWNER])
def dial_tx(bundle: str, mode: Optional[str] = None):
    s = S()
    with _lock:
        return _ok(s.agent.settings_tx_request(s.agent.propose_bundle(bundle, mode)))


@app.post("/api/dial", dependencies=[OWNER])
@mutating
def set_dial(body: Dial):
    s = S()
    return _err(s.agent.apply_bundle(s.agent.propose_bundle(body.bundle, body.mode), tx_hash=body.tx_hash))


@app.post("/api/settings/{settings_id}/underwriter", dependencies=[BANK])
@mutating
def underwriter_approved(settings_id: int, body: TxHash):
    """The underwriter approved a bonded bundle from their own wallet."""
    return S().agent.underwriter_approve(settings_id, body.tx_hash)


# ------------------------------------------------------------------ security and owner actions
@app.get("/api/log", dependencies=[ANY])
def log(security: bool = False, limit: int = 200):
    s = S()
    lines = s.agent.log.security() if security else s.agent.log.lines
    return _ok([l.__dict__ for l in lines[-limit:]])


@app.post("/api/pause", dependencies=[PROTECT])
@mutating
def pause():
    return S().agent.pause_self("Owner pressed pause")


@app.get("/api/owner-tx/{action}", dependencies=[OWNER])
def owner_tx(action: str, supplier: Optional[str] = None):
    """Unsigned owner transaction: unpause, or unfreeze (supplier=...)."""
    with _lock:
        return _ok(S().agent.owner_tx_request(action, supplier=supplier))


@app.post("/api/resume", dependencies=[OWNER])
@mutating
def resume(body: TxHash):
    return _err(S().agent.resume(tx_hash=body.tx_hash))


@app.post("/api/payees/{supplier_id}/unfreeze", dependencies=[OWNER])
@mutating
def unfreeze(supplier_id: str, body: TxHash):
    return _err(S().agent.unfreeze_supplier(supplier_id, tx_hash=body.tx_hash))


@app.post("/api/anchor", dependencies=[STAFF])
@mutating
def anchor():
    return S().agent.anchor_day(int(time.time() // 86400))


# ------------------------------------------------------------------ screens of the desk (spec section 9)
class PayeeBody(BaseModel):
    wallet: str = ""
    rail: str = "token"
    tx_hash: Optional[str] = None
    callback: dict = {}
    new: Optional[dict] = None


class BankBody(BaseModel):
    tx_hash: str
    bill: Optional[str] = None
    amount: Optional[float] = None


class Timing(BaseModel):
    mode: str


class Cap(BaseModel):
    usd: float


@app.post("/api/settings/daily-cap", dependencies=[OWNER])
@mutating
def set_daily_cap(body: Cap):
    """The most the company pays in one day, all payments together (0 turns the ceiling off)."""
    return S().agent.set_daily_cap(body.usd)


@app.get("/api/payments", dependencies=[ANY])
def payments_register(start: Optional[str] = None, end: Optional[str] = None, by: Optional[str] = None,
                      supplier: Optional[str] = None):
    """Every payment in the period and who made it (spec E3). Dates are ISO (YYYY-MM-DD), inclusive."""
    from . import views
    with _lock:
        return _ok(views.payments(S(), start, end, by, supplier))


@app.get("/api/journal", dependencies=[ANY])
def journal(limit: int = 300, bill: Optional[str] = None, actor: Optional[str] = None, security: bool = False):
    from . import views
    with _lock:
        return _ok(views.journal(S(), limit, bill, actor, security))


@app.get("/api/journal/{index}/verify", dependencies=[ANY])
def verify_line(index: int):
    """Merkle proof that one journal line is in a root stored on-chain (spec E4)."""
    from . import views
    with _lock:
        try:
            return _ok(views.verify(S(), index))
        except KeyError as e:
            raise HTTPException(404, str(e))


@app.get("/api/disputes", dependencies=[ANY])
def disputes():
    from . import views
    with _lock:
        return _ok(views.disputes(S()))


@app.get("/api/schedule", dependencies=[ANY])
def schedule():
    from . import views
    with _lock:
        return _ok({"pay_timing": S().pay_timing, "daily_cap_usd": S().agent.daily_cap(), "rows": views.schedule(S())})


@app.post("/api/settings/pay-timing", dependencies=[OWNER])
@mutating
def pay_timing(body: Timing):
    return S().set_pay_timing(body.mode)


@app.post("/api/schedule/run", dependencies=[STAFF])
@mutating
def run_due():
    return S().run_due()


@app.get("/api/close", dependencies=[ANY])
def close_pack(month: Optional[str] = None):
    """The month in numbers (spec E5)."""
    from . import views
    with _lock:
        return _ok(views.close_pack(S(), month))


@app.get("/api/suppliers", dependencies=[ANY])
def suppliers():
    from . import views
    with _lock:
        return _ok(views.supplier_rows(S()))


@app.get("/api/payees/{supplier_id}/tx", dependencies=[OWNER])
def payee_tx(supplier_id: str, wallet: str = "", rail: str = "token"):
    with _lock:
        return _ok(S().agent.payee_tx_request(supplier_id, wallet, rail))


@app.post("/api/payees/{supplier_id}", dependencies=[OWNER])
@mutating
def set_payee(supplier_id: str, body: PayeeBody):
    """Add a supplier or change its payment details (spec X7): call-back first, owner's transaction, cool-down."""
    return _err(S().agent.set_payee(supplier_id, body.wallet, body.rail, body.callback, body.tx_hash, body.new))


class KeyBody(BaseModel):
    address: str = ""


@app.post("/api/suppliers/{supplier_id}/signing-key", dependencies=[OWNER])
@mutating
def signing_key(supplier_id: str, body: KeyBody):
    """Enrol the key a supplier signs its e-invoices with (spec C9)."""
    return S().agent.set_signing_key(supplier_id, body.address)


@app.get("/api/bank", dependencies=[ANY])
def bank_view():
    """The bank's console (spec E7)."""
    from . import views
    with _lock:
        return _ok(views.bank(S()))


@app.get("/api/bank/tx/{action}", dependencies=[need("underwriter", "arbiter")])
def bank_tx(action: str, bill: Optional[str] = None, amount: Optional[float] = None, settings: Optional[int] = None):
    with _lock:
        try:
            return _ok(S().agent.bank_tx_request(action, bill, amount, settings))
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.post("/api/bank/{action}", dependencies=[need("underwriter", "arbiter")])
@mutating
def bank_action(action: str, body: BankBody, u: A.User = Depends(current_user)):
    if action not in ("dispute", "resolve", "fund", "unpause"):
        raise HTTPException(404)
    if (action == "resolve") != (u.role in ("arbiter", "*")) and u.role != "*":
        raise HTTPException(403, "Only the arbiter settles a disputed claim; only the bank disputes, funds or unpauses")
    return S().agent.bank_action(action, body.tx_hash, body.bill, body.amount)


# ------------------------------------------------------------------ demo clock (local chain only)
@app.post("/api/demo/next-day", dependencies=[DEMO])
@mutating
def next_day():
    try:
        return {"today": S().next_day()}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/demo/advance", dependencies=[DEMO])
@mutating
def advance(seconds: int = 121):
    s = S()
    if NETWORK != "localhost":
        raise HTTPException(400, "time can only move on a local chain")
    s.chain.advance(seconds)
    return {"ok": True}


# ------------------------------------------------------------------ chain relay for the browser wallet (FISCO)
def _raw_tx_to(raw_hex: str) -> Optional[str]:
    """The `to` address of a signed raw transaction (legacy or EIP-2718 typed)."""
    import rlp
    raw = bytes.fromhex(raw_hex.removeprefix("0x"))
    if raw and raw[0] < 0x7f:  # typed: type byte, then the RLP payload
        fields = rlp.decode(raw[1:])
        to = fields[5] if raw[0] == 2 else fields[4] if raw[0] == 1 else None
    else:
        to = rlp.decode(raw)[3]
    return Web3.to_checksum_address(to) if to else None


@app.post("/api/rpc")
def rpc_relay(body: dict, request: Request):
    """Forward a JSON-RPC call from the browser wallet to the connected chain. Reads for anyone (the sign-in page
    needs the chain); a signed transaction only from someone signed in, and only to their own company's contracts:
    on a demo chain the test keys are public, so the relay is what keeps one company's contracts from another."""
    if body.get("method") not in RPC_ALLOWED:
        return {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "method not allowed"}}
    if body["method"] == "eth_sendRawTransaction":
        u = getattr(request.state, "user", None)
        if u is None or u.role == "none":
            return {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32001, "message": "sign in first"}}
        try:
            to = _raw_tx_to((body.get("params") or [""])[0])
        except Exception:  # noqa: BLE001 - not a transaction
            return {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32602, "message": "not a signed transaction"}}
        mine = {Web3.to_checksum_address(a) for a in S().chain.dep["contracts"].values()}
        if to not in mine:
            S().agent.log.add(u.role, "rpc_refused", {"to": to}, security=True)
            return {"jsonrpc": "2.0", "id": body.get("id"),
                    "error": {"code": -32003, "message": "transactions go only to your company's contracts"}}
    r = S().chain.w3.provider.make_request(body["method"], body.get("params", []))
    return {"jsonrpc": "2.0", "id": body.get("id"), **({"error": r["error"]} if "error" in r else {"result": r.get("result")})}


# ------------------------------------------------------------------ transaction lookup (FISCO has no public explorer)
@app.get("/api/tx/{tx_hash}", dependencies=[ANY])
def tx_lookup(tx_hash: str):
    """The receipt of a transaction on the connected chain, with our contracts' events decoded."""
    from web3.logs import DISCARD

    ch = S().chain
    try:
        rc = ch.w3.eth.get_transaction_receipt(tx_hash)
        tx = ch.w3.eth.get_transaction(tx_hash)
    except Exception as e:
        raise HTTPException(404, f"no such transaction on {NETWORK}: {e}")
    names = {v.lower(): k for k, v in ch.dep["contracts"].items()}
    events = []
    for c in (ch.vault, ch.pool, ch.anchor):
        for ev in c.events:
            for log in ev().process_receipt(rc, errors=DISCARD):
                events.append({"contract": names.get(log["address"].lower(), log["address"]), "event": log["event"],
                               "args": {k: ("0x" + v.hex() if isinstance(v, bytes) else v) for k, v in log["args"].items()}})
    return _ok({"network": NETWORK, "chain_id": ch.chain_id, "hash": tx_hash, "status": "success" if rc.status == 1 else "reverted",
                "block": rc.blockNumber, "from": tx["from"], "to": names.get(str(tx["to"]).lower(), tx["to"]),
                "gas_used": rc.gasUsed, "events": events})


# ------------------------------------------------------------------ market data
@app.get("/api/market/{series}", dependencies=[ANY])
def market_series(series: str, start: str = "2024-01", end: str = "2025-12"):
    """A public price series (World Bank, monthly, $/mt) for the fair-price chart."""
    from . import market

    s = market.series().get(series)
    if s is None:
        raise HTTPException(404, f"no series {series}")
    return {"series": series, "source": market.SOURCE, "points": [[k, v] for k, v in sorted(s.items()) if start <= k <= end]}


class DraftPO(BaseModel):
    item: str
    option: str
    months: int = 2


class OfferBody(BaseModel):
    bill: str


@app.get("/api/offers", dependencies=[ANY])
def offers():
    """Spec P4: bills worth paying early for a discount, and the offers made."""
    with _lock:
        ag = S().agent
        return _ok({"candidates": ag.offer_candidates(), "offers": list(ag.offers.values())})


@app.post("/api/offers", dependencies=[STAFF])
@mutating
def make_offer(body: OfferBody):
    return S().agent.make_offer(body.bill)


class BudgetBody(BaseModel):
    centre: str
    monthly_usd: Optional[float] = None


@app.get("/api/budgets", dependencies=[ANY])
def budgets_view(month: Optional[str] = None):
    from . import budgets
    s = S()
    with _lock:
        return _ok({"month": month or s.led.today[:7], "rows": budgets.overview(s.led, s.agent.budgets, month)})


@app.post("/api/budgets", dependencies=[OWNER])
@mutating
def set_budget(body: BudgetBody):
    """Set (or clear, with no amount) a cost centre's monthly budget (spec D5)."""
    return S().agent.set_budget(body.centre, body.monthly_usd)


@app.get("/api/notifications")
def notifications(u: A.User = ANY):
    from . import views
    with _lock:
        return _ok(views.notifications(S(), u.role))


@app.get("/api/market-watch", dependencies=[ANY])
def market_watch():
    """Spec C10: a 90% price range per indexed material, alert signals, and a buy-ahead comparison on alert."""
    from . import marketwatch
    with _lock:
        return _ok({"cards": marketwatch.watch(S().led), "drafts": S().agent.__dict__.get("po_drafts", [])})


@app.get("/api/market-watch/{item}/buy-ahead", dependencies=[ANY])
def buy_ahead(item: str, months: int = 2):
    from . import marketwatch
    s = S()
    with _lock:
        mat = s.led.materials.get(item)
        if not mat or not mat.series:
            raise HTTPException(404, "no public index for this material")
        need = next(c["need_t_per_month"] for c in marketwatch.watch(s.led) if c["item"] == item)
        return _ok(marketwatch.buy_ahead(mat.series, need, months=months,
                                         cash_available=s.led.cash_usd - s.agent.cfg.cash_floor_usd))


@app.post("/api/market-watch/drafts", dependencies=[STAFF])
@mutating
def draft_po(body: DraftPO):
    return S().agent.draft_po(body.item, body.option, body.months)


@app.get("/api/market-watch/backtest", dependencies=[ANY])
def market_backtest():
    from . import marketwatch
    return marketwatch.backtest()


# ------------------------------------------------------------------ results
@app.get("/api/results", dependencies=[ANY])
def results():
    out = {}
    for name in ("ac8", "capital", "fair", "red"):
        p = DATA_DIR.parent / "results" / f"{name}.json"
        if p.exists():
            out[name] = json.loads(p.read_text())
    return out


@app.get("/api/evidence", dependencies=[ANY])
def evidence():
    p = DATA_DIR.parent / "evidence" / f"evidence_{NETWORK}.json"
    return json.loads(p.read_text()) if p.exists() else {}


# ------------------------------------------------------------------ the web app (built files), if present
_WEB = DATA_DIR.parent / "web" / "dist"
if _WEB.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=_WEB / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str):
        f = _WEB / path
        return FileResponse(f if path and f.is_file() and f.resolve().is_relative_to(_WEB.resolve()) else _WEB / "index.html")
