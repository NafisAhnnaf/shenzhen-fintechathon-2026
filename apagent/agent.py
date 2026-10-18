"""The payables agent (plan 3.2, 3.3, 3.7).

Every bill: reader -> injection flag -> checker -> governor -> T1 (governor co-signs, contract checks) or
T2 (approval card with a proposed resolution). The agent also reconciles supplier statements, files claims
with the manager's signature, recovers overpayments from the next invoice, runs the supplier query, and
takes protective actions (freeze, pause, probation) on its own.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import date, timedelta
from typing import Optional

from . import checker, injection, policies
from .audit import AuditLog, input_hash
from .chain import Chain
from .config import SETTINGS, Settings
from .domain import Bill, Case, Ledger, Read, Receivable
from .governor import Decision, Governor
from .policies import PolicyViolation, ToolCall
from .risk.calibrate import Calibration
from .tags import Src, T

CAUSE = {"overpayment": 1, "duplicate": 2, "wrong_payee": 3}


class Agent:
    def __init__(self, ledger: Ledger, calib: Calibration, chain: Optional[Chain] = None,
                 cfg: Settings = SETTINGS, log: Optional[AuditLog] = None):
        self.led = ledger
        self.cfg = cfg
        self.chain = chain
        self.log = log or AuditLog()
        self.gov = Governor(calib, cfg, chain)
        self.cal = calib
        self.erp = None  # set by the session: where payments are recorded back (see apagent/erp)
        self.n_bills = 0
        self.n_plans = 0
        self._pending_bundle: dict = {}
        self.queries: dict[str, dict] = {}
        self.money = {"discounts_taken": 0.0, "overcharges_held": 0.0, "duplicates_blocked": 0.0,
                      "recovered": 0.0, "claims_paid": 0.0, "attacks_blocked": 0, "t1_paid": 0.0, "t1_count": 0,
                      "t2_paid": 0.0, "t2_count": 0}
        self.checks: dict[str, checker.CheckResult] = {}
        self.decisions: dict[str, Decision] = {}

    # ================================================================== helpers
    def _chain_state(self) -> Optional[dict]:
        return self.chain.state() if self.chain else None

    def _tx(self, res) -> dict:
        return {"ok": res.ok, "tx_hash": res.tx_hash, "error": res.error,
                "explorer": self.chain.explorer(res.tx_hash) if self.chain else None}

    def _gate(self, call: ToolCall, bill_id: Optional[str] = None, plan_id: Optional[str] = None) -> Optional[str]:
        """Run the policy gate. Returns the violated policy, or None if allowed."""
        try:
            policies.check(call)
            return None
        except PolicyViolation as e:
            self.log.add("system", "policy_block", {"tool": call.tool, "reason": e.msg}, policy=e.policy,
                         bill_id=bill_id, plan_id=plan_id, decision="blocked", security=True)
            self.money["attacks_blocked"] += 1
            self._blocked()
            return e.policy

    def _blocked(self) -> None:
        if self.gov.blocked_attempt():
            self.pause_self("Circuit breaker: repeated blocked attempts")

    def bill_input(self, bill: Bill) -> dict:
        r = bill.read
        return {"inv_no": r.inv_no, "supplier": bill.supplier_id, "po": r.po_id, "total": r.total, "credit": r.credit,
                "lines": [(l.item, l.qty, l.price) for l in r.lines], "amount": bill.amount_usd}

    # ================================================================== intake and processing
    def intake(self, read: Read, source: str = "pdf", bill_id: Optional[str] = None) -> Bill:
        self.n_bills += 1
        bid = bill_id or f"B-{self.led.today.replace('-', '')}-{self.n_bills:04d}"
        bill = Bill(bill_id=bid, received=self.led.today, source=source, read=read)
        self.led.bills[bid] = bill
        self.log.add("agent", "intake", {"source": source, "inv_no": read.inv_no, "total": read.total}, bill_id=bid)
        return bill

    def process(self, bill_id: str, auto_pay: bool = True, plan_id: Optional[str] = None) -> dict:
        bill = self.led.bills[bill_id]
        inj = injection.score(bill.read.raw_text)
        bill.injection_p = inj["p"]
        if inj["p"] >= self.cfg.injection_threshold:
            self.log.add("agent", "injection_flag", {"p": inj["p"], "decoded": inj["decoded"]}, bill_id=bill_id,
                         decision="T2", security=True)
            self.money["attacks_blocked"] += 1
        res = checker.check(self.led, bill, self.cfg)
        self.checks[bill_id] = res
        bill.supplier_id = res.supplier.id if res.supplier else None
        bill.group = res.group
        bill.erp_bound = res.erp_bound.value
        bill.amount_usd = res.amount.value
        bill.resolution = res.resolution
        bill.fair_price = next((f.to_json() for f in res.fair if f.flagged), None)
        if bill.fair_price:
            self.money["overcharges_held"] += bill.fair_price["overcharge"]

        # Protective actions the agent takes itself (S10: only against this bill's supplier).
        if "bank_change" in res.codes and res.supplier:
            self.freeze_supplier(res.supplier.id, "Bank details on a bill differ from the registry", trigger=res.supplier.id)
            self.open_case("bank_change", res.supplier.id, {"bill": bill_id, "callback": res.supplier.contact})

        d = self.gov.decide(self.led, bill, res, inj["p"], self.led.today, self._chain_state())
        self.decisions[bill_id] = d
        bill.tier, bill.score, bill.reasons = d.tier, d.score, d.reasons
        self.log.add("governor", "decision", {"tier": d.tier, "score": d.score, "cutoff": d.cutoff, "group": d.group,
                                               "reasons": d.reasons, "amount": d.amount}, bill_id=bill_id,
                     plan_id=plan_id, decision=d.tier)
        if d.tier == "reject":
            bill.status = "rejected"
            self.money["duplicates_blocked"] += bill.read.total
            return {"bill": bill_id, "tier": "reject", "reasons": d.reasons}
        if d.tier == "hold":
            bill.status = "held"
            bill.hold_reason = d.reasons[0]
            return {"bill": bill_id, "tier": "hold", "reasons": d.reasons}
        if d.tier == "T2":
            bill.status = "held"
            return {"bill": bill_id, "tier": "T2", "reasons": d.reasons, "resolution": bill.resolution}
        if auto_pay:
            return self.pay_t1(bill_id, plan_id=plan_id)
        bill.status = "approved"
        return {"bill": bill_id, "tier": "T1", "reasons": d.reasons, "amount": d.amount}

    # ================================================================== payments
    def pay_t1(self, bill_id: str, plan_id: Optional[str] = None, from_request: bool = False,
               confirmed: bool = False) -> dict:
        bill = self.led.bills[bill_id]
        d = self.decisions[bill_id]
        res = self.checks[bill_id]
        if d.tier != "T1":
            return {"bill": bill_id, "tier": d.tier, "reasons": d.reasons, "error": "not a T1 decision"}
        call = ToolCall("pay_autonomous", {"payee": T.of(bill.supplier_id, Src.REGISTRY), "amount": res.amount},
                        plan_confirmed=confirmed, from_request=from_request)
        if self._gate(call, bill_id, plan_id):
            bill.status = "held"
            return {"bill": bill_id, "tier": "T2", "reasons": ["Policy gate refused the payment"]}
        ih = input_hash(self.bill_input(bill))
        tx = None
        if self.chain:
            cs = self.chain.state()
            self.gov.sign(d, bill_id, bill.supplier_id, cs["settings_id"], ih)
            tx = self.chain.pay_autonomous(bill_id, bill.supplier_id, d.amount, d.settings_id, d.expiry, ih, d.signature)
            if not tx.ok:
                self.log.add("contract", "revert", {"error": tx.error}, bill_id=bill_id, plan_id=plan_id,
                             tx_hash=tx.tx_hash, decision="T2", security=True)
                self._blocked()
                bill.status = "held"
                bill.tier = "T2"
                bill.reasons = bill.reasons + [f"Contract refused the autonomous payment: {tx.error}"]
                return {"bill": bill_id, "tier": "T2", "reasons": bill.reasons, "revert": tx.error}
        self._mark_paid(bill, "T1", tx.tx_hash if tx else None)
        self.gov.record_t1(bill.supplier_id, d.amount, self.led.today)
        self.money["t1_paid"] += d.amount
        self.money["t1_count"] += 1
        self.log.add("contract", "pay_autonomous", {"amount": d.amount, "supplier": bill.supplier_id,
                                                     "premium": d.premium}, bill_id=bill_id, plan_id=plan_id,
                     input_hash="0x" + ih.hex(), decision="paid", tx_hash=bill.tx_hash)
        return {"bill": bill_id, "tier": "T1", "amount": d.amount, "tx": self._tx(tx) if tx else None}

    def approval_amount(self, bill_id: str, amount: Optional[float] = None) -> float:
        """The amount a T2 approval pays: the proposed resolution, or an edited amount, never above erp_bound."""
        bill = self.led.bills[bill_id]
        proposed = bill.resolution["amount"] if bill.resolution else bill.amount_usd
        usd = proposed if amount is None else amount
        return round(max(0.0, min(usd, bill.erp_bound)), 2)

    def approval_request(self, bill_id: str, amount: Optional[float] = None, ttl: int = 900) -> dict:
        """What the finance manager signs in their wallet for a T2 payment (EIP-712 PaymentApproval)."""
        bill = self.led.bills[bill_id]
        usd = self.approval_amount(bill_id, amount)
        exp = self.chain.now() + ttl
        return {"bill": bill_id, "amount": usd, "expiry": exp, "signer": self.chain.role_address("approver"),
                "typed_data": self.chain.typed_data(self.chain._pay_msg(bill_id, bill.supplier_id, usd, exp))}

    def approve(self, bill_id: str, amount: Optional[float] = None, actor: str = "finance_manager",
                plan_id: Optional[str] = None, signature: Optional[bytes] = None, expiry: Optional[int] = None) -> dict:
        """T2: the finance manager approves the proposed resolution (or an edited amount, never above erp_bound).

        signature/expiry come from the manager's wallet (approval_request). Without them the server signs with the
        approver key, which only works when this process holds that key (SIGNING=server).
        """
        bill = self.led.bills[bill_id]
        if bill.status not in ("held", "received", "approved"):
            return {"bill": bill_id, "error": f"bill is {bill.status}"}
        if not bill.supplier_id:
            return {"bill": bill_id, "error": "no registered supplier"}
        usd = self.approval_amount(bill_id, amount)
        amt = T.of(usd, Src.ERP_BOUNDED)
        call = ToolCall("pay_approved", {"payee": T.of(bill.supplier_id, Src.REGISTRY), "amount": amt})
        if self._gate(call, bill_id, plan_id):
            return {"bill": bill_id, "error": "policy gate refused"}
        tx = None
        if self.chain:
            if signature is None:
                if not self.chain.has_key("approver"):
                    return {"bill": bill_id, "error": "needs the finance manager's signature", "needs_signature": True}
                expiry = self.chain.now() + 900
                signature = self.chain.approval_signature(bill_id, bill.supplier_id, usd, expiry)
            elif self.chain.recover(self.chain._pay_msg(bill_id, bill.supplier_id, usd, expiry), signature) != self.chain.role_address("approver"):
                self.log.add("system", "bad_signature", {"for": "pay_approved"}, bill_id=bill_id, security=True)
                return {"bill": bill_id, "error": "signature is not the finance manager's for this bill and amount"}
            tx = self.chain.pay_approved(bill_id, bill.supplier_id, usd, expiry, signature)
            if not tx.ok:
                self.log.add("contract", "revert", {"error": tx.error}, bill_id=bill_id, plan_id=plan_id, decision="refused")
                return {"bill": bill_id, "error": tx.error}
        bill.amount_usd = usd
        self._mark_paid(bill, "T2", tx.tx_hash if tx else None)
        self.money["t2_paid"] += usd
        self.money["t2_count"] += 1
        self.log.add(actor, "approve", {"amount": usd}, bill_id=bill_id, plan_id=plan_id, decision="approved")
        self.log.add("contract", "pay_approved", {"amount": usd, "supplier": bill.supplier_id}, bill_id=bill_id,
                     plan_id=plan_id, decision="paid", tx_hash=bill.tx_hash)
        return {"bill": bill_id, "tier": "T2", "amount": usd, "tx": self._tx(tx) if tx else None}

    def reject(self, bill_id: str, actor: str = "finance_manager") -> dict:
        bill = self.led.bills[bill_id]
        bill.status = "rejected"
        self.log.add(actor, "reject", {}, bill_id=bill_id, decision="rejected")
        return {"bill": bill_id, "status": "rejected"}

    def _mark_paid(self, bill: Bill, tier: str, tx_hash: Optional[str]) -> None:
        bill.status = "paid"
        bill.tier = tier
        bill.tx_hash = tx_hash
        bill.paid_on = self.led.today
        sup = self.led.suppliers[bill.supplier_id]
        sup.bills_paid += 1
        if tier == "T2" and sup.probation_left > 0:
            sup.probation_left -= 1
        self.led.cash_usd -= bill.amount_usd
        if bill.read.terms == "2/10net30":
            days = (date.fromisoformat(self.led.today) - date.fromisoformat(bill.read.date)).days
            if days <= 10:
                self.money["discounts_taken"] += round(0.02 * bill.amount_usd, 2)
        # Recovery: an open receivable deducted from this bill is recorded as an offset.
        ded = self.checks.get(bill.bill_id).deductions.get("open_receivable") if bill.bill_id in self.checks else None
        if ded:
            self._record_offsets(bill, ded)
        self._post_to_erp(bill, tier, tx_hash)

    def _post_to_erp(self, bill: Bill, tier: str, tx_hash: Optional[str]) -> None:
        """Record the payment in the company's ERP. The payment has already settled on-chain, so a failure here is
        logged and flagged for reconciliation, never undone."""
        if self.erp is None:
            return
        from .erp import PaymentRecord

        rec = PaymentRecord(bill.bill_id, bill.supplier_id, bill.read.inv_no, bill.read.po_id, bill.amount_usd,
                            self.led.today, tx_hash, tier, self.chain.network if self.chain else "offline")
        try:
            ref = self.erp.record_payment(rec)
            bill.erp_ref = ref
            self.log.add("agent", "erp_payment", {"erp": self.erp.name, "ref": ref}, bill_id=bill.bill_id)
        except Exception as e:  # noqa: BLE001 - any ERP failure must not lose the record of the payment
            bill.erp_ref = None
            self.log.add("agent", "erp_payment_failed", {"erp": self.erp.name, "error": str(e)[:300]},
                         bill_id=bill.bill_id, security=False)

    # ================================================================== protective actions (P tier)
    def freeze_supplier(self, supplier_id: str, reason: str, trigger: Optional[str] = None) -> dict:
        call = ToolCall("freeze", {"supplier": T.of(supplier_id, Src.REGISTRY)}, trigger_supplier=trigger)
        if self._gate(call):
            return {"error": "policy"}
        self.led.suppliers[supplier_id].frozen = True
        tx = self.chain.freeze(supplier_id) if self.chain else None
        self.log.add("agent", "freeze_payee", {"supplier": supplier_id, "reason": reason}, decision="frozen",
                     tx_hash=tx.tx_hash if tx else None, security=True)
        return {"supplier": supplier_id, "frozen": True, "tx": self._tx(tx) if tx else None}

    def unfreeze_supplier(self, supplier_id: str, tx_hash: Optional[str] = None) -> dict:
        """Owner only (T3). tx_hash: the owner sent unfreezePayee from their wallet; else the server key sends it."""
        tx = None
        if self.chain:
            tx = self._owner_tx(self.chain.vault.functions.unfreezePayee(__import__("apagent.chain", fromlist=["b32"]).b32(supplier_id)),
                                tx_hash, self.chain.unfreeze, supplier_id)
            if not tx.ok:
                return {"supplier": supplier_id, "error": tx.error, "needs_signature": tx.error == "needs the owner's wallet"}
        self.led.suppliers[supplier_id].frozen = False
        self.log.add("owner", "unfreeze_payee", {"supplier": supplier_id}, tx_hash=tx.tx_hash if tx else None)
        return {"supplier": supplier_id, "frozen": False, "tx": self._tx(tx) if tx else None}

    def _owner_tx(self, fn, tx_hash: Optional[str], server_call, *args):
        """An owner transaction: verify the one the owner sent, or send it with the server's owner key if held."""
        from .chain import TxResult
        if tx_hash:
            return self.chain.verify_sent(tx_hash, "owner", self.chain.vault)
        if self.chain.has_key("owner"):
            return server_call(*args)
        return TxResult(False, None, "needs the owner's wallet")

    def owner_tx_request(self, action: str, **kw) -> dict:
        """Unsigned transaction for the owner's wallet: unpause, unfreeze, settings."""
        from .chain import b32
        v = self.chain.vault.functions
        fn = {"unpause": lambda: v.unpauseAgent(),
              "unfreeze": lambda: v.unfreezePayee(b32(kw["supplier"]))}[action]()
        return {"action": action, "tx": self.chain.prepare("owner", fn)}

    def pause_self(self, reason: str) -> dict:
        tx = self.chain.pause_agent("agent") if self.chain else None
        self.log.add("agent", "pause_self", {"reason": reason}, decision="paused",
                     tx_hash=tx.tx_hash if tx else None, security=True)
        return {"paused": True, "tx": self._tx(tx) if tx else None}

    def resume(self, tx_hash: Optional[str] = None) -> dict:
        """Owner only (T3): unpause."""
        tx = None
        if self.chain:
            tx = self._owner_tx(None, tx_hash, self.chain.unpause_agent)
            if not tx.ok:
                return {"paused": True, "error": tx.error, "needs_signature": tx.error == "needs the owner's wallet"}
        self.gov.state.blocked.clear()
        self.log.add("owner", "unpause", {}, tx_hash=tx.tx_hash if tx else None)
        return {"paused": False, "tx": self._tx(tx) if tx else None}

    def hold(self, bill_id: str, reason: str, plan_id: Optional[str] = None) -> dict:
        bill = self.led.bills[bill_id]
        if bill.status in ("paid", "rejected"):
            return {"bill": bill_id, "skipped": bill.status}
        bill.status = "held"
        bill.hold_reason = reason
        self.log.add("agent", "hold", {"reason": reason}, bill_id=bill_id, plan_id=plan_id, decision="held")
        return {"bill": bill_id, "held": True}

    def probation(self, supplier_id: str, n: Optional[int] = None, reason: str = "") -> dict:
        sup = self.led.suppliers[supplier_id]
        sup.probation_left = max(sup.probation_left, n or self.cfg.probation_bills)
        self.log.add("agent", "probation", {"supplier": supplier_id, "bills": sup.probation_left, "reason": reason})
        return {"supplier": supplier_id, "probation_left": sup.probation_left}

    # ================================================================== cases, reconciliation, claims, recovery
    def open_case(self, kind: str, supplier_id: str, detail: dict) -> Case:
        cid = f"C-{len(self.led.cases) + 1:04d}"
        c = Case(cid, kind, supplier_id, "open", detail, self.led.today)
        self.led.cases[cid] = c
        self.log.add("agent", "case_open", {"kind": kind, **detail}, decision="open")
        return c

    def reconcile(self, supplier_id: str, statement: list[dict]) -> list[Case]:
        """Match each statement line to the ledger. Every unmatched credit or charge opens a case."""
        paid = {b.read.inv_no: b for b in self.led.bills.values() if b.supplier_id == supplier_id and b.status == "paid"}
        gross = {l["ref"]: l["amount"] for l in statement if l["kind"] == "invoice"}
        cases = []
        for line in statement:
            if line["kind"] == "invoice":
                if not any(b.read.inv_no == line["ref"] for b in self.led.bills.values()):
                    cases.append(self.open_case("unmatched_charge", supplier_id, {"statement_line": line}))
                continue
            if line["kind"] != "credit":
                continue
            against = paid.get(line.get("against", ""))
            if against is None:
                cases.append(self.open_case("unmatched_credit", supplier_id, {"statement_line": line}))
                continue
            # What we owed per the statement vs what we paid. Paying less for other reasons is not a case.
            inv_gross = gross.get(against.read.inv_no, round(sum(l.amount for l in against.read.lines), 2))
            owed = round(inv_gross - abs(line["amount"]), 2)
            overpaid = round(against.amount_usd - owed, 2)
            if overpaid > 0.01:
                cases.append(self.open_case("missed_credit", supplier_id, {
                    "statement_line": line, "bill": against.bill_id, "amount": min(overpaid, abs(line["amount"])),
                    "paid": against.amount_usd, "owed": owed, "tier": against.tier, "tx_hash": against.tx_hash}))
        self.log.add("agent", "reconcile", {"supplier": supplier_id, "lines": len(statement), "cases": [c.case_id for c in cases]})
        return cases

    def _claim_needed(self, bill: Bill) -> bool:
        return bool(self.chain) and bill.tier == "T1" and self.chain.state()["mode"] != "standard"

    def claim_evidence(self, bill_id: str, amount: float, cause: str = "overpayment") -> bytes:
        """Deterministic evidence hash for a claim: the bill, the amount, the cause and the cases behind it."""
        return input_hash({"bill": bill_id, "amount": amount, "cause": cause, "cases": sorted(
            c.case_id for c in self.led.cases.values() if c.detail.get("bill") == bill_id)})

    def case_signing_request(self, case_id: str, ttl: int = 3600) -> dict:
        """What the finance manager signs to confirm a missed credit: the receivable and, if the reserve covers
        the payment, the claim. Both are EIP-712 messages for their wallet."""
        c = self.led.cases[case_id]
        bill = self.led.bills[c.detail["bill"]]
        amount = c.detail["amount"]
        exp = self.chain.now() + ttl
        out = {"case": case_id, "amount": amount, "expiry": exp, "signer": self.chain.role_address("approver"),
               "receivable": self.chain.typed_data(self.chain._recv_msg(bill.bill_id, amount, exp))}
        if self._claim_needed(bill):
            ev = self.claim_evidence(bill.bill_id, amount)
            out["claim"] = self.chain.typed_data(self.chain._claim_msg(bill.bill_id, amount, CAUSE["overpayment"], ev, exp))
        return out

    def confirm_case(self, case_id: str, actor: str = "finance_manager", receivable_sig: Optional[bytes] = None,
                     claim_sig: Optional[bytes] = None, expiry: Optional[int] = None) -> dict:
        """The manager confirms. For a missed credit: receivable, claim (reserve modes, T1 only), cut-off drop,
        probation. Recovery happens on the supplier's next bill. Signatures come from the manager's wallet
        (case_signing_request); without them the server signs only if it holds the approver key."""
        c = self.led.cases[case_id]
        out: dict = {"case": case_id}
        if c.kind != "missed_credit":
            c.status = "confirmed"
            self.log.add(actor, "case_confirm", {"case": case_id, "kind": c.kind})
            return out
        bill = self.led.bills[c.detail["bill"]]
        amount = c.detail["amount"]
        if self.chain:
            if receivable_sig is None and not self.chain.has_key("approver"):
                return {"case": case_id, "error": "needs the finance manager's signature", "needs_signature": True}
            if receivable_sig is not None:
                who = self.chain.recover(self.chain._recv_msg(bill.bill_id, amount, expiry), receivable_sig)
                if who != self.chain.role_address("approver"):
                    return {"case": case_id, "error": "receivable signature is not the finance manager's"}
            tx = self.chain.open_receivable(bill.bill_id, amount, receivable_sig, expiry)
            out["receivable_tx"] = self._tx(tx)
            self.log.add("contract", "open_receivable", {"amount": amount}, bill_id=bill.bill_id, tx_hash=tx.tx_hash)
            if not tx.ok:
                return {**out, "error": tx.error}
        c.status = "confirmed"
        self.log.add(actor, "case_confirm", {"case": case_id, "kind": c.kind})
        rec = Receivable(bill.bill_id, c.supplier_id, amount, amount, "overpayment", on_chain=bool(self.chain))
        self.led.receivables[bill.bill_id] = rec
        sup = self.led.suppliers[c.supplier_id]
        sup.confirmed_errors += 1
        if bill.tier == "T1":
            ell = amount / bill.amount_usd if bill.amount_usd else 0.0
            before = self.gov.cutoff(bill.group)
            self.gov.outcome(bill.group, ell)
            out["cutoff"] = {"group": bill.group, "before": round(before, 4), "after": round(self.gov.cutoff(bill.group), 4)}
            self.log.add("governor", "cutoff_drop", out["cutoff"])
            if self._claim_needed(bill):
                out["claim"] = self.file_claim(bill.bill_id, amount, sig=claim_sig, expiry=expiry)
        out["probation"] = self.probation(c.supplier_id, reason=f"confirmed error on {bill.bill_id}")
        return out

    def file_claim(self, bill_id: str, amount: float, cause: str = "overpayment", sig: Optional[bytes] = None,
                   expiry: Optional[int] = None) -> dict:
        evidence = self.claim_evidence(bill_id, amount, cause)
        if sig is not None:
            who = self.chain.recover(self.chain._claim_msg(bill_id, amount, CAUSE[cause], evidence, expiry), sig)
            if who != self.chain.role_address("approver"):
                return {"ok": False, "tx_hash": None, "error": "claim signature is not the finance manager's"}
        elif not self.chain.has_key("approver"):
            return {"ok": False, "tx_hash": None, "error": "needs the finance manager's signature"}
        tx = self.chain.file_claim(bill_id, amount, CAUSE[cause], evidence, sig, expiry)
        self.log.add("agent", "file_claim", {"amount": amount, "cause": cause, "signed_by": "finance_manager"},
                     bill_id=bill_id, tx_hash=tx.tx_hash, decision="filed" if tx.ok else tx.error)
        rec = self.led.receivables.get(bill_id)
        if rec:
            rec.claim = {"filed_tx": tx.tx_hash, "amount": amount, "status": "filed" if tx.ok else "failed"}
        return self._tx(tx)

    def execute_claim(self, bill_id: str) -> dict:
        tx = self.chain.execute_claim(bill_id)
        rec = self.led.receivables.get(bill_id)
        if tx.ok and rec:
            rec.claim["status"] = "paid"
            rec.claim["paid_tx"] = tx.tx_hash
            self.money["claims_paid"] += rec.claim["amount"]
        self.log.add("contract", "claim_paid", {}, bill_id=bill_id, tx_hash=tx.tx_hash, decision="paid" if tx.ok else tx.error)
        return self._tx(tx)

    def _record_offsets(self, new_bill: Bill, deducted: float) -> None:
        left = deducted
        for rec in self.led.receivables.values():
            if rec.supplier_id != new_bill.supplier_id or rec.open <= 0 or left <= 0:
                continue
            take = round(min(rec.open, left), 2)
            tx = self.chain.record_offset(rec.bill_id, new_bill.bill_id, take) if self.chain and rec.on_chain else None
            rec.open = round(rec.open - take, 2)
            left = round(left - take, 2)
            new_bill.offsets.append({"against": rec.bill_id, "amount": take, "tx": tx.tx_hash if tx else None})
            self.money["recovered"] += take
            self.log.add("agent", "record_offset", {"receivable": rec.bill_id, "amount": take,
                                                     "to_reserve": bool(rec.claim and rec.claim.get("status") == "paid")},
                         bill_id=new_bill.bill_id, tx_hash=tx.tx_hash if tx else None)

    # ================================================================== supplier messages
    def inbox(self, supplier_id: str, text: str) -> dict:
        """A message from a supplier (email export). Bank details from a supplier only open a call-back task (S4)."""
        from .intent.decide import classify_reply

        cls = classify_reply(text)
        inj = injection.score(text)
        self.log.add("agent", "message", {"supplier": supplier_id, "class": cls, "injection_p": inj["p"]},
                     security=cls == "bank_change" or inj["p"] >= self.cfg.injection_threshold)
        out = {"class": cls, "injection_p": inj["p"]}
        if cls == "bank_change":
            out["freeze"] = self.freeze_supplier(supplier_id, "Supplier message asks to change bank details", trigger=supplier_id)
            out["case"] = self.open_case("bank_change", supplier_id, {"message": "bank-detail change request",
                                                                      "callback": self.led.suppliers[supplier_id].contact}).case_id
        return out

    def receive_email(self, raw: str) -> dict:
        """An email as received. The sender's domain must match a registered supplier exactly. A message that
        names one of our open queries (e.g. 'Re: Q-001') is treated as the reply to that query."""
        from .intake import parse_email, supplier_by_sender

        m = parse_email(raw)
        sid = supplier_by_sender(self.led, m["from"])
        if sid is None:
            inj = injection.score(m["body"])
            self.log.add("agent", "email_unknown_sender", {"from": m["from"], "injection_p": inj["p"]}, security=True)
            return {"from": m["from"], "supplier": None, "action": "logged: sender is not a registered supplier"}
        ref = re.search(r"\bQ-\d{3}\b", f"{m['subject']} {m['body']}")
        if ref and ref.group(0) in self.queries and self.led.bills[self.queries[ref.group(0)]["bill"]].supplier_id == sid:
            return {"from": m["from"], "supplier": sid, "reply_to": ref.group(0), **self.receive_reply(ref.group(0), m["body"])}
        return {"from": m["from"], "supplier": sid, **self.inbox(sid, m["body"])}

    # ================================================================== supplier query
    def draft_query(self, bill_id: str, topic: str = "price") -> dict:
        bill = self.led.bills[bill_id]
        sup = self.led.suppliers[bill.supplier_id]
        fp = bill.fair_price
        if topic == "price" and fp:
            body = (f"Re invoice {bill.read.inv_no} ({fp['material']}): unit price {fp['p_invoice']:,.2f} is "
                    f"{fp['actual']:+.1%} on our last price {fp['p_last']:,.2f}. The {fp['series']} index moved "
                    f"{fp['index_now'] / fp['index_last'] - 1:+.1%} over the same lagged period; with our agreed "
                    f"pass-through this justifies {fp['justified_price']:,.2f}. Please issue a credit note for "
                    f"{fp['overcharge']:,.2f} or explain the difference.")
        else:
            body = f"Re invoice {bill.read.inv_no}: please explain the {topic} on this invoice."
        qid = f"Q-{len(self.queries) + 1:03d}"
        body += f"\n\nPlease quote our reference {qid} in your reply."
        q = {"id": qid, "bill": bill_id, "to": sup.contact, "topic": topic, "subject": f"{qid}: invoice {bill.read.inv_no}",
             "body": body, "status": "draft", "amount": fp["overcharge"] if fp else None}
        self.queries[qid] = q
        self.log.add("agent", "draft_query", {"query": qid, "to": sup.contact}, bill_id=bill_id)
        return q

    def send_query(self, qid: str, actor: str = "finance_manager") -> dict:
        q = self.queries[qid]
        bill = self.led.bills[q["bill"]]
        call = ToolCall("send_query", {"recipient": T.of(self.led.suppliers[bill.supplier_id].contact, Src.REGISTRY),
                                       "bill": T.of(bill.bill_id, Src.ERP)})
        if self._gate(call, bill.bill_id):
            return {"error": "policy"}
        q["status"] = "sent"
        bill.disputed = True
        self.log.add(actor, "send_query", {"query": qid, "to": q["to"]}, bill_id=bill.bill_id, decision="sent")
        return q

    def receive_reply(self, qid: str, reply_text: str, fields: Optional[dict] = None) -> dict:
        """The reply goes through intake: typed fields extracted from its text, a class from the decider.
        No reply class leads to paying more than the current proposed amount."""
        from .intake import extract_reply_fields
        from .intent.decide import classify_reply

        q = self.queries[qid]
        bill = self.led.bills[q["bill"]]
        fields = {**extract_reply_fields(reply_text), **(fields or {})}
        cls = classify_reply(reply_text)
        inj = injection.score(reply_text)
        self.log.add("agent", "reply", {"query": qid, "class": cls, "injection_p": inj["p"], "fields": fields},
                     bill_id=bill.bill_id, security=inj["p"] >= self.cfg.injection_threshold)
        out = {"query": qid, "class": cls}
        if cls == "bank_change" or inj["p"] >= self.cfg.injection_threshold:
            out["action"] = self.freeze_supplier(bill.supplier_id, "Supplier reply asks to change bank details",
                                                 trigger=bill.supplier_id)
            self.open_case("bank_change", bill.supplier_id, {"bill": bill.bill_id, "query": qid})
            return out
        if cls == "credit_note" and fields.get("amount") is None:
            q["status"] = "needs_manager"
            out["resolution"] = {"text": "The supplier mentions a credit note but states no amount: manager to decide."}
            return out
        if cls == "credit_note":
            amount = float(fields["amount"])
            expected = q.get("amount") or 0.0
            proposed = bill.resolution["amount"] if bill.resolution else bill.amount_usd
            # Credit note matched: pay the bill net of it, never more than the current proposed amount.
            net = round(min(proposed, bill.read.total - amount), 2)
            bill.resolution = {**(bill.resolution or {}), "action": "pay_partial", "amount": net,
                               "text": f"Credit note {fields.get('credit_note', '')} for {amount:,.2f} received "
                                       f"({'matches' if abs(amount - expected) < 0.01 else 'differs from'} the query). "
                                       f"Pay {net:,.2f} net of it.",
                               "credit_note": fields.get("credit_note"), "credit": amount}
            bill.disputed = False
            q["status"] = "resolved"
            out["resolution"] = bill.resolution
            return out
        q["status"] = "needs_manager"
        out["resolution"] = {"text": "Reply unclear: manager to decide."}
        return out

    # ================================================================== payment date planner
    def plan_dates(self, bills: list[Bill], cash: Optional[float] = None) -> list[dict]:
        """Pay early only if the discount's annual return beats the credit rate and cash stays above the floor."""
        cash = self.led.cash_usd if cash is None else cash
        today = date.fromisoformat(self.led.today)
        rows = []
        for b in bills:
            due = date.fromisoformat(b.read.due_date)
            if b.read.terms == "2/10net30":
                d, n, dd = 0.02, 30, 10
                ann = d / (1 - d) * 365 / (n - dd)
                disc_by = date.fromisoformat(b.read.date) + timedelta(days=dd)
                rows.append({"bill": b, "ann": ann, "pay_by": disc_by if disc_by >= today else due, "discount": d if disc_by >= today else 0.0})
            else:
                rows.append({"bill": b, "ann": 0.0, "pay_by": due, "discount": 0.0})
        rows.sort(key=lambda r: -r["ann"])
        out = []
        for r in rows:
            b = r["bill"]
            early = r["discount"] > 0 and r["ann"] > self.cfg.credit_rate and cash - b.amount_usd >= self.cfg.cash_floor_usd
            pay_on = today if early else max(today, r["pay_by"] - timedelta(days=1))
            if early:
                cash -= b.amount_usd
            out.append({"bill": b.bill_id, "pay_on": pay_on.isoformat(), "early": early,
                        "annual_return": round(r["ann"], 3), "amount": b.amount_usd})
        return out

    # ================================================================== settings (SET-DIAL, mode)
    def propose_bundle(self, name: str, mode: Optional[str] = None) -> dict:
        """Prepare the settings transaction for a bundle. Only the owner key can send it (T3)."""
        b = self.cal.bundle(name)
        cs = self.chain.state() if self.chain else {"mode": "bonded"}
        mode = mode or cs["mode"]
        return {"bundle": name, "mode": mode, "beta": b.beta, "t1_share": b.t1_share, "p_day_usd": b.p_day_usd,
                "p_nday": b.p_nday, "p_supweek_usd": self.cfg.p_supweek_usd, "K_usd": b.K_usd,
                "r_usd": 0.0 if mode == "standard" else b.r_usd, "chen_usd": b.chen_usd,
                "max_exposure_usd": b.max_exposure_usd}

    MODE_ID = {"standard": 0, "self_reserve": 1, "bonded": 2}

    def _settings_fn(self, p: dict):
        from .config import usd_to_units
        return self.chain.vault.functions.proposeSettings(
            self.MODE_ID[p["mode"]], usd_to_units(p["p_day_usd"]), p["p_nday"], usd_to_units(p["p_supweek_usd"]),
            usd_to_units(p["r_usd"]))

    def settings_tx_request(self, proposal: dict) -> dict:
        """Unsigned proposeSettings transaction for the owner's wallet."""
        return {"proposal": proposal, "tx": self.chain.prepare("owner", self._settings_fn(proposal))}

    def apply_bundle(self, proposal: dict, actor: str = "owner", tx_hash: Optional[str] = None) -> dict:
        """The owner sends proposeSettings (from their wallet: tx_hash; or with the server's owner key). In bonded
        mode the underwriter must also approve; if this process does not hold the underwriter key, the result
        carries the transaction for the underwriter's wallet and the change waits for underwriter_approve."""
        call = ToolCall("propose_settings", {"bundle": T.of(proposal["bundle"], Src.OWNER)})
        if self._gate(call):
            return {"error": "policy"}
        out: dict = {}
        if not self.chain:
            self.gov.bundle_name = proposal["bundle"]
            return out
        tx = self._owner_tx(None, tx_hash, lambda: self.chain.send("owner", self._settings_fn(proposal)))
        out["propose_tx"] = self._tx(tx)
        if not tx.ok:
            return {**out, "error": tx.error, "needs_signature": tx.error == "needs the owner's wallet"}
        sid = self._settings_id_from(tx.tx_hash)
        self.log.add(actor, "settings_proposed", {k: proposal[k] for k in ("bundle", "mode", "r_usd", "p_day_usd", "p_nday")},
                     tx_hash=tx.tx_hash)
        self._pending_bundle = {sid: proposal["bundle"]}
        if proposal["mode"] == "bonded":
            if not self.chain.has_key("underwriter"):
                out["awaiting_underwriter"] = {"settings_id": sid, "tx": self.chain.prepare(
                    "underwriter", self.chain.vault.functions.approveSettings(sid))}
                out["state"] = self.chain.state()
                return out
            out["approve_tx"] = self._tx(self.chain.approve_settings(sid))
        return {**out, **self._settings_active(sid, proposal["bundle"])}

    def underwriter_approve(self, settings_id: int, tx_hash: str) -> dict:
        """The underwriter approved a bonded bundle from their own wallet."""
        tx = self.chain.verify_sent(tx_hash, "underwriter", self.chain.vault)
        if not tx.ok:
            return {"error": tx.error}
        name = getattr(self, "_pending_bundle", {}).get(settings_id)
        self.log.add("underwriter", "settings_approved", {"settings_id": settings_id}, tx_hash=tx_hash)
        return {"approve_tx": self._tx(tx), **self._settings_active(settings_id, name)}

    def _settings_id_from(self, tx_hash: str) -> int:
        from web3.logs import DISCARD
        rc = self.chain.w3.eth.get_transaction_receipt(tx_hash)
        ev = self.chain.vault.events.SettingsProposed().process_receipt(rc, errors=DISCARD)
        return int(ev[0]["args"]["id"])

    def _settings_active(self, sid: int, bundle_name: Optional[str]) -> dict:
        st = self.chain.state()
        if st["settings_id"] == sid and bundle_name:
            self.gov.bundle_name = bundle_name
            self.log.add("contract", "settings_active", {"settings_id": sid, "bundle": bundle_name, "mode": st["mode"]})
        return {"state": st, "active": st["settings_id"] == sid}

    # ================================================================== anchoring
    def anchor_day(self, day: int) -> dict:
        root = self.log.root()
        tx = self.chain.anchor_root(day, root) if self.chain else None
        self.log.add("agent", "anchor", {"day": day, "root": "0x" + root.hex()}, tx_hash=tx.tx_hash if tx else None)
        return {"root": "0x" + root.hex(), "tx": self._tx(tx) if tx else None}

    # ================================================================== views
    def bill_card(self, bill_id: str) -> dict:
        b = self.led.bills[bill_id]
        d = self.decisions.get(bill_id)
        res = self.checks.get(bill_id)
        sup = self.led.suppliers.get(b.supplier_id) if b.supplier_id else None
        card = {
            "bill": b.bill_id, "inv_no": b.read.inv_no, "supplier": sup.name if sup else b.read.supplier_name,
            "supplier_id": b.supplier_id, "status": b.status, "tier": b.tier, "group": b.group,
            "supplier_says_total": b.read.total, "amount": b.amount_usd, "amount_tag": "computed:erp_bounded",
            "erp_bound": b.erp_bound, "score": b.score, "cutoff": d.cutoff if d else None, "reasons": b.reasons,
            "resolution": b.resolution, "fair_price": b.fair_price, "injection_p": b.injection_p,
            "tx_hash": b.tx_hash, "due": b.read.due_date, "terms": b.read.terms, "disputed": b.disputed,
            "mismatches": [asdict(m) for m in res.mismatches] if res else [], "offsets": b.offsets,
            "premium": d.premium if d else None, "erp_ref": b.erp_ref,
        }
        tags = self._card_tags(card)
        policies.check_card(card, tags)  # S5: an untagged number blocks the card
        card["tags"] = {k: t.to_json() for k, t in tags.items()}
        return card

    def _card_tags(self, card: dict) -> dict[str, T]:
        """The source of every number a bill card shows (policy S5)."""
        doc, erp, comp, bnd, mkt = Src.SUPPLIER_DOC, Src.ERP, Src.COMPUTED, Src.ERP_BOUNDED, Src.MARKET
        src = {"supplier_says_total": {doc}, "amount": {bnd}, "erp_bound": {erp}, "score": {comp, doc},
               "cutoff": {Src.SETTINGS, comp}, "injection_p": {comp, doc}, "premium": {comp},
               "resolution.amount": {bnd}, "resolution.held": {comp, doc}, "resolution.credit": {Src.SUPPLIER_MSG}}
        fp = card.get("fair_price") or {}
        when = f"{fp.get('series', 'index')}, World Bank monthly"
        for k in ("p_last", "justified_price", "qty"):
            src[f"fair_price.{k}"] = {erp, comp} if k == "justified_price" else {erp}
        for k in ("p_invoice", "actual", "excess", "overcharge"):
            src[f"fair_price.{k}"] = {doc, comp}
        for k in ("index_last", "index_now", "justified"):
            src[f"fair_price.{k}"] = {mkt}
        tags: dict[str, T] = {}
        for k, v in policies._numbers(card).items():
            s = src.get(k)
            if s is not None:
                tags[k] = T(v, frozenset(s), note=when if mkt in s else "")
        return tags
