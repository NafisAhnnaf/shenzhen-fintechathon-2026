"""Scripted tasks (plan 10.1). Each ends in a transaction hash or a log line. Writes the execution evidence.

    python -m apagent.tasks --network localhost      (after deploying to a local node)
    python -m apagent.tasks --network baseSepolia    (real testnet: no time travel, see README)

Task 17 (market watch) is not built in v3. Task numbers follow the plan.
"""
from __future__ import annotations

import argparse
import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import naive
from .audit import input_hash
from .chain import DEMO_CLOCK
from .config import DATA_DIR
from .governor import Decision
from .reader import VLMReader
from . import demo
from .session import Session

EVIDENCE_DIR = DATA_DIR.parent / "evidence"


@dataclass
class Evidence:
    task: str
    title: str
    story: str  # routine, mistake_recovery, attack_defence, control
    steps: list = field(default_factory=list)
    ok: bool = False
    error: Optional[str] = None
    started: float = 0.0

    def add(self, action: str, actor: str, result, tx: Optional[str] = None, expect: Optional[str] = None) -> None:
        self.steps.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, "actor": actor,
                           "result": result, "tx_hash": tx, "expect": expect})


def _tx(r) -> Optional[str]:
    if isinstance(r, dict):
        t = r.get("tx")
        if isinstance(t, dict):
            return t.get("tx_hash")
        return r.get("tx_hash")
    return None


class Runner:
    def __init__(self, network: str):
        self.s = Session(network)
        self.ag = self.s.agent
        self.ch = self.s.chain
        self.network = network
        self.out: list[Evidence] = []
        self.bills: dict[str, str] = {}

    def task(self, tid: str, title: str, story: str):
        def wrap(fn: Callable[[Evidence], bool]):
            ev = Evidence(tid, title, story, started=time.time())
            self.ag.gov.state.blocked.clear()
            try:
                ev.ok = bool(fn(ev))
            except Exception as e:  # keep going: the evidence file reports what failed
                ev.error = f"{type(e).__name__}: {e}"
                ev.steps.append({"trace": traceback.format_exc()[-1500:]})
            self.out.append(ev)
            print(f"[{'PASS' if ev.ok else 'FAIL'}] task {tid}: {title}" + (f"  ({ev.error})" if ev.error else ""))
            return fn
        return wrap

    # ================================================================== day 1
    def day1(self) -> None:
        T = self.task

        @T("8", "Poisoned invoice: held, and a payment to the document's address refused twice", "attack_defence")
        def _(ev):
            read = demo.read_from_doc(self.s.docs["t07_poisoned"])
            n = {"plan": naive.plan_from_text(read.raw_text, self.ch.state()["vault_balance_usd"], read.total)}
            ev.add("what the invoice's hidden text asks for", "document", n, None, "pay a new address")
            r = self.s.ingest("t07_poisoned")
            self.bills["poisoned"] = r["bill"]
            ev.add("our agent processes the same invoice", "agent", r, None, "hold, nothing moves")
            # The planner never sees supplier text; if anything tried to pay the address from the document, S1 refuses it.
            from .policies import ToolCall
            from .tags import Src, T as Tg
            blocked = self.ag._gate(ToolCall("pay_autonomous", {"payee": Tg.of(n["plan"]["to"], Src.SUPPLIER_DOC),
                                                                 "amount": Tg.of(n["plan"]["amount"], Src.SUPPLIER_DOC)}), r["bill"])
            ev.add("tool call with payee from the document", "policy_gate", {"blocked_by": blocked}, None, "S1")
            # Even a signed payment to the attacker reverts: the address is not a registered payee.
            fake = Decision("T1", [], "routine", 0.1, 0.5, 4000.0)
            ih = input_hash({"attack": "unregistered payee"})
            self.ag.gov.sign(fake, r["bill"], "ATTACKER", self.ch.state()["settings_id"], ih)
            tx = self.ch.pay_autonomous(r["bill"], "ATTACKER", 4000.0, fake.settings_id, fake.expiry, ih, fake.signature, mine_revert=True)
            ev.add("payment to the attacker sent anyway (hacked app)", "agent_key", {"error": tx.error}, tx.tx_hash, "revert PayeeNotActive")
            return n["plan"]["to"] != "registered" and r["tier"] in ("hold", "T2") and blocked == "S1" and not tx.ok

        @T("7", "Hidden instruction to pay a new account: flagged, S1 blocks", "attack_defence")
        def _(ev):
            b = self.ag.led.bills[self.bills["poisoned"]]
            sec = [l for l in self.ag.log.security() if l.bill_id == b.bill_id]
            ev.add("injection flag", "agent", {"p": b.injection_p}, None, "p >= 0.5")
            ev.add("security log lines", "system", [{"kind": l.kind, "policy": l.policy} for l in sec])
            return b.injection_p >= 0.5 and any(l.policy == "S1" for l in sec)

        @T("1", "Routine bill paid alone; reserve locked, then released", "routine")
        def _(ev):
            r = self.s.ingest("t01_routine")
            self.bills["t01"] = r["bill"]
            ev.add("read, match, score, pay alone", "agent", r, _tx(r), "T1 payment")
            lock = self.ch.pool.functions.locks(__import__("apagent.chain", fromlist=["b32"]).b32(r["bill"])).call()
            ev.add("reserve locked", "contract", {"r_usd": lock[1] / 1000}, None)
            return r["tier"] == "T1" and r["tx"]["ok"]

        @T("2", "Same invoice sent twice (re-issued with a new number): second payment blocked", "routine")
        def _(ev):
            r1 = self.s.ingest("t02_pdf")
            ev.add("first copy", "agent", r1, _tx(r1))
            # The plan's version sends the duplicate as a phone photo; that needs the vision reader (VLM_API_KEY).
            # Without it, the second copy is the same invoice re-issued with a new number and another layout.
            if VLMReader().available():
                r2 = self.s.ingest("t02_photo")
                ev.add("phone photo of the same invoice (read by the vision model)", "agent", r2, None, "reject as duplicate")
            else:
                r2 = self.s.ingest("t02_resent")
                ev.add("re-issued copy of the same invoice", "agent", r2, None, "reject as duplicate")
            self.bills["t02"] = r1["bill"]
            return r1["tier"] == "T1" and r2["tier"] == "reject"

        @T("13", "2/10 net 30 paid inside the discount window; a net-30 bill waits", "routine")
        def _(ev):
            r = self.s.ingest("t13_net30", auto_pay=False)
            b = self.ag.led.bills[r["bill"]]
            sched = self.ag.plan_dates([self.ag.led.bills[self.bills["t02"]], b])
            ev.add("payment planner", "agent", sched)
            ev.add("discount taken on the Sun Kee bill", "agent", {"discount_usd": self.ag.money["discounts_taken"]},
                   self.ag.led.bills[self.bills["t02"]].tx_hash)
            later = next(x for x in sched if x["bill"] == b.bill_id)
            return self.ag.money["discounts_taken"] > 0 and not later["early"]

        @T("15", "Mainland payee via bank rail; vault records it", "routine")
        def _(ev):
            r = self.s.ingest("t15_bank_rail")
            ev.add("Ganjiang (mainland) bill, bank rail", "agent", r, _tx(r), "BankPaymentRecorded")
            rc = self.ch.w3.eth.get_transaction_receipt(_tx(r))
            from web3.logs import DISCARD
            logs = self.ch.vault.events.BankPaymentRecorded().process_receipt(rc, errors=DISCARD)
            ev.add("bank reference", "contract", {"bank_ref": "0x" + logs[0]["args"]["bankRef"].hex()} if logs else {})
            return r["tier"] == "T1" and bool(logs)

        @T("4", "Agent reconciles the statement, finds the missed credit; claim paid; cut-off drops; probation", "mistake_recovery")
        def _(ev):
            r = self.s.ingest("t04_missed_credit")
            self.bills["t04"] = r["bill"]
            ev.add("Shatin PCB bill paid alone (a credit for returned boards was never recorded or billed)", "agent",
                   r, _tx(r), "T1, overpaid")
            p = demo.STATEMENTS_DIR / "SHATINPCB-2025-12.csv"
            cases = self.s.statement("SHATINPCB", p.name, p.read_bytes())
            ev.add("statement reconciliation", "agent", [c.detail for c in cases], None, "missed_credit case")
            mc = next(c for c in cases if c.kind == "missed_credit")
            out = self.ag.confirm_case(mc.case_id)
            ev.add("manager confirms with one tap", "finance_manager", {k: v for k, v in out.items() if k != "claim"},
                   (out.get("receivable_tx") or {}).get("tx_hash"))
            ev.add("claim filed with the manager's signature", "agent", out.get("claim"), (out.get("claim") or {}).get("tx_hash"))
            self.ch.advance(121)
            pay = self.ag.execute_claim(r["bill"])
            ev.add("reserve repays the company", "contract", pay, pay.get("tx_hash"))
            return pay["ok"] and out["cutoff"]["after"] < out["cutoff"]["before"] and out["probation"]["probation_left"] > 0

        @T("5", "Self-recovery: next invoice short-paid by the credit; recovery returned to the reserve", "mistake_recovery")
        def _(ev):
            pool_before = self.ch.state()["pool_balance_usd"]
            r = self.s.ingest("t05_next_invoice")
            ev.add("next Shatin PCB bill (probation: goes to a person)", "agent", r, None, "T2, net of receivable")
            a = self.ag.approve(r["bill"])
            b = self.ag.led.bills[r["bill"]]
            ev.add("manager approves the proposed amount", "finance_manager", a, _tx(a))
            for o in b.offsets:
                ev.add("offset recorded on-chain", "agent", o, o["tx"])
            pool_after = self.ch.state()["pool_balance_usd"]
            ev.add("reserve balance", "contract", {"before": pool_before, "after": pool_after})
            return r["tier"] == "T2" and a.get("tx", {}).get("ok") and pool_after > pool_before

        @T("6", "Bank-detail change by message: the agent freezes the supplier itself", "attack_defence")
        def _(ev):
            r = self.ag.receive_email((demo.INBOX_DIR / "lionrock_bank_change.eml").read_text())
            ev.add("email from Lion Rock's registered domain", "agent", {"supplier": r["supplier"], "class": r["class"]}, None)
            lk = self.ag.receive_email((demo.INBOX_DIR / "lookalike_sender.eml").read_text())
            ev.add("email from a look-alike domain", "agent", {"action": lk["action"]}, None, "logged only")
            ev.add("freeze payee on-chain with the agent key", "agent", r.get("freeze"), _tx(r.get("freeze")), "PayeeFrozen")
            return r["class"] == "bank_change" and self.ch.payee("LIONROCK")["frozen"]

        @T("9", "Direct call from a non-agent key", "attack_defence")
        def _(ev):
            sid = self.ch.state()["settings_id"]
            exp = self.ch.now() + 600
            ih = input_hash({"attack": "direct"})
            sig = self.ch.gov_signature("ATTACK-9", "ACME", 1000.0, sid, exp, ih)
            tx = self.ch.pay_autonomous("ATTACK-9", "ACME", 1000.0, sid, exp, ih, sig, caller="attacker", mine_revert=True)
            ev.add("payAutonomous from an outside key, even with a valid governor signature", "attacker", {"error": tx.error}, tx.tx_hash, "revert NotAuthorized")
            return not tx.ok and tx.tx_hash is not None and tx.error == "NotAuthorized"

        @T("10", "Agent key with no governor signature (hacked server)", "attack_defence")
        def _(ev):
            sid = self.ch.state()["settings_id"]
            exp = self.ch.now() + 600
            ih = input_hash({"attack": "no governor"})
            sig = self.ch.gov_signature("ATTACK-10", "ACME", 4900.0, sid, exp, ih, role="agent")  # self-signed
            tx = self.ch.pay_autonomous("ATTACK-10", "ACME", 4900.0, sid, exp, ih, sig, mine_revert=True)
            ev.add("payAutonomous signed by the agent key itself", "agent_key", {"error": tx.error}, tx.tx_hash, "revert BadSignature")
            return not tx.ok and tx.tx_hash is not None and tx.error == "BadSignature"

        @T("14", "Three blocked attempts: the agent pauses itself; owner unpauses", "attack_defence")
        def _(ev):
            from .policies import ToolCall
            from .tags import Src, T as Tg
            for i in range(3):
                pol = self.ag._gate(ToolCall("pay_autonomous", {"payee": Tg.of("0xdead", Src.SUPPLIER_MSG),
                                                                 "amount": Tg.of(4999.0, Src.SUPPLIER_MSG)}))
                ev.add(f"blocked attempt {i + 1}", "policy_gate", {"policy": pol})
            paused = self.ch.state()["agent_paused"]
            pause_line = next((l for l in reversed(self.ag.log.lines) if l.kind == "pause_self"), None)
            ev.add("circuit breaker", "agent", {"paused": paused}, pause_line.tx_hash if pause_line else None, "AgentPaused")
            r = self.s.ingest("t21_3", auto_pay=True)  # a routine bill while paused goes to a person
            ev.add("routine bill while paused", "agent", r, None, "T2")
            un = self.ag.resume()
            ev.add("owner unpauses", "owner", un, _tx(un))
            self.bills["t21_3_paused"] = r["bill"]
            return paused and r["tier"] == "T2" and not self.ch.state()["agent_paused"]

        @T("20", "Vague request 'pay the copper supplier': one question, answer, plan", "control")
        def _(ev):
            for k in ("t19_acme_0", "t19_acme_1", "t19_acme_2", "t16_fair_price"):
                r = self.s.ingest(k, process=False)
                self.bills[k] = r["bill"]
            q = self.s.request("Pay the copper supplier")
            ev.add("request", "owner", {"kind": q["kind"], "question": q["route"].get("question")})
            if q["kind"] != "question":
                return False
            p = self.s.answer(q["id"], "ACME")
            ev.add("owner taps ACME; plan preview", "agent", {"summary": p["plan"]["summary"],
                                                                "steps": [(s["bill"], s["tier"], s["status"]) for s in p["plan"]["steps"]]})
            self.bills["plan20"] = p["plan"]["plan_id"]
            return len(q["route"]["question"]["options"]) >= 2 and p["kind"] == "plan"

    # ================================================================== day 2
    def day2(self) -> None:
        T = self.task
        self.s.next_day()

        @T("1b", "Reserve for the task-1 payment released after the window", "routine")
        def _(ev):
            tx = self.ch.release(self.bills["t01"])
            ev.add("release after P-WINDOW with no claim", "anyone (agent key)", {"ok": tx.ok}, tx.tx_hash, "Released")
            return tx.ok

        @T("19", "Owner types 'pay everything from Acme due this week except the disputed bill'", "control")
        def _(ev):
            p = self.s.request("Pay everything from Acme due this week except the disputed bill")
            plan = p["plan"]
            ev.add("plan preview", "agent", {"summary": plan["summary"], "steps": [(s["bill"], s["tier"], s["status"], s["reason"]) for s in plan["steps"]]})
            done = self.s.run(plan["plan_id"])
            for s in done["steps"]:
                ev.add(f"step {s['n']} {s['kind']}", "agent" if s["tier"] == "T1" else "agent", {"status": s["status"], "tier": s["tier"]},
                       _tx(s["result"]))
            paid = [s for s in done["steps"] if s["status"] == "done"]
            skipped = [s for s in done["steps"] if s["status"] == "skipped"]
            return len(paid) == 3 and len(skipped) >= 1

        @T("16", "Fair price: copper rod +9% vs index; hold excess; query; credit note; paid at justified price", "routine")
        def _(ev):
            bid = self.bills["t16_fair_price"]
            r = self.ag.process(bid)
            b = self.ag.led.bills[bid]
            ev.add("fair-price check", "agent", {"fair_price": b.fair_price, "resolution": b.resolution}, None, "T2")
            q = self.ag.draft_query(bid, "price")
            ev.add("query drafted", "agent", {"to": q["to"], "body": q["body"]})
            self.ag.send_query(q["id"])
            ev.add("sent with one tap", "finance_manager", {"query": q["id"]})
            # Acme's reply by email, quoting our reference; its fields are read from the text.
            acme = self.ag.led.suppliers["ACME"]
            reply = (f"From: Acme Accounts <{acme.contact}>\nSubject: Re: {q['subject']}\n\n"
                     f"Thank you for your query {q['id']}. We agree the rod price should follow the index. "
                     f"Credit note CN-7781 for USD {b.fair_price['overcharge']:,.2f} is attached.\n")
            (EVIDENCE_DIR / "acme_reply.eml").write_text(reply)  # kept with the evidence, not in the inbox
            out = self.ag.receive_email(reply)
            ev.add("supplier reply by email: classified, fields read from the text", "agent", out)
            a = self.ag.approve(bid)
            ev.add("paid at the justified price", "finance_manager", a, _tx(a))
            return r["tier"] == "T2" and out["class"] == "credit_note" and a.get("tx", {}).get("ok") and a["amount"] < b.read.total

        @T("3", "Owner types 'be more careful this month'; owner signs; new limits on-chain", "control")
        def _(ev):
            p = self.s.request("Be more careful this month")
            plan = p["plan"]
            ev.add("plan preview", "agent", {"summary": plan["summary"]})
            out = self.s.sign_settings(plan["plan_id"])
            ev.add("owner signs the settings", "owner", out.get("propose_tx"), (out.get("propose_tx") or {}).get("tx_hash"))
            ev.add("underwriter co-signs (bonded)", "underwriter", out.get("approve_tx"), (out.get("approve_tx") or {}).get("tx_hash"))
            st = self.ch.state()
            ev.add("on-chain settings", "contract", {k: st[k] for k in ("settings_id", "mode", "p_day_usd", "p_nday", "r_usd")})
            return st["p_nday"] == 3 and self.ag.gov.bundle_name == "careful"

        @T("18", "Switch to standard mode; payments run with caps only; switch back", "control")
        def _(ev):
            prop = self.ag.propose_bundle("standard", mode="standard")
            out = self.ag.apply_bundle(prop)
            ev.add("owner switches to standard mode", "owner", {"mode": out["state"]["mode"]}, out["propose_tx"]["tx_hash"])
            r = self.s.ingest("t21_0")
            ev.add("routine bill in standard mode (no reserve lock)", "agent", r, _tx(r))
            locked = self.ch.pool.functions.locks(__import__("apagent.chain", fromlist=["b32"]).b32(r["bill"])).call()[1]
            back = self.ag.apply_bundle(self.ag.propose_bundle("standard", mode="bonded"))
            ev.add("owner switches back to bonded", "owner", {"mode": back["state"]["mode"]}, back["propose_tx"]["tx_hash"])
            ev.add("underwriter co-signs", "underwriter", {}, back["approve_tx"]["tx_hash"])
            return out["state"]["mode"] == "standard" and r["tier"] == "T1" and locked == 0 and back["state"]["mode"] == "bonded"

    # ================================================================== day 3
    def day3(self) -> None:
        T = self.task
        self.s.next_day()

        @T("12", "One large bill split into ten: later parts go to T2; a forced T1 hits P-SUPWEEK", "attack_defence")
        def _(ev):
            tiers = []
            for i in range(10):
                r = self.s.ingest(f"t12_split_{i}")
                tiers.append(r["tier"])
                self.bills[f"t12_{i}"] = r["bill"]
            amounts = [self.ag.led.bills[self.bills[f"t12_{i}"]].amount_usd for i in range(10)]
            ev.add("one $16,000 order billed as ten parts of about $1,600", "agent", {"tiers": tiers, "amounts": amounts})
            # Force a T1 on one of the held parts, as a compromised app would: the contract refuses.
            held = next(self.bills[f"t12_{i}"] for i in range(10) if tiers[i] == "T2")
            b = self.ag.led.bills[held]
            d = Decision("T1", [], "routine", 0.1, 0.5, b.amount_usd)
            ih = input_hash(self.ag.bill_input(b))
            self.ag.gov.sign(d, held, "KWONGFAT", self.ch.state()["settings_id"], ih)
            tx = self.ch.pay_autonomous(held, "KWONGFAT", d.amount, d.settings_id, d.expiry, ih, d.signature, mine_revert=True)
            ev.add("forced T1 on a held part", "agent_key", {"error": tx.error}, tx.tx_hash, "revert OverSupplierWeek")
            return "T2" in tiers and tiers[0] == "T1" and not tx.ok and tx.error == "OverSupplierWeek"

    # ================================================================== day 4
    def day4(self) -> None:
        T = self.task
        self.s.next_day()

        @T("21", "Owner cancels a running five-payment plan after two payments", "control")
        def _(ev):
            for k in ("t21_1", "t21_2", "t21_4"):
                self.s.ingest(k, process=False)
            b = self.ag.led.bills[self.bills["t21_3_paused"]]
            b.status, b.tier = "received", None  # re-check the bill that was held while paused
            p = self.s.request("pay everything due this month")
            plan = p["plan"]
            pays = [s for s in plan["steps"] if s["kind"] == "pay" and s["tier"] == "T1"]
            ev.add("plan preview", "agent", {"summary": plan["summary"], "t1_steps": len(pays)})
            done = self.s.run(plan["plan_id"], cancel_after=2)
            for s in done["steps"]:
                ev.add(f"step {s['n']}", "agent", {"status": s["status"], "bill": s["bill"]}, _tx(s["result"]))
            ev.add("plan status", "owner", {"status": done["status"]})
            n_done = sum(s["status"] == "done" for s in done["steps"])
            n_stop = sum(s["status"] == "stopped" for s in done["steps"])
            return done["status"] == "cancelled" and n_done == 2 and n_stop >= 1

        @T("11", "Pool too small: T1 reverts, approval card, paid", "control")
        def _(ev):
            r = self.s.ingest("t11_pool", process=False)
            cand = self.ag.led.bills[r["bill"]]
            d = self.ag.process(cand.bill_id, auto_pay=False)  # governor decides T1 on the current pool state
            ev.add("governor decides T1 and signs", "governor", d)
            st = self.ch.state()
            free = st["pool_free_usd"]
            w = self.ch.pool_withdraw(round(free - 1000, 2))
            ev.add("underwriter withdraws free capital", "underwriter", {"free_before": free}, w.tx_hash)
            p = self.ag.pay_t1(cand.bill_id)
            ev.add("T1 attempt", "agent", p, None, "contract refuses: reserve too small")
            a = self.ag.approve(cand.bill_id)
            ev.add("approval card, manager approves, paid", "finance_manager", a, _tx(a))
            f = self.ch.pool_fund(round(free - 1000, 2))
            u = self.ch.pool_unpause()
            ev.add("underwriter tops up and unpauses", "underwriter", {"unpause_ok": u.ok}, f.tx_hash)
            return d.get("tier") == "T1" and p.get("tier") == "T2" and a.get("tx", {}).get("ok")

        @T("anchor", "Daily Merkle root of the decision log anchored on-chain", "control")
        def _(ev):
            a = self.ag.anchor_day(int(time.time() // 86400) + len(self.out))
            ev.add("anchor", "agent", {"root": a["root"]}, _tx(a))
            return a["tx"]["ok"]

    # ================================================================== output
    def write(self) -> dict:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        dep = self.ch.dep
        doc = {"network": self.network, "chain_id": self.ch.chain_id, "contracts": dep["contracts"], "roles": dep["roles"],
               "deploy_txs": dep["txs"], "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
               "tasks": [e.__dict__ for e in self.out], "money": self.ag.money,
               "summary": {"passed": sum(e.ok for e in self.out), "total": len(self.out)}}
        (EVIDENCE_DIR / f"evidence_{self.network}.json").write_text(json.dumps(doc, indent=1, default=str))
        (EVIDENCE_DIR / f"decision_log_{self.network}.json").write_text(json.dumps(self.ag.log.to_json(10_000), indent=1, default=str))
        (EVIDENCE_DIR / f"evidence_{self.network}.md").write_text(render_md(doc, self.ch))
        return doc


def render_md(doc: dict, ch) -> str:
    lines = [f"# Execution evidence ({doc['network']}, chain {doc['chain_id']})", "",
             f"Generated {doc['generated']}. Passed {doc['summary']['passed']} of {doc['summary']['total']} tasks.", "",
             "## Contracts", ""] + [f"- {k}: `{v}`" for k, v in doc["contracts"].items()] + [""]
    for story, title in [("routine", "Routine operations"), ("mistake_recovery", "Mistake and recovery"),
                         ("attack_defence", "Attacks and defence"), ("control", "Owner control")]:
        lines += [f"## {title}", ""]
        for t in [t for t in doc["tasks"] if t["story"] == story]:
            lines += [f"### Task {t['task']}: {t['title']} ({'pass' if t['ok'] else 'FAIL'})", "",
                      "| Time | Actor | Action | Transaction |", "| --- | --- | --- | --- |"]
            for s in t["steps"]:
                if "action" not in s:
                    continue
                tx = s.get("tx_hash")
                link = ch.explorer(tx) if tx else None
                txs = f"[`{tx[:18]}…`]({link})" if link else (f"`{tx}`" if tx else "log")
                lines.append(f"| {s['time']} | {s['actor']} | {s['action']} | {txs} |")
            lines.append("")
    lines += ["## How to check", "", "Each hash can be looked up on the chain's explorer (Base Sepolia: sepolia.basescan.org). "
              "Reverted transactions show the custom error that refused them. The full decision log is in "
              f"`decision_log_{doc['network']}.json`; its daily Merkle root is anchored by EvidenceAnchor."]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", default="localhost")
    a = ap.parse_args()
    r = Runner(a.network)
    if a.network in DEMO_CLOCK:
        r.ch.advance(r.ch.cool_down + 1)  # payee cool-down (on FISCO and Base Sepolia this waits)
    for day in (r.day1, r.day2, r.day3, r.day4):
        day()
    doc = r.write()
    print(f"\n{doc['summary']['passed']}/{doc['summary']['total']} tasks passed. Evidence in evidence/evidence_{a.network}.md")


if __name__ == "__main__":
    main()
