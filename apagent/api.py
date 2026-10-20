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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

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

app = FastAPI(title="Bonded payables agent", version="0.4")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_lock = threading.RLock()
_session: Optional[Session] = None


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
    role: str = "owner"


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


@app.get("/api/state")
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


@app.post("/api/admin/reset")
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
@app.get("/api/erp")
def erp_status():
    s = S()
    return _ok({**s.erp.describe(), "last_sync": s.erp_synced, "orders": len(s.led.pos), "suppliers": len(s.led.suppliers),
                "receipts": len(s.led.receipts), "returns": len(s.led.returns)})


@app.post("/api/erp/sync")
@mutating
def erp_sync():
    """Pull the company records from the ERP now (it also happens before each new bill)."""
    return S().sync_erp() or {"source": "file", "note": "the demo file does not change"}


# ------------------------------------------------------------------ bills and documents
@app.get("/api/bills")
def bills(status: Optional[str] = None):
    s = S()
    with _lock:
        out = [s.agent.bill_card(b.bill_id) for b in s.led.bills.values()
               if not b.bill_id.startswith("H") and (status is None or b.status == status)]
    return _ok(sorted(out, key=lambda c: c["bill"], reverse=True))


@app.get("/api/bills/{bill_id}")
def bill(bill_id: str):
    s = S()
    if bill_id not in s.led.bills:
        raise HTTPException(404)
    return _ok(s.agent.bill_card(bill_id))


@app.post("/api/documents")
@mutating
def upload_document(file: UploadFile = File(...), process: bool = Form(True)):
    """A supplier document as received: .json e-invoice, .pdf, or a photo (.png/.jpg). PDFs and photos need the
    vision reader (VLM_API_KEY); without it the API answers 503 and nothing is recorded."""
    import httpx

    try:
        return S().ingest_file(file.filename or "upload", file.file.read(), process=process)
    except (httpx.HTTPStatusError, httpx.TransportError) as e:
        raise HTTPException(503, reader_error(e))


@app.post("/api/documents/stream")
def upload_document_stream(file: UploadFile = File(...)):
    """The same upload, reported as it happens (server-sent events): received, reading, read (every field the
    reader extracted, with confidences and the page's other text), checking, then decided or error."""
    import httpx

    from .intake import read_document
    from .reader import VLMReader

    name, data = file.filename or "upload", file.file.read()

    def ev(stage: str, **d) -> str:
        return f"data: {json.dumps({'stage': stage, **_ok(d)})}\n\n"

    def gen():
        yield ev("received", file=name, bytes=len(data))
        is_json = name.lower().endswith(".json")
        yield ev("reading", reader="e-invoice parser" if is_json else VLMReader().model)
        t0 = time.time()
        try:
            read, kind = read_document(name, data)
        except (BadDocument, ReaderUnavailable) as e:
            yield ev("error", message=str(e))
            return
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            yield ev("error", message=reader_error(e))
            return
        yield ev("read", kind=kind, seconds=round(time.time() - t0, 1), reader=read.reader or "e-invoice parser", read=read_json(read))
        yield ev("checking")
        with _lock:
            try:
                out = S().ingest_read(name, data, read, kind)
                S().save()
            except Exception as e:  # noqa: BLE001 - reported to the page, not swallowed
                yield ev("error", message=str(e))
                return
        yield ev("decided", result=out)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/bills/{bill_id}/read")
def bill_read(bill_id: str):
    """What the reader extracted from this bill's document. Every value here is what the supplier's document says."""
    s = S()
    if bill_id not in s.led.bills:
        raise HTTPException(404)
    return read_json(s.led.bills[bill_id].read)


def reader_error(e) -> str:
    """A plain message for a failed call to the vision model. Nothing is recorded when the read fails."""
    code = getattr(getattr(e, "response", None), "status_code", None)
    if code == 429:
        return "The vision model's quota is used up (429). Nothing was recorded. Wait for the quota to reset or set another VLM_MODEL."
    if code in (401, 403):
        return f"The vision model refused the API key ({code}). Nothing was recorded. Check VLM_API_KEY."
    return f"The vision reader is busy or unreachable ({code or type(e).__name__}). Nothing was recorded. Try again in a moment."


def read_json(r) -> dict:
    return {"inv_no": r.inv_no, "supplier_name": r.supplier_name, "tax_id": r.tax_id, "sender_domain": r.sender_domain,
            "po_id": r.po_id, "date": r.date, "due_date": r.due_date, "terms": r.terms, "currency": r.currency,
            "lines": [{"item": l.item, "desc": l.desc, "unit": l.unit, "qty": l.qty, "price": l.price} for l in r.lines],
            "credit": r.credit, "total": r.total, "bank_account": r.bank_account, "confidence": r.confidence,
            "text": r.raw_text, "reader": r.reader}


@app.get("/api/inbox")
def inbox():
    """Files waiting in the demo inbox folders (documents, emails, statements)."""
    s = S()
    used = {b.read.inv_no for b in s.led.bills.values() if not b.bill_id.startswith("H")}
    docs = [{"key": k, **d, "taken": d["inv_no"] in used} for k, d in s.docs.items()]
    emails = sorted(p.name for p in demo.INBOX_DIR.glob("*.eml") if not p.name.startswith("._"))
    stmts = sorted(p.name for p in demo.STATEMENTS_DIR.glob("*.csv") if not p.name.startswith("._"))
    return {"documents": docs, "emails": emails, "statements": stmts}


@app.get("/api/files/{kind}/{name}")
def file(kind: str, name: str):
    """Serve a demo inbox file (the PDF or e-invoice of a document, an email, a statement)."""
    base = {"documents": demo.DOCS_DIR, "inbox": demo.INBOX_DIR, "statements": demo.STATEMENTS_DIR}.get(kind)
    p = (base / name) if base else None
    if not p or not p.exists() or p.resolve().parent != base.resolve():
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/api/inbox/documents/{key}")
@mutating
def take_document(key: str, process: bool = True):
    """Take a document from the inbox folder through the same intake path as an upload."""
    if key not in S().docs:
        raise HTTPException(404)
    return S().ingest(key, process=process)


# ------------------------------------------------------------------ T2: approvals
@app.get("/api/bills/{bill_id}/approval")
def approval_request(bill_id: str, amount: Optional[float] = None):
    """EIP-712 PaymentApproval for the finance manager's wallet."""
    with _lock:
        return _ok(S().agent.approval_request(bill_id, amount))


@app.post("/api/bills/{bill_id}/approve")
@mutating
def approve(bill_id: str, body: Approve):
    return _err(S().agent.approve(bill_id, body.amount, signature=_sig(body.signature), expiry=body.expiry))


@app.post("/api/bills/{bill_id}/pay")
@mutating
def pay_alone(bill_id: str):
    """Pay a bill the governor cleared for T1: the agent pays, the governor co-signs, the contract checks."""
    s = S()
    b = s.led.bills[bill_id]
    if b.status != "approved" or b.tier != "T1":
        raise HTTPException(400, "only a bill cleared to pay on its own can be paid this way")
    return s.agent.pay_t1(bill_id)


@app.post("/api/bills/{bill_id}/reject")
@mutating
def reject(bill_id: str):
    return S().agent.reject(bill_id)


# ------------------------------------------------------------------ supplier queries and emails
@app.get("/api/queries")
def queries():
    return _ok(list(S().agent.queries.values()))


@app.post("/api/bills/{bill_id}/query")
@mutating
def draft_query(bill_id: str, topic: str = "price"):
    return S().agent.draft_query(bill_id, topic)


@app.post("/api/queries/{qid}/send")
@mutating
def send_query(qid: str):
    return S().agent.send_query(qid)


@app.post("/api/emails")
@mutating
def receive_email(body: RawEmail):
    """An email as received (RFC 822 text with From/Subject). Replies quoting a query ID go to that query."""
    return S().agent.receive_email(body.raw)


@app.post("/api/emails/upload")
@mutating
def receive_email_file(file: UploadFile = File(...)):
    return S().agent.receive_email(file.file.read().decode("utf-8", errors="replace"))


@app.post("/api/inbox/emails/{name}")
@mutating
def take_email(name: str):
    p = demo.INBOX_DIR / name
    if not p.exists():
        raise HTTPException(404)
    return S().agent.receive_email(p.read_text())


# ------------------------------------------------------------------ statements, cases, claims
@app.post("/api/statements/{supplier_id}")
@mutating
def statement(supplier_id: str, file: UploadFile = File(...)):
    """A supplier statement (.csv: date,ref,kind,amount,against, or .json). Each unmatched line opens a case."""
    return [c.__dict__ for c in S().statement(supplier_id, file.filename or "statement.csv", file.file.read())]


@app.post("/api/inbox/statements/{name}")
@mutating
def take_statement(name: str, supplier_id: str):
    p = demo.STATEMENTS_DIR / name
    if not p.exists():
        raise HTTPException(404)
    return [c.__dict__ for c in S().statement(supplier_id, p.name, p.read_bytes())]


@app.get("/api/cases")
def cases():
    return _ok([c.__dict__ for c in S().led.cases.values()])


@app.get("/api/cases/{case_id}/signing")
def case_signing(case_id: str):
    """EIP-712 messages the finance manager signs to confirm a missed credit (receivable, and claim if covered)."""
    with _lock:
        return _ok(S().agent.case_signing_request(case_id))


@app.post("/api/cases/{case_id}/confirm")
@mutating
def confirm_case(case_id: str, body: CaseConfirm):
    return _err(S().agent.confirm_case(case_id, receivable_sig=_sig(body.receivable_signature),
                                       claim_sig=_sig(body.claim_signature), expiry=body.expiry))


@app.post("/api/claims/{bill_id}/execute")
@mutating
def execute_claim(bill_id: str):
    return S().agent.execute_claim(bill_id)


# ------------------------------------------------------------------ requests and plans
@app.post("/api/request")
@mutating
def request(body: Req):
    return S().request(body.text, body.role)


@app.post("/api/questions/{qid}/answer")
@mutating
def answer(qid: str, body: Choice):
    return S().answer(qid, body.choice)


@app.get("/api/plans/{plan_id}")
def plan(plan_id: str):
    return _ok(S().plans[plan_id].to_json())


@app.post("/api/plans/{plan_id}/step")
@mutating
def plan_step(plan_id: str):
    s = S()
    st = planner.step_next(s.agent, s.plans[plan_id])
    return {"step": st.__dict__ if st else None, "plan": s.plans[plan_id].to_json()}


@app.post("/api/plans/{plan_id}/run")
@mutating
def plan_run(plan_id: str):
    return S().run(plan_id)


@app.post("/api/plans/{plan_id}/cancel")
@mutating
def plan_cancel(plan_id: str):
    s = S()
    return planner.cancel(s.agent, s.plans[plan_id]).to_json()


@app.get("/api/plans/{plan_id}/tx")
def plan_tx(plan_id: str):
    """The owner's transaction for a plan that needs it (SET-DIAL settings, RESUME unpause)."""
    s = S()
    p = s.plans[plan_id]
    with _lock:
        if p.intent == "RESUME":
            return _ok(s.agent.owner_tx_request("unpause"))
        st = next(x for x in p.steps if x.kind == "settings")
        return _ok(s.agent.settings_tx_request(st.result["proposal"]))


@app.post("/api/plans/{plan_id}/sign")
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
@app.get("/api/dial")
def dial():
    s = S()
    cal = s.agent.cal
    return _ok({"active": s.agent.gov.bundle_name, "bundles": [b.__dict__ for b in cal.bundles],
                "p_cap_usd": SETTINGS.p_cap_usd, "eps": cal.eps, "delta": cal.delta, "drift": dict(s.agent.gov.state.drift)})


@app.get("/api/dial/tx")
def dial_tx(bundle: str, mode: Optional[str] = None):
    s = S()
    with _lock:
        return _ok(s.agent.settings_tx_request(s.agent.propose_bundle(bundle, mode)))


@app.post("/api/dial")
@mutating
def set_dial(body: Dial):
    s = S()
    return _err(s.agent.apply_bundle(s.agent.propose_bundle(body.bundle, body.mode), tx_hash=body.tx_hash))


@app.post("/api/settings/{settings_id}/underwriter")
@mutating
def underwriter_approved(settings_id: int, body: TxHash):
    """The underwriter approved a bonded bundle from their own wallet."""
    return S().agent.underwriter_approve(settings_id, body.tx_hash)


# ------------------------------------------------------------------ security and owner actions
@app.get("/api/log")
def log(security: bool = False, limit: int = 200):
    s = S()
    lines = s.agent.log.security() if security else s.agent.log.lines
    return _ok([l.__dict__ for l in lines[-limit:]])


@app.post("/api/naive/attack")
@mutating
def naive_attack(doc: str = "t07_poisoned"):
    """Split screen: the naive wallet follows the document's text; our agent processes the same document."""
    s = S()
    read = demo.read_from_doc(s.docs[doc])
    n = naive.run(s.chain, read.raw_text, read.total)
    return {"naive": n, "ours": s.ingest(doc)}


@app.post("/api/pause")
@mutating
def pause():
    return S().agent.pause_self("Owner pressed pause")


@app.get("/api/owner-tx/{action}")
def owner_tx(action: str, supplier: Optional[str] = None):
    """Unsigned owner transaction: unpause, or unfreeze (supplier=...)."""
    with _lock:
        return _ok(S().agent.owner_tx_request(action, supplier=supplier))


@app.post("/api/resume")
@mutating
def resume(body: TxHash):
    return _err(S().agent.resume(tx_hash=body.tx_hash))


@app.post("/api/payees/{supplier_id}/unfreeze")
@mutating
def unfreeze(supplier_id: str, body: TxHash):
    return _err(S().agent.unfreeze_supplier(supplier_id, tx_hash=body.tx_hash))


@app.post("/api/anchor")
@mutating
def anchor():
    return S().agent.anchor_day(int(time.time() // 86400))


# ------------------------------------------------------------------ demo clock (local chain only)
@app.post("/api/demo/next-day")
@mutating
def next_day():
    try:
        return {"today": S().next_day()}
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.post("/api/demo/advance")
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
@app.get("/api/tx/{tx_hash}")
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
@app.get("/api/market/{series}")
def market_series(series: str, start: str = "2024-01", end: str = "2025-12"):
    """A public price series (World Bank, monthly, $/mt) for the fair-price chart."""
    from . import market

    s = market.series().get(series)
    if s is None:
        raise HTTPException(404, f"no series {series}")
    return {"series": series, "source": market.SOURCE, "points": [[k, v] for k, v in sorted(s.items()) if start <= k <= end]}


# ------------------------------------------------------------------ results
@app.get("/api/results")
def results():
    out = {}
    for name in ("ac8", "capital", "fair", "red"):
        p = DATA_DIR.parent / "results" / f"{name}.json"
        if p.exists():
            out[name] = json.loads(p.read_text())
    return out


@app.get("/api/evidence")
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
