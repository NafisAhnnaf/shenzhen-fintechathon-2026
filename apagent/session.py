"""One running system: ledger + agent + chain + request router + plans. Used by the API and the task runner.

State is saved to data/state/<network>.pkl after every change and reloaded on start, but only if it belongs to
the contracts currently deployed (same vault address). consistency() compares the ledger with the chain.
"""
from __future__ import annotations

import json
import os
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
    """Keys this process loads in SIGNING=client mode. The bank approves bonded settings and disputes claims from
    its own wallet (UNDERWRITER_SERVICE=on keeps a server-side bank key for scripted demos). With a separate
    governor service (GOVERNOR_URL), this process does not hold the governor key either."""
    import os
    if signing == "server":
        return None
    from .agent import governor_url
    roles = set(SERVICE_ROLES)
    if os.environ.get("UNDERWRITER_SERVICE", "off").lower() not in ("on", "1", "true", "yes"):
        roles.discard("underwriter")
    if governor_url():
        roles.discard("governor")
    return roles


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


def store():
    """The Postgres store when STATE_STORE=postgres (production, Neon); otherwise None and state goes to a file."""
    import os
    from .config import load_env
    load_env()
    if os.environ.get("STATE_STORE", "file").lower() != "postgres":
        return None
    global _STORE
    if _STORE is None:
        from .store import Store
        _STORE = Store()
        _STORE.migrate()
    return _STORE


_STORE = None
DEFAULT_COMPANY = "demo"


class Session:
    def __init__(self, network: Optional[str] = "localhost", decider=None, log_path: Optional[Path] = None,
                 signing: str = "server", erp: Optional[str] = None, company_id: str = DEFAULT_COMPANY,
                 dep: Optional[dict] = None):
        self.company_id = company_id
        self.network = network
        self.signing = signing
        self.erp: ErpAdapter = make_adapter(erp)
        self.led = ledger_for(self.erp)
        self.erp_synced = time.time()
        self.chain = Chain(network, held_roles=held_roles(signing), dep=dep) if network else None
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
        st = store()
        if st is not None:
            st.save(self.company_id, self)
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

    def attach(self, chain: Chain) -> "Session":
        self.chain = self.agent.chain = self.agent.gov.chain = chain
        return self

    @staticmethod
    def open(network: str = "localhost", log_path: Optional[Path] = None, signing: str = "client",
             erp: Optional[str] = None, company_id: str = DEFAULT_COMPANY) -> "Session":
        """Reload saved state if it belongs to the deployed contracts; otherwise start from the demo baseline.
        With the Postgres store, the company's row holds its own deployment and its state is rebuilt from rows."""
        st = store()
        if st is not None:
            co = st.company(company_id)
            own = network in ("localhost", "fisco") and os.environ.get("PER_COMPANY_CONTRACTS", "off") == "on"
            if co is None and own:  # a company of its own: fresh contracts, nothing shared with other companies
                return reset(network, log_path, signing=signing, erp=erp, company_id=company_id)
            if co is not None and own and not Chain(co["network"], held_roles=held_roles(signing), dep=co["deployment"]).has_code():
                # The local chain started again and the company's contracts are gone: start it again from the
                # sample records rather than show records the chain no longer agrees with.
                return reset(network, log_path, signing=signing, erp=erp, company_id=company_id)
            if co is None:
                dep = json.loads((CHAIN_DIR / "deployments" / f"{network}.json").read_text())
                st.create_company(company_id, Ledger.load(demo.DEMO_DIR / "ledger.json").company, network, dep)
                co = st.company(company_id)
            chain = Chain(co["network"], held_roles=held_roles(signing), dep=co["deployment"])
            s = st.load(company_id)
            if s is not None:
                s.signing = signing
                return s.attach(chain)
            s = Session(co["network"], log_path=log_path, signing=signing, erp=erp, company_id=company_id,
                        dep=co["deployment"])
            s.save()
            return s
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
            if b.status in ("received", "held", "approved", "rejected") and used:
                mism.append({"bill": b.bill_id, "ledger": b.status, "chain": "paid"})
        for sid, sp in self.led.suppliers.items():
            if sid not in demo.DEMO_SUPPLIERS:
                continue
            p = self.chain.payee(sid)
            n += 1
            if p["exists"] and p["frozen"] != sp.frozen:
                mism.append({"supplier": sid, "ledger": "frozen" if sp.frozen else "active",
                             "chain": "frozen" if p["frozen"] else "active"})
        st = self.chain.state()
        b = self.agent.cal.bundle(self.agent.gov.bundle_name)
        if (round(b.p_day_usd, 2), b.p_nday) != (round(st["p_day_usd"], 2), st["p_nday"]):
            mism.append({"settings": self.agent.gov.bundle_name, "ledger": f"{b.p_day_usd:,.0f}/day, {b.p_nday} payments",
                         "chain": f"{st['p_day_usd']:,.0f}/day, {st['p_nday']} payments"})
        return {"ok": not mism, "checked": n + 1, "mismatches": mism}

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
        out = self.agent.process(bill.bill_id, auto_pay=auto_pay and self.pay_timing == "now")
        if out.get("tier") == "T1" and bill.status == "approved":
            from . import views
            out["scheduled"] = next((r["pay_on"] for r in views.schedule(self) if r["bill"] == bill.bill_id), None)
        return {**out, "source": kind}

    def ingest(self, key: str, process: bool = True, auto_pay: bool = True) -> dict:
        """A demo document from data/demo/documents, through the same path as an upload."""
        p = demo.DEMO_DIR / self.docs[key]["file"]
        return self.ingest_file(p.name, p.read_bytes(), process, auto_pay)

    # ------------------------------------------------------------------ pay timing (spec P3)
    @property
    def pay_timing(self) -> str:
        """now: pay a cleared bill at once. best_date: pay on the planner's date (discount window or day before due)."""
        return self.__dict__.get("_pay_timing", "now")

    def set_pay_timing(self, mode: str) -> dict:
        if mode not in ("now", "best_date"):
            raise ValueError("pay timing is 'now' or 'best_date'")
        self.__dict__["_pay_timing"] = mode
        self.agent.log.add("owner", "pay_timing", {"mode": mode})
        return {"pay_timing": mode}

    def run_due(self) -> list[dict]:
        """Pay the scheduled bills whose date has come."""
        from . import views
        out = []
        for r in views.schedule(self):
            b = self.led.bills[r["bill"]]
            if r["stage"] == "scheduled" and r["pay_on"] <= self.led.today:
                out.append(self.agent.pay_t1(b.bill_id))
        return out

    def poll_mailbox(self) -> list[dict]:
        """Read new mail (spec R4). Attachments from a registered supplier's address go through bill intake; other
        messages go to the reply path (query replies, bank-detail requests). Each message is read once."""
        from . import mail
        from .intake import BadDocument, ReaderUnavailable, parse_email, supplier_by_sender

        seen = self.__dict__.setdefault("mail_seen", set())
        out = []
        for key, raw in mail.mailbox().fetch(seen):
            seen.add(key)
            text, files = mail.split_message(raw)
            sender = parse_email(text)["from"]
            if not files:
                out.append({"message": key, **self.agent.receive_email(text)})
                continue
            sid = supplier_by_sender(self.led, sender)
            if sid is None:
                self.agent.log.add("agent", "email_unknown_sender", {"from": sender, "attachments": len(files)}, security=True)
                out.append({"message": key, "from": sender, "action": "ignored: sender is not a registered supplier"})
                continue
            for name, data in files:
                try:
                    out.append({"message": key, "file": name, **self.ingest_file(name, data)})
                except (BadDocument, ReaderUnavailable) as e:
                    out.append({"message": key, "file": name, "error": str(e)})
        if out:
            self.agent.log.add("agent", "mailbox_poll", {"messages": len({o["message"] for o in out})})
        return out

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

    REQUEST_MAX_CHARS = 500

    def request(self, text: str, role: str = "owner") -> dict:
        """A typed request. Too long, or written as instructions to the AI (the same patterns as on invoices), it is
        refused before any model sees it, and the refusal is a security event."""
        from . import injection

        text = (text or "").strip()
        if not text:
            raise ValueError("Type what you want done")
        if len(text) > self.REQUEST_MAX_CHARS:
            self.agent.log.add(role, "request_refused", {"reason": "too long", "chars": len(text)}, security=True)
            raise ValueError(f"Keep requests under {self.REQUEST_MAX_CHARS} characters")
        inj = injection.score(text)
        if inj["p"] >= self.agent.cfg.injection_threshold:
            self.agent.log.add(role, "request_refused", {"reason": "reads as instructions to the AI", "p": inj["p"],
                                                         "chars": len(text)}, security=True)
            return {"kind": "refused", "reason": "This reads like instructions to the AI rather than a task. Say what "
                    "you want done, for example \"pay Acme's bills due this week\".", "p": inj["p"]}
        self.agent.log.add(role, "request", {"text": text})
        r = self.router.route(text, self.request_state(), role)
        d = self.router.decider
        reader = {"decider": getattr(d, "last", d.name), "model": getattr(getattr(d, "primary", None), "model", None),
                  "fallback": getattr(d, "last", d.name) != d.name, "provisional_calibration": getattr(self.router, "provisional", False)}
        if reader["fallback"]:
            reader["error"] = getattr(d, "error", None)
        self.agent.log.add("agent", "route", {"outcome": r.outcome, "intent_set": r.intent_set, "slot_set": r.slot_set,
                                              "q_intent": self.router.q_intent, "q_slot": self.router.q_slot, "reader": reader})
        if r.outcome != "plan":
            qid = f"QQ-{len(self.pending) + int(time.time()) % 100000:05d}"
            self.pending[qid] = r
            return {"kind": "question", "id": qid, "route": r.to_json(), "reader": reader}
        return {**self._plan(r), "reader": reader}

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

    def run(self, plan_id: str, cancel_after: Optional[int] = None, actor: str = "owner") -> dict:
        return planner.run(self.agent, self.plans[plan_id], cancel_after=cancel_after, actor=actor).to_json()

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

    def clock(self) -> str:
        """"real": the ledger date is today's date. "demo": it stays on the sample records' date and moves only with
        the demo controls. CLOCK sets it; by default a company on the sample records keeps the demo date (its
        invoices and orders are dated around it) and one connected to a real ERP runs on the calendar."""
        mode = os.environ.get("CLOCK", "").lower()
        if mode in ("real", "demo"):
            return mode
        return "demo" if self.erp.name == "file" else "real"

    def sync_clock(self) -> bool:
        """On the real clock, move the ledger to today, closing (anchoring) the last open day first. True if moved."""
        if self.clock() != "real":
            return False
        today = date.today().isoformat()
        if today <= self.led.today:
            return False
        self.close_day()
        self.led.today = today
        self.agent.gov.state.blocked.clear()
        if self.pay_timing == "best_date":
            self.run_due()
        return True

    def next_day(self, days: int = 1) -> str:
        """Hardhat: jump a day. FISCO BCOS, Base Sepolia: wait one demo day (the contract's dayLength)."""
        if not (self.chain and self.chain.network in DEMO_CLOCK):
            raise RuntimeError("the demo clock can only move on a local chain")
        self.close_day()
        self.chain.advance(self.chain.day_seconds * days)
        self.led.today = (date.fromisoformat(self.led.today) + timedelta(days=days)).isoformat()
        self.agent.gov.state.blocked.clear()
        if self.pay_timing == "best_date":
            self.run_due()
        return self.led.today


def reset(network: str = "localhost", log_path: Optional[Path] = None, allow_testnet: bool = False,
          signing: str = "client", erp: Optional[str] = None, company_id: str = DEFAULT_COMPANY) -> Session:
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
    st = store()
    if st is not None:  # the company starts again: fresh contracts, its rows removed
        dep = json.loads((CHAIN_DIR / "deployments" / f"{network}.json").read_text())
        name = Ledger.load(demo.DEMO_DIR / "ledger.json").company
        st.delete_company(company_id)
        st.create_company(company_id, name, network, dep)
    if hasattr(adapter, "remove_agent_postings"):
        adapter.remove_agent_postings()  # the ERP goes back to the state the fresh ledger expects
    if log_path and log_path.exists():
        log_path.rename(log_path.with_suffix(f".{int(time.time())}.jsonl"))
    s = Session(network, log_path=log_path, signing=signing, erp=erp, company_id=company_id,
                dep=json.loads((CHAIN_DIR / "deployments" / f"{network}.json").read_text()))
    from .agent import _governor_headers, governor_url
    if governor_url():  # the governor service starts again from the company records, too
        import httpx
        try:
            httpx.post(f"{governor_url()}/reset", timeout=60, headers=_governor_headers())
        except httpx.HTTPError:
            pass
    if network in ("localhost", "fisco"):
        s.chain.advance(s.chain.cool_down + 1)  # payee cool-down (on FISCO this waits)
    s.save()
    return s
