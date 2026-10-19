"""One running system: ledger + agent + chain + request router + plans. Used by the API and the task runner.

State is saved to data/state/<network>.pkl after every change and reloaded on start, but only if it belongs to
the contracts currently deployed (same vault address). consistency() compares the ledger with the chain.
"""
from __future__ import annotations

import pickle
import shutil
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from . import demo
from .agent import Agent
from .audit import AuditLog
from .chain import DEMO_CLOCK, Chain
from .config import CHAIN_DIR, DATA_DIR
from .domain import Ledger
from .erp import ErpAdapter, make_adapter, merge_into
from .intake import parse_statement, read_document
from .intent import planner
from .intent.router import Route, Router
from .risk.calibrate import Calibration

STATE_DIR = DATA_DIR / "state"
# Who signs what. client: the owner and the finance manager sign in their own wallets; the server holds the agent,
# governor and underwriter-service keys. server: the server holds every key (scripted task runs and tests).
SERVICE_ROLES = {"agent", "governor", "underwriter"}


def held_roles(signing: str) -> Optional[set]:
    return None if signing == "server" else SERVICE_ROLES


def ledger_for(erp: ErpAdapter) -> Ledger:
    """The agent's working ledger. With the demo file it is the file itself (records plus settled history). With a
    real ERP it starts empty apart from the company settings (name, demo date, material-to-index map) and the
    company records come from the ERP."""
    base = Ledger.load(demo.DEMO_DIR / "ledger.json")
    if erp.name == "file":
        return base
    led = Ledger(company=base.company, today=base.today, cash_usd=base.cash_usd, materials=base.materials)
    merge_into(led, erp.fetch())
    return led


class Session:
    def __init__(self, network: Optional[str] = "localhost", decider=None, log_path: Optional[Path] = None,
                 signing: str = "server", erp: Optional[str] = None):
        self.network = network
        self.signing = signing
        self.erp: ErpAdapter = make_adapter(erp)
        self.led = ledger_for(self.erp)
        self.erp_synced = time.time()
        self.chain = Chain(network, held_roles=held_roles(signing)) if network else None
        self.agent = Agent(self.led, Calibration.load(), self.chain, log=AuditLog(log_path))
        self.agent.erp = self.erp
        self.router = Router.load(decider)
        self.plans: dict[str, planner.Plan] = {}
        self.pending: dict[str, Route] = {}  # a question waiting for the user's answer
        self.docs = demo.load_docs()
        self.uploads = 0
        self.anchored: set[int] = set()  # ledger days whose decision-log root is on-chain

    # ------------------------------------------------------------------ persistence
    @staticmethod
    def state_file(network: str, erp: str = "file") -> Path:
        return STATE_DIR / f"{network}-{erp}.pkl"

    def save(self) -> None:
        if not self.network:
            return
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        chain, self.chain, self.agent.chain, self.agent.gov.chain = self.chain, None, None, None
        try:
            blob = pickle.dumps({"vault": chain.dep["contracts"]["vault"] if chain else None, "session": self})
        finally:
            self.chain = self.agent.chain = self.agent.gov.chain = chain
        target = self.state_file(self.network, self.erp.name)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(target)

    @staticmethod
    def open(network: str = "localhost", log_path: Optional[Path] = None, signing: str = "client",
             erp: Optional[str] = None) -> "Session":
        """Reload saved state if it belongs to the deployed contracts; otherwise start from the demo baseline."""
        erp_name = make_adapter(erp).name
        p = Session.state_file(network, erp_name)
        chain = Chain(network, held_roles=held_roles(signing))
        if p.exists():
            d = pickle.loads(p.read_bytes())
            if d["vault"] == chain.dep["contracts"]["vault"]:
                s: Session = d["session"]
                s.signing = signing
                s.chain = s.agent.chain = s.agent.gov.chain = chain
                return s
        s = Session(network, log_path=log_path, signing=signing, erp=erp)
        s.save()
        return s

    # ------------------------------------------------------------------ ERP
    def sync_erp(self, max_age: float = 0.0) -> Optional[dict]:
        """Refresh the company records from the ERP (skipped for the demo file, or if synced within max_age s)."""
        if self.erp.name == "file" or time.time() - self.erp_synced < max_age:
            return None
        out = merge_into(self.led, self.erp.fetch())
        self.erp_synced = time.time()
        self.agent.log.add("agent", "erp_sync", out)
        return out

    def consistency(self) -> dict:
        """Ledger vs chain: every bill the ledger says was paid on-chain must be used in the vault, and no open
        bill may be. Also compares the pause switch and the active settings."""
        if not self.chain:
            return {"ok": True, "checked": 0, "mismatches": []}
        mism = []
        n = 0
        for b in self.led.bills.values():
            if b.bill_id.startswith("H"):
                continue
            n += 1
            used = self.chain.bill_used(b.bill_id)
            if b.status == "paid" and b.tx_hash and not used:
                mism.append({"bill": b.bill_id, "ledger": "paid", "chain": "not paid"})
            if b.status in ("received", "held", "approved") and used:
                mism.append({"bill": b.bill_id, "ledger": b.status, "chain": "paid"})
        return {"ok": not mism, "checked": n, "mismatches": mism}

    # ------------------------------------------------------------------ documents
    def ingest_file(self, filename: str, data: bytes, process: bool = True, auto_pay: bool = True) -> dict:
        """A document as received (JSON e-invoice, PDF or image). Kept under data/state/uploads/."""
        read, kind = read_document(filename, data)
        self.sync_erp(max_age=30)  # check the bill against the ERP as it is now
        self.uploads += 1
        keep = STATE_DIR / "uploads" / f"{self.uploads:04d}-{Path(filename).name}"
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_bytes(data)
        bill = self.agent.intake(read, "photo" if kind == "photo" else kind)
        if not process:
            return {"bill": bill.bill_id, "source": kind}
        return {**self.agent.process(bill.bill_id, auto_pay=auto_pay), "source": kind}

    def ingest(self, key: str, process: bool = True, auto_pay: bool = True) -> dict:
        """A demo document from data/demo/documents, through the same path as an upload."""
        p = demo.DEMO_DIR / self.docs[key]["file"]
        return self.ingest_file(p.name, p.read_bytes(), process, auto_pay)

    def statement(self, supplier_id: str, filename: str, data: bytes) -> list:
        return self.agent.reconcile(supplier_id, parse_statement(filename, data))

    # ------------------------------------------------------------------ requests
    def request_state(self) -> dict:
        sups = {sid: {"name": s.name, "materials": sorted({l.item for po in self.led.pos.values() if po.supplier_id == sid for l in po.lines})}
                for sid, s in self.led.suppliers.items() if sid in demo.DEMO_SUPPLIERS}
        bills = {b.bill_id[-4:]: {"supplier_id": b.supplier_id, "inv_no": b.read.inv_no, "status": b.status}
                 for b in self.led.bills.values() if not b.bill_id.startswith("H") and b.status in ("received", "held", "approved")}
        return {"suppliers": sups, "bills": bills}

    def alias(self) -> dict:
        return {b.bill_id[-4:]: b.bill_id for b in self.led.bills.values() if not b.bill_id.startswith("H")}

    def request(self, text: str, role: str = "owner") -> dict:
        self.agent.log.add(role, "request", {"text": text})
        r = self.router.route(text, self.request_state(), role)
        self.agent.log.add("agent", "route", {"outcome": r.outcome, "intent_set": r.intent_set, "slot_set": r.slot_set,
                                              "q_intent": self.router.q_intent, "q_slot": self.router.q_slot})
        if r.outcome != "plan":
            qid = f"QQ-{len(self.pending) + int(time.time()) % 100000:05d}"
            self.pending[qid] = r
            return {"kind": "question", "id": qid, "route": r.to_json()}
        return self._plan(r)

    def answer(self, qid: str, choice: str) -> dict:
        """The user taps one button. Intent questions pick the intent; slot questions pick the value."""
        from .intent.catalogue import CATALOGUE

        r = self.pending.pop(qid)
        if r.question["kind"] == "intent":
            r.intent, r.intent_set = choice, [choice]
            if CATALOGUE[choice].key_slot:
                rr = self.router.route(r.text, self.request_state())
                r.value = rr.value if rr.intent == choice else None
        else:
            r.value = choice
        r.outcome = "plan"
        self.agent.log.add("owner", "answer", {"question": qid, "choice": choice})
        return self._plan(r)

    def _plan(self, r: Route) -> dict:
        p = planner.build(self.agent, r, self.alias())
        self.plans[p.plan_id] = p
        self.agent.log.add("agent", "plan_preview", {"intent": p.intent, "summary": p.summary, "steps": len(p.steps)},
                           plan_id=p.plan_id)
        return {"kind": "plan", "plan": p.to_json(), "route": r.to_json()}

    def run(self, plan_id: str, cancel_after: Optional[int] = None) -> dict:
        return planner.run(self.agent, self.plans[plan_id], cancel_after=cancel_after).to_json()

    def sign_settings(self, plan_id: str, tx_hash: Optional[str] = None) -> dict:
        p = self.plans[plan_id]
        st = next(s for s in p.steps if s.kind == "settings")
        out = self.agent.apply_bundle(st.result["proposal"], tx_hash=tx_hash)
        if not out.get("error"):
            st.status = "done" if out.get("active") else "needs_signature"
            st.result["signed"] = out
        return out

    # ------------------------------------------------------------------ time (local chain only)
    def close_day(self) -> Optional[dict]:
        """Anchor the day's decision-log Merkle root on-chain, once per ledger day (plan: daily root)."""
        anchored = self.__dict__.setdefault("anchored", set())  # sessions saved before this field existed
        day = date.fromisoformat(self.led.today).toordinal()
        if day in anchored:
            return None
        out = self.agent.anchor_day(day)
        if out.get("tx") is None or out["tx"]["ok"]:
            anchored.add(day)
        return out

    def next_day(self, days: int = 1) -> str:
        """Hardhat: jump a day. FISCO BCOS, Base Sepolia: wait one demo day (the contract's dayLength)."""
        if not (self.chain and self.chain.network in DEMO_CLOCK):
            raise RuntimeError("the demo clock can only move on a local chain")
        self.close_day()
        self.chain.advance(self.chain.day_seconds * days)
        self.led.today = (date.fromisoformat(self.led.today) + timedelta(days=days)).isoformat()
        self.agent.gov.state.blocked.clear()
        return self.led.today


def reset(network: str = "localhost", log_path: Optional[Path] = None, allow_testnet: bool = False,
          signing: str = "client", erp: Optional[str] = None) -> Session:
    """Redeploy the contracts and start the ledger from the demo baseline, together, so they always agree."""
    if network not in ("localhost", "fisco") and not allow_testnet:
        raise RuntimeError("redeploying on a public network costs gas; pass allow_testnet=True")
    # shutil.which finds npx.cmd on Windows, where a bare "npx" is not an executable
    r = subprocess.run([shutil.which("npx") or "npx", "hardhat", "run", "scripts/deploy.js", "--network", network], cwd=CHAIN_DIR,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"deploy failed: {r.stderr[-800:]}")
    adapter = make_adapter(erp)
    Session.state_file(network, adapter.name).unlink(missing_ok=True)
    if hasattr(adapter, "remove_agent_postings"):
        adapter.remove_agent_postings()  # the ERP goes back to the state the fresh ledger expects
    if log_path and log_path.exists():
        log_path.rename(log_path.with_suffix(f".{int(time.time())}.jsonl"))
    s = Session(network, log_path=log_path, signing=signing, erp=erp)
    if network in ("localhost", "fisco"):
        s.chain.advance(s.chain.cool_down + 1)  # payee cool-down (on FISCO this waits)
    s.save()
    return s
