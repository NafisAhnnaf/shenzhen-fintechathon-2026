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

from . import auth as A
from . import demo, naive
from .config import DATA_DIR, SETTINGS
from .intake import BadDocument, ReaderUnavailable
from .intent import planner
from .session import Session, reset as reset_session

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
_session: Optional[Session] = None

# ------------------------------------------------------------------ sign-in and roles (spec X2)
AUTH = A.Auth()
COOKIE = "desk_session"
LABEL = {"owner": "owner", "approver": "finance manager", "underwriter": "bank", "arbiter": "arbiter", "viewer": "viewer"}
# The request router's names for the two people who can type requests.
ROUTER_ROLE = {"owner": "owner", "approver": "finance_manager"}


def current_user(request: Request) -> A.User:
    if not A.enabled():
        return A.User("0x0000000000000000000000000000000000000000", "*", float("inf"))
    h = request.headers.get("authorization", "")
    token = h[7:].strip() if h.lower().startswith("bearer ") else request.cookies.get(COOKIE)
    u = AUTH.user(token)
    if u is None:
        raise HTTPException(401, "Sign in with your wallet first")
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


ANY = need("owner", "approver", "underwriter", "arbiter", "viewer")
STAFF = need("owner", "approver")
OWNER = need("owner")
FM = need("approver")
BANK = need("underwriter")
PROTECT = need("owner", "approver", "underwriter", "arbiter")
DEMO = Depends(_demo_clock)


def S() -> Session:
    global _session
    if _session is None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _session = Session.open(NETWORK, log_path=LOG_PATH, signing=SIGNING, erp=ERP)
    return _session


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


@app.get("/api/public")
def public():
    """What the sign-in page needs before anyone signs in: the chain for the wallet and the role addresses."""
    s = S()
    return _ok({"network": NETWORK, "chain_id": s.chain.chain_id, "rpc": RPC_PUBLIC, "company": s.led.company,
                "roles": {k: v for k, v in s.chain.dep["roles"].items() if k in A.ROLE_ORDER}, "auth": A.enabled(),
                "demo_date": s.led.today})


# ------------------------------------------------------------------ sign-in
@app.post("/api/auth/challenge")
def auth_challenge(body: Challenge, request: Request):
    from web3 import Web3

    if not Web3.is_address(body.address):
        raise HTTPException(400, "not a wallet address")
    s = S()
    host = request.headers.get("host", "localhost")
    return AUTH.challenge(Web3.to_checksum_address(body.address), host, f"{request.url.scheme}://{host}",
                          s.chain.chain_id, s.led.company.replace(" (fictional)", ""))


@app.post("/api/auth/login")
def auth_login(body: Login, response: Response):
    try:
        token, u = AUTH.login(body.nonce, body.signature, S().chain.dep["roles"])
    except PermissionError as e:
        raise HTTPException(401, str(e))
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=A.SESSION_TTL)
    return {"address": u.address, "role": u.role, "label": LABEL.get(u.role, u.role), "token": token}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    AUTH.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(u: A.User = Depends(current_user)):
    return {"address": u.address, "role": u.role, "label": LABEL.get(u.role, u.role)}


@app.get("/api/state", dependencies=[ANY])
def state():
    s = S()
    with _lock:
        ch = s.chain
        return _ok({
            "network": NETWORK, "signing": SIGNING, "today": s.led.today, "company": s.led.company,
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
    global _session
    with _lock:
        try:
            _session = reset_session(NETWORK, LOG_PATH, allow_testnet=confirm == "redeploy", signing=SIGNING, erp=ERP)
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        return _ok({"reset": True, "contracts": _session.chain.dep["contracts"]})


# ------------------------------------------------------------------ ERP
@app.get("/api/erp", dependencies=[ANY])
def erp_status():
    s = S()
    return _ok({**s.erp.describe(), "last_sync": s.erp_synced, "orders": len(s.led.pos), "suppliers": len(s.led.suppliers),
                "receipts": len(s.led.receipts), "returns": len(s.led.returns)})


@app.post("/api/erp/sync", dependencies=[STAFF])
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


@app.post("/api/documents", dependencies=[STAFF])
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


@app.post("/api/inbox/documents/{key}", dependencies=[STAFF])
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


@app.post("/api/bills/{bill_id}/query", dependencies=[STAFF])
@mutating
def draft_query(bill_id: str, topic: str = "price"):
    return S().agent.draft_query(bill_id, topic)


@app.post("/api/queries/{qid}/send", dependencies=[STAFF])
@mutating
def send_query(qid: str):
    return S().agent.send_query(qid)


@app.post("/api/emails", dependencies=[STAFF])
@mutating
def receive_email(body: RawEmail):
    """An email as received (RFC 822 text with From/Subject). Replies quoting a query ID go to that query."""
    return S().agent.receive_email(body.raw)


@app.post("/api/emails/upload", dependencies=[STAFF])
@mutating
def receive_email_file(file: UploadFile = File(...)):
    return S().agent.receive_email(file.file.read().decode("utf-8", errors="replace"))


@app.post("/api/inbox/emails/{name}", dependencies=[STAFF])
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


@app.post("/api/mailbox/poll", dependencies=[STAFF])
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


# ------------------------------------------------------------------ statements, cases, claims
@app.post("/api/statements/{supplier_id}", dependencies=[STAFF])
@mutating
def statement(supplier_id: str, file: UploadFile = File(...)):
    """A supplier statement (.csv: date,ref,kind,amount,against, or .json). Each unmatched line opens a case."""
    return [c.__dict__ for c in S().statement(supplier_id, file.filename or "statement.csv", file.file.read())]


@app.post("/api/inbox/statements/{name}", dependencies=[STAFF])
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
@app.post("/api/request")
@mutating
def request(body: Req, u: A.User = STAFF):
    """The role comes from the signed-in wallet, not from the request body (spec X2)."""
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


@app.post("/api/naive/attack", dependencies=[STAFF])
@mutating
def naive_attack(doc: str = "t07_poisoned"):
    """Split screen: the naive wallet follows the document's text; our agent processes the same document."""
    s = S()
    read = demo.read_from_doc(s.docs[doc])
    n = naive.run(s.chain, read.raw_text, read.total)
    return {"naive": n, "ours": s.ingest(doc)}


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


class Attack(BaseModel):
    text: str


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
        return _ok({"pay_timing": S().pay_timing, "rows": views.schedule(S())})


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


@app.post("/api/try-attack", dependencies=[STAFF])
@mutating
def try_attack(body: Attack):
    """Any text on a routine bill, given to both agents (spec X8). Ours pays nothing; the naive wallet may."""
    if not body.text.strip():
        raise HTTPException(400, "Type the text to put on the bill")
    return S().try_attack(body.text)


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
@app.post("/api/rpc")
def rpc_relay(body: dict):
    """Forward a JSON-RPC call from the browser wallet to the connected chain. Reads and signed transactions only."""
    if body.get("method") not in RPC_ALLOWED:
        return {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601, "message": "method not allowed"}}
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
    for c in (ch.vault, ch.pool, ch.anchor, ch.naive):
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
