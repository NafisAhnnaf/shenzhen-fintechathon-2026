"""Postgres store (Neon in production, a local Postgres in tests): one row set per company.

    DATABASE_URL=postgresql://...        the database
    APP_SECRET=...                       signs the agent's working memory (see below)

What lives where:
- Business records are rows, the system of record, loaded from these tables on start: bills, suppliers, cases,
  receivables, emails, anchors, and the journal. The journal is append-only (a trigger refuses UPDATE and DELETE)
  and hash-chained: each row stores the hash of its own content and of the previous row.
- The ERP mirror (orders, receipts, returns, a year of settled bills) is one compressed JSON document per company,
  written only when it changes (it is a copy of the ERP, which stays the source of those records).
- The agent's working memory (governor state, check results, plans, open questions) is a small pickled blob signed
  with HMAC-SHA256: a row someone altered in the database is refused instead of being unpickled.
Money and approvals stay on-chain; the session's consistency check compares these rows with the chain.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import pickle
import zlib
from dataclasses import asdict
from typing import Optional

from web3 import Web3

from .audit import LogLine
from .domain import (Bill, Case, GoodsReceipt, InvLine, Ledger, Material, POLine, PurchaseOrder, Read, Receivable,
                     ReturnRecord, Supplier)

SCHEMA = [
    # v1
    """
    create table if not exists companies (
        id text primary key,
        name text not null,
        network text not null,
        deployment jsonb not null,
        settings jsonb not null default '{}',
        demo boolean not null default false,
        created_at timestamptz not null default now()
    );
    create table if not exists erp_snapshots (
        company_id text primary key references companies(id) on delete cascade,
        digest text not null,
        data bytea not null,
        saved_at timestamptz not null default now()
    );
    create table if not exists suppliers (
        company_id text references companies(id) on delete cascade,
        id text,
        name text not null,
        frozen boolean not null,
        data jsonb not null,
        updated_at timestamptz not null default now(),
        primary key (company_id, id)
    );
    create table if not exists bills (
        company_id text references companies(id) on delete cascade,
        bill_id text,
        inv_no text not null,
        supplier_id text,
        status text not null,
        tier text,
        amount_usd numeric(18,2) not null,
        received text not null,
        paid_on text,
        tx_hash text,
        data jsonb not null,
        updated_at timestamptz not null default now(),
        primary key (company_id, bill_id)
    );
    create index if not exists bills_status on bills(company_id, status);
    create table if not exists cases (
        company_id text references companies(id) on delete cascade,
        case_id text,
        kind text not null,
        status text not null,
        data jsonb not null,
        primary key (company_id, case_id)
    );
    create table if not exists receivables (
        company_id text references companies(id) on delete cascade,
        bill_id text,
        data jsonb not null,
        primary key (company_id, bill_id)
    );
    create table if not exists emails (
        company_id text references companies(id) on delete cascade,
        id text,
        template text not null,
        status text not null,
        to_address text not null,
        data jsonb not null,
        primary key (company_id, id)
    );
    create table if not exists anchors (
        company_id text references companies(id) on delete cascade,
        day integer,
        data jsonb not null,
        primary key (company_id, day)
    );
    create table if not exists journal (
        company_id text references companies(id) on delete cascade,
        seq integer,
        ts double precision not null,
        actor text not null,
        kind text not null,
        bill_id text,
        plan_id text,
        policy text,
        decision text,
        tx_hash text,
        security boolean not null,
        detail jsonb not null,
        input_hash text,
        leaf text not null,
        prev_hash text not null,
        chain_hash text not null,
        primary key (company_id, seq)
    );
    create index if not exists journal_security on journal(company_id) where security;
    create table if not exists agent_state (
        company_id text primary key references companies(id) on delete cascade,
        data bytea not null,
        mac text not null,
        saved_at timestamptz not null default now()
    );
    create or replace function journal_append_only() returns trigger language plpgsql as $$
    begin
        if current_setting('app.allow_purge', true) = 'on' then
            if tg_op = 'DELETE' then return old; end if;
            return new;
        end if;
        raise exception 'the journal is append-only';
    end $$;
    drop trigger if exists journal_no_change on journal;
    create trigger journal_no_change before update or delete on journal
        for each row execute function journal_append_only();
    """,
]

GENESIS = "0x" + "00" * 32


def _hex(b: bytes) -> str:
    return "0x" + b.hex().removeprefix("0x")


def chain_hash(prev: str, leaf: str) -> str:
    """Each journal row's hash covers its own content and the previous row's hash."""
    return _hex(Web3.keccak(bytes.fromhex(prev[2:]) + bytes.fromhex(leaf[2:])))


def database_url() -> Optional[str]:
    from .config import load_env
    load_env()
    return os.environ.get("DATABASE_URL") or None


def _secret() -> bytes:
    s = os.environ.get("APP_SECRET", "")
    if not s:
        raise RuntimeError("APP_SECRET is not set: it signs the agent's saved working memory")
    return s.encode()


# ------------------------------------------------------------------ (de)serialising the ERP mirror
def erp_doc(led: Ledger) -> dict:
    """The ERP mirror: everything the ERP owns. Live bills, suppliers, cases and receivables have their own rows."""
    return {"company": led.company, "materials": {k: asdict(v) for k, v in led.materials.items()},
            "pos": {k: asdict(v) for k, v in led.pos.items()}, "receipts": [asdict(g) for g in led.receipts],
            "returns": [asdict(r) for r in led.returns], "billed_external": led.billed_external,
            "erp_source": led.erp_source,
            "history": {k: asdict(b) for k, b in led.bills.items() if k.startswith("H")}}


def bill_from(d: dict) -> Bill:
    d = dict(d)
    r = dict(d["read"])
    r["lines"] = [InvLine(**l) for l in r["lines"]]
    d["read"] = Read(**r)
    return Bill(**d)


def ledger_from(doc: dict, state: dict) -> Ledger:
    led = Ledger(company=doc["company"], today=state["today"], cash_usd=state["cash_usd"],
                 billed_external=doc.get("billed_external", {}), erp_source=doc.get("erp_source", "file"))
    led.materials = {k: Material(**v) for k, v in doc["materials"].items()}
    led.pos = {k: PurchaseOrder(v["po_id"], v["supplier_id"], v["date"], [POLine(**l) for l in v["lines"]])
               for k, v in doc["pos"].items()}
    led.receipts = [GoodsReceipt(**g) for g in doc["receipts"]]
    led.returns = [ReturnRecord(**r) for r in doc["returns"]]
    led.bills = {k: bill_from(v) for k, v in doc["history"].items()}
    return led


class Store:
    def __init__(self, url: Optional[str] = None):
        import psycopg
        from psycopg.types.json import Jsonb

        self.url = url or database_url()
        if not self.url:
            raise RuntimeError("DATABASE_URL is not set")
        self._psycopg, self.Jsonb = psycopg, Jsonb
        self._saved: dict[str, dict] = {}  # per company: what was last written, to send only changes

    def connect(self):
        return self._psycopg.connect(self.url, connect_timeout=20)

    def migrate(self) -> int:
        with self.connect() as c:
            c.execute("create table if not exists schema_version (v integer not null)")
            row = c.execute("select max(v) from schema_version").fetchone()
            v = row[0] or 0
            for i, sql in enumerate(SCHEMA[v:], start=v + 1):
                c.execute(sql)
                c.execute("insert into schema_version (v) values (%s)", (i,))
            return len(SCHEMA)

    # ------------------------------------------------------------------ companies
    def create_company(self, company_id: str, name: str, network: str, deployment: dict, demo: bool = False,
                       settings: Optional[dict] = None) -> None:
        with self.connect() as c:
            c.execute("insert into companies (id, name, network, deployment, settings, demo) values (%s,%s,%s,%s,%s,%s) "
                      "on conflict (id) do update set name=excluded.name, network=excluded.network, "
                      "deployment=excluded.deployment, demo=excluded.demo",
                      (company_id, name, network, self.Jsonb(deployment), self.Jsonb(settings or {}), demo))

    def company(self, company_id: str) -> Optional[dict]:
        with self.connect() as c:
            row = c.execute("select id, name, network, deployment, settings, demo from companies where id=%s",
                            (company_id,)).fetchone()
        return dict(zip(("id", "name", "network", "deployment", "settings", "demo"), row)) if row else None

    def companies(self) -> list[dict]:
        with self.connect() as c:
            rows = c.execute("select id, name, network, demo, created_at from companies order by created_at").fetchall()
        return [dict(zip(("id", "name", "network", "demo", "created_at"), r)) for r in rows]

    def delete_company(self, company_id: str) -> None:
        """Remove a company and all its rows (demo companies only). The journal's append-only rule is lifted
        for this one transaction."""
        with self.connect() as c:
            c.execute("set local app.allow_purge = 'on'")
            c.execute("delete from companies where id=%s", (company_id,))
        self._saved.pop(company_id, None)

    # ------------------------------------------------------------------ saving a session
    def save(self, company_id: str, s) -> dict:
        """Write what changed since the last save. Returns counts, for the logs and tests."""
        ag, led = s.agent, s.led
        prev = self._saved.setdefault(company_id, {})
        out = {"bills": 0, "suppliers": 0, "journal": 0, "emails": 0, "cases": 0, "erp": 0}
        with self.connect() as c:
            # ERP mirror: only when it changed
            raw = json.dumps(erp_doc(led), sort_keys=True, default=str).encode()
            digest = hashlib.sha256(raw).hexdigest()
            if prev.get("erp") != digest:
                c.execute("insert into erp_snapshots (company_id, digest, data) values (%s,%s,%s) "
                          "on conflict (company_id) do update set digest=excluded.digest, data=excluded.data, saved_at=now()",
                          (company_id, digest, zlib.compress(raw, 6)))
                prev["erp"] = digest
                out["erp"] = 1
            # rows that may change: write those whose content changed
            def upsert(kind: str, key: str, payload: dict, sql: str, params: tuple):
                h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
                seen = prev.setdefault(kind, {})
                if seen.get(key) != h:
                    c.execute(sql, params)
                    seen[key] = h
                    out[kind] = out.get(kind, 0) + 1

            for sid, sp in led.suppliers.items():
                d = asdict(sp)
                upsert("suppliers", sid, d,
                       "insert into suppliers (company_id, id, name, frozen, data) values (%s,%s,%s,%s,%s) "
                       "on conflict (company_id, id) do update set name=excluded.name, frozen=excluded.frozen, "
                       "data=excluded.data, updated_at=now()",
                       (company_id, sid, sp.name, sp.frozen, self.Jsonb(d)))
            for bid, b in led.bills.items():
                if bid.startswith("H"):
                    continue
                d = json.loads(json.dumps(asdict(b), default=str))
                upsert("bills", bid, d,
                       "insert into bills (company_id, bill_id, inv_no, supplier_id, status, tier, amount_usd, received, "
                       "paid_on, tx_hash, data) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (company_id, bill_id) "
                       "do update set inv_no=excluded.inv_no, supplier_id=excluded.supplier_id, status=excluded.status, "
                       "tier=excluded.tier, amount_usd=excluded.amount_usd, paid_on=excluded.paid_on, "
                       "tx_hash=excluded.tx_hash, data=excluded.data, updated_at=now()",
                       (company_id, bid, b.read.inv_no, b.supplier_id, b.status, b.tier, round(b.amount_usd, 2),
                        b.received, b.paid_on, b.tx_hash, self.Jsonb(d)))
            for cid, cs in led.cases.items():
                d = json.loads(json.dumps(asdict(cs), default=str))
                upsert("cases", cid, d,
                       "insert into cases (company_id, case_id, kind, status, data) values (%s,%s,%s,%s,%s) "
                       "on conflict (company_id, case_id) do update set status=excluded.status, data=excluded.data",
                       (company_id, cid, cs.kind, cs.status, self.Jsonb(d)))
            for bid, r in led.receivables.items():
                d = json.loads(json.dumps(asdict(r), default=str))
                upsert("receivables", bid, d,
                       "insert into receivables (company_id, bill_id, data) values (%s,%s,%s) "
                       "on conflict (company_id, bill_id) do update set data=excluded.data",
                       (company_id, bid, self.Jsonb(d)))
            for e in ag._emails():
                d = json.loads(json.dumps(e, default=str))
                upsert("emails", e["id"], d,
                       "insert into emails (company_id, id, template, status, to_address, data) values (%s,%s,%s,%s,%s,%s) "
                       "on conflict (company_id, id) do update set status=excluded.status, data=excluded.data",
                       (company_id, e["id"], e["template"], e["status"], e["to"], self.Jsonb(d)))
            for a in ag.__dict__.get("anchors", []):
                upsert("anchors", str(a["day"]), a,
                       "insert into anchors (company_id, day, data) values (%s,%s,%s) on conflict (company_id, day) "
                       "do update set data=excluded.data", (company_id, a["day"], self.Jsonb(a)))
            # journal: append the new lines, each chained to the previous one
            last = c.execute("select seq, chain_hash from journal where company_id=%s order by seq desc limit 1",
                             (company_id,)).fetchone()
            seq, prev_hash = (last[0] + 1, last[1]) if last else (0, GENESIS)
            for line in ag.log.lines[seq:]:
                leaf = _hex(line.leaf())
                ch = chain_hash(prev_hash, leaf)
                c.execute("insert into journal (company_id, seq, ts, actor, kind, bill_id, plan_id, policy, decision, "
                          "tx_hash, security, detail, input_hash, leaf, prev_hash, chain_hash) values "
                          "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                          (company_id, seq, line.ts, line.actor, line.kind, line.bill_id, line.plan_id, line.policy,
                           line.decision, line.tx_hash, line.security,
                           self.Jsonb(json.loads(json.dumps(line.detail, default=str))), line.input_hash, leaf,
                           prev_hash, ch))
                seq, prev_hash = seq + 1, ch
                out["journal"] += 1
            # working memory, signed
            blob = zlib.compress(pickle.dumps(working_memory(s)), 6)
            mac = hmac.new(_secret(), blob, hashlib.sha256).hexdigest()
            c.execute("insert into agent_state (company_id, data, mac) values (%s,%s,%s) on conflict (company_id) "
                      "do update set data=excluded.data, mac=excluded.mac, saved_at=now()", (company_id, blob, mac))
        return out

    # ------------------------------------------------------------------ loading a session
    def load(self, company_id: str):
        """Rebuild a session from the rows (None if the company has no saved state yet)."""
        from .session import Session
        prev: dict = {}
        with self.connect() as c:
            snap = c.execute("select digest, data from erp_snapshots where company_id=%s", (company_id,)).fetchone()
            st = c.execute("select data, mac from agent_state where company_id=%s", (company_id,)).fetchone()
            if not snap or not st:
                return None
            blob, mac = bytes(st[0]), st[1]
            if not hmac.compare_digest(hmac.new(_secret(), blob, hashlib.sha256).hexdigest(), mac):
                raise RuntimeError(f"saved working memory for {company_id} failed its signature check")
            mem = pickle.loads(zlib.decompress(blob))
            doc = json.loads(zlib.decompress(bytes(snap[1])))
            prev["erp"] = snap[0]
            led = ledger_from(doc, mem["ledger"])
            for sid, d in c.execute("select id, data from suppliers where company_id=%s", (company_id,)):
                led.suppliers[sid] = Supplier(**d)
            for bid, d in c.execute("select bill_id, data from bills where company_id=%s", (company_id,)):
                led.bills[bid] = bill_from(d)
            for cid, d in c.execute("select case_id, data from cases where company_id=%s", (company_id,)):
                led.cases[cid] = Case(**d)
            for bid, d in c.execute("select bill_id, data from receivables where company_id=%s", (company_id,)):
                led.receivables[bid] = Receivable(**d)
            emails = [d for (d,) in c.execute("select data from emails where company_id=%s order by id", (company_id,))]
            anchors = [d for (d,) in c.execute("select data from anchors where company_id=%s order by day", (company_id,))]
            lines = [LogLine(ts, actor, kind, detail, plan_id, bill_id, ih, policy, decision, tx, sec)
                     for (ts, actor, kind, detail, plan_id, bill_id, ih, policy, decision, tx, sec) in c.execute(
                         "select ts, actor, kind, detail, plan_id, bill_id, input_hash, policy, decision, tx_hash, security "
                         "from journal where company_id=%s order by seq", (company_id,))]
        s = Session.__new__(Session)
        restore(s, led, mem, lines, emails, anchors)
        self._saved[company_id] = prev  # rows are re-hashed on the next save; the ERP mirror is known
        return s

    def verify_journal(self, company_id: str) -> dict:
        """Recompute the hash chain from the stored rows: proves no row was altered, removed or reordered."""
        prev, n, bad = GENESIS, 0, []
        with self.connect() as c:
            for seq, leaf, p, ch in c.execute("select seq, leaf, prev_hash, chain_hash from journal where company_id=%s "
                                              "order by seq", (company_id,)):
                if p != prev or chain_hash(prev, leaf) != ch or seq != n:
                    bad.append(seq)
                prev, n = ch, n + 1
        return {"rows": n, "ok": not bad, "broken_at": bad[:5], "head": prev}


# ------------------------------------------------------------------ the agent's working memory
SESSION_FIELDS = ("network", "signing", "erp_synced", "plans", "pending", "uploads", "anchored", "_pay_timing",
                  "_trials", "mail_seen", "company_id")
AGENT_SKIP = {"led", "chain", "log", "erp", "cal", "gov", "emails", "anchors"}


def working_memory(s) -> dict:
    ag = s.agent
    return {"ledger": {"today": s.led.today, "cash_usd": s.led.cash_usd},
            "session": {k: s.__dict__[k] for k in SESSION_FIELDS if k in s.__dict__},
            "erp_name": s.erp.name,
            "agent": {k: v for k, v in ag.__dict__.items() if k not in AGENT_SKIP},
            "governor": {"state": ag.gov.state, "bundle_name": ag.gov.bundle_name}}


def restore(s, led: Ledger, mem: dict, lines: list, emails: list, anchors: list) -> None:
    from . import demo
    from .agent import Agent
    from .audit import AuditLog
    from .erp import make_adapter
    from .intent.router import Router
    from .risk.calibrate import Calibration

    s.__dict__.update(mem["session"])
    s.led = led
    s.erp = make_adapter(mem["erp_name"])
    s.chain = None
    s.agent = Agent(led, Calibration.load(), None, log=AuditLog(None, lines))
    s.agent.__dict__.update(mem["agent"])
    s.agent.erp = s.erp
    s.agent.__dict__["emails"] = emails
    s.agent.__dict__["anchors"] = anchors
    s.agent.gov.state = mem["governor"]["state"]
    s.agent.gov.bundle_name = mem["governor"]["bundle_name"]
    s.router = Router.load(None)
    s.docs = demo.load_docs()
