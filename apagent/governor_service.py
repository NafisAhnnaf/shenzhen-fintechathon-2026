"""The governor as its own service (spec X5).

    NETWORK=localhost .venv/bin/uvicorn apagent.governor_service:app --port 8001
    # then start the API with GOVERNOR_URL=http://127.0.0.1:8001

The contract pays a bill alone only with the governor's signature. If the governor key sat in the agent's process,
whoever took over that process would hold both keys. Here the governor runs apart, with its own key and its own
copy of the company records. It does not trust the agent's decision: for every request it re-reads the bill,
re-runs the checker, the injection flag and the risk score, checks the caps itself, and signs only if it reaches
"pay alone" for the same amount and the same input hash. Each bill is signed at most once.

What it cannot see: bills the finance manager paid (they are not its business) and the agent's free-text context.
Disagreement is safe: the bill goes to the finance manager.
"""
from __future__ import annotations

import os
import pickle
import threading
from dataclasses import asdict
from datetime import date
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from . import checker, injection
from .audit import input_hash
from .chain import Chain
from .config import DATA_DIR, SETTINGS
from .domain import Bill, InvLine, Read
from .erp import make_adapter
from .governor import Governor
from .risk.calibrate import Calibration

NETWORK = os.environ.get("NETWORK", "localhost")
TOKEN = os.environ.get("GOVERNOR_TOKEN", "")  # optional shared secret with the agent server
STATE = DATA_DIR / "state" / f"governor-{NETWORK}.pkl"


def read_from_json(d: dict) -> Read:
    return Read(**{**d, "lines": [InvLine(**l) for l in d["lines"]]})


def read_to_json(r: Read) -> dict:
    return asdict(r)


def bill_input(bill: Bill) -> dict:
    """The same fields the agent hashes (Agent.bill_input); the signature binds them."""
    r = bill.read
    return {"inv_no": r.inv_no, "supplier": bill.supplier_id, "po": r.po_id, "total": r.total, "credit": r.credit,
            "lines": [(l.item, l.qty, l.price) for l in r.lines], "amount": bill.amount_usd}


class GovernorService:
    def __init__(self, network: str = NETWORK, erp: Optional[str] = None):
        from .session import ledger_for

        self.network = network
        self.erp = make_adapter(erp)
        self.led = ledger_for(self.erp)
        self.gov = Governor(Calibration.load(), SETTINGS)
        self.signed: dict[str, dict] = {}  # bill_id -> what was signed
        self.vault: Optional[str] = None
        self.chain: Optional[Chain] = None

    # ------------------------------------------------------------------ persistence
    @staticmethod
    def open(network: str = NETWORK) -> "GovernorService":
        chain = Chain(network, held_roles={"governor"})
        vault = chain.dep["contracts"]["vault"]
        if STATE.exists():
            s: GovernorService = pickle.loads(STATE.read_bytes())
            if s.vault == vault:  # same deployment: keep what was signed
                s.chain = s.gov.chain = chain
                return s
        s = GovernorService(network)
        s.vault, s.chain, s.gov.chain = vault, chain, chain
        return s

    def save(self) -> None:
        chain, self.chain, self.gov.chain = self.chain, None, None
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(self))
            tmp.replace(STATE)
        finally:
            self.chain = self.gov.chain = chain

    # ------------------------------------------------------------------ the decision
    def sign(self, bill_id: str, read: Read, source: str, amount_usd: float, settings_id: int, ih: str,
             today: str) -> dict:
        if bill_id in self.signed:
            raise PermissionError("this bill was already signed once")
        if date.fromisoformat(today) > date.fromisoformat(self.led.today):
            self.led.today = today  # the demo clock only moves forward
        bill = Bill(bill_id=bill_id, received=self.led.today, source=source, read=read)
        res = checker.check(self.led, bill, SETTINGS)
        bill.supplier_id = res.supplier.id if res.supplier else None
        bill.amount_usd = res.amount.value
        inj = injection.assess(read.raw_text)["p"]
        st = self.chain.state()
        if st["settings_id"] != settings_id:
            raise PermissionError("the agent asked for a settings bundle that is not active on-chain")
        d = self.gov.decide(self.led, bill, res, inj, self.led.today, st)
        if d.tier != "T1":
            raise PermissionError("; ".join(d.reasons) or f"decision is {d.tier}")
        if round(d.amount, 2) != round(amount_usd, 2):
            raise PermissionError(f"amount {amount_usd:,.2f} differs from the checked amount {d.amount:,.2f}")
        own_hash = "0x" + input_hash(bill_input(bill)).hex().removeprefix("0x")
        if own_hash.lower() != ih.lower():
            raise PermissionError("the input hash does not match the bill")
        self.gov.sign(d, bill_id, bill.supplier_id, settings_id, bytes.fromhex(own_hash[2:]))
        self.gov.record_t1(bill.supplier_id, d.amount, self.led.today)
        bill.status, bill.tier = "paid", "T1"  # so a resent copy is caught as a duplicate
        self.led.bills[bill_id] = bill
        self.signed[bill_id] = {"supplier": bill.supplier_id, "amount": d.amount, "settings_id": settings_id,
                                "expiry": d.expiry, "input_hash": own_hash, "score": d.score, "cutoff": d.cutoff,
                                "day": self.led.today}
        return {"signature": "0x" + d.signature.hex().removeprefix("0x"), "expiry": d.expiry,
                "settings_id": settings_id, "score": d.score, "cutoff": d.cutoff}

    def outcome(self, supplier_id: str, group: str, loss_ratio: float) -> dict:
        """A confirmed mistake: the cut-off for the group tightens and the supplier goes on probation.
        Both only make the governor stricter, so the agent may report them without a signature."""
        self.gov.outcome(group, max(0.0, min(1.0, loss_ratio)))
        sup = self.led.suppliers.get(supplier_id)
        if sup:
            sup.probation_left = max(sup.probation_left, SETTINGS.probation_bills)
        return {"drift": dict(self.gov.state.drift), "probation_left": sup.probation_left if sup else None}


# ------------------------------------------------------------------ HTTP
app = FastAPI(title="Governor", version="1")
_lock = threading.Lock()
_svc: Optional[GovernorService] = None


def svc() -> GovernorService:
    global _svc
    if _svc is None:
        _svc = GovernorService.open()
    return _svc


def _check_token(x_governor_token: Optional[str]) -> None:
    if TOKEN and x_governor_token != TOKEN:
        raise HTTPException(401, "wrong governor token")


class SignReq(BaseModel):
    bill_id: str
    read: dict
    source: str
    amount_usd: float
    settings_id: int
    input_hash: str
    today: str


class OutcomeReq(BaseModel):
    supplier_id: str
    group: str
    loss_ratio: float


@app.get("/health")
def health():
    s = svc()
    return {"ok": True, "network": s.network, "governor": s.chain.role_address("governor"), "signed": len(s.signed)}


@app.post("/sign")
def sign(body: SignReq, x_governor_token: Optional[str] = Header(None)):
    _check_token(x_governor_token)
    with _lock:
        s = svc()
        try:
            out = s.sign(body.bill_id, read_from_json(body.read), body.source, body.amount_usd, body.settings_id,
                         body.input_hash, body.today)
        except PermissionError as e:
            raise HTTPException(409, str(e))
        s.save()
        return out


@app.post("/outcome")
def outcome(body: OutcomeReq, x_governor_token: Optional[str] = Header(None)):
    _check_token(x_governor_token)
    with _lock:
        s = svc()
        out = s.outcome(body.supplier_id, body.group, body.loss_ratio)
        s.save()
        return out


@app.get("/signed")
def signed():
    """Everything this governor has signed: an independent record to compare with the agent's journal."""
    return svc().signed


@app.post("/reset")
def reset(x_governor_token: Optional[str] = Header(None)):
    """Demo reset after a redeploy: start again from the company records (local chains only)."""
    _check_token(x_governor_token)
    global _svc
    with _lock:
        if NETWORK not in ("localhost", "fisco"):
            raise HTTPException(400, "reset only on a local chain")
        STATE.unlink(missing_ok=True)
        _svc = GovernorService.open()
        _svc.save()
        return {"ok": True}
