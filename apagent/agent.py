"""The payables agent (plan 3.2, 3.3, 3.7).

Every bill: reader -> injection flag -> checker -> governor -> T1 (governor co-signs, contract checks) or
T2 (approval card with a proposed resolution). The agent also reconciles supplier statements, files claims
with the manager's signature, recovers overpayments from the next invoice, runs the supplier query, and
takes protective actions (freeze, pause, probation) on its own.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict
from datetime import date, timedelta
from typing import Optional

from . import budgets, checker, injection, mail, policies
from .audit import AuditLog, input_hash
from .chain import Chain
from .config import SETTINGS, Settings
from .domain import Bill, Case, Ledger, Read, Receivable
from .governor import Decision, Governor
from .policies import PolicyViolation, ToolCall
from .risk.calibrate import Calibration
from .tags import Src, T

CAUSE = {"overpayment": 1, "duplicate": 2, "wrong_payee": 3}


def governor_url() -> Optional[str]:
    """The separate governor service (apagent/governor_service.py), if one is configured."""
    u = os.environ.get("GOVERNOR_URL", "").strip()
    return u.rstrip("/") or None


def _governor_headers() -> dict:
    t = os.environ.get("GOVERNOR_TOKEN", "")
    return {"x-governor-token": t} if t else {}


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
        from . import fx
        self.n_bills += 1
        bid = bill_id or f"B-{self.led.today.replace('-', '')}-{self.n_bills:04d}"
        conv = None
        if (read.currency or "USD").upper() != "USD":
            r = fx.rate(read.currency, read.date or self.led.today)
            if r:  # checked in USD like the order; the original stays on the bill
                conv = {"currency": read.currency.upper(), "total": read.total, "rate": r, "date": read.date,
                        "source": "reference rate"}
                read = fx.to_usd(read, r)
        bill = Bill(bill_id=bid, received=self.led.today, source=source, read=read, fx=conv)
        self.led.bills[bid] = bill
        self.log.add("agent", "intake", {"source": source, "inv_no": read.inv_no, "total": read.total}, bill_id=bid)
        return bill

    def process(self, bill_id: str, auto_pay: bool = True, plan_id: Optional[str] = None) -> dict:
        bill = self.led.bills[bill_id]
        inj = injection.assess(bill.read.raw_text)
        bill.injection_p = inj["p"]
        if inj["p"] >= self.cfg.injection_threshold:
            self.log.add("agent", "injection_flag", {"p": inj["p"], "decoded": inj["decoded"], "model_p": inj.get("model_p")}, bill_id=bill_id,
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
            self._alert_bank_change(res.supplier.id, bill_id)

        d = self.gov.decide(self.led, bill, res, inj["p"], self.led.today, self._chain_state())
        over = budgets.check(self.led, self.budgets, bill, d.amount) if d.tier == "T1" else None
        if over:  # spec D5: a budget only adds scrutiny
            d.tier, d.reasons = "T2", [f"Over budget: {over}"]
        self.decisions[bill_id] = d
        bill.tier, bill.score, bill.reasons = d.tier, d.score, d.reasons
        self.log.add("governor", "decision", {"tier": d.tier, "score": d.score, "cutoff": d.cutoff, "group": d.group,
                                               "reasons": d.reasons, "amount": d.amount}, bill_id=bill_id,
                     plan_id=plan_id, decision=d.tier)
        if d.tier == "reject":
            bill.status = "rejected"
            self.money["duplicates_blocked"] += bill.read.total
            if res.duplicate_of and bill.supplier_id:
                self._notify_duplicate(bill, res.duplicate_of)
            return {"bill": bill_id, "tier": "reject", "reasons": d.reasons}
        if d.tier == "hold":
            bill.status = "held"
            bill.hold_reason = d.reasons[0]
            return {"bill": bill_id, "tier": "hold", "reasons": d.reasons}
        if d.tier == "T2":
            bill.status = "held"
            out = {"bill": bill_id, "tier": "T2", "reasons": d.reasons, "resolution": bill.resolution}
            if (bill.fair_price or "price_history" in res.codes) and mail.auto_email_on():  # ask about the price at once
                q = self.draft_query(bill_id, "price")
                out["query"] = self.send_query(q["id"], actor="agent")["id"]
            return out
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
            refused = self._gov_sign(d, bill, cs["settings_id"], ih)
            if refused:
                self.log.add("governor", "refused", {"reason": refused}, bill_id=bill_id, plan_id=plan_id,
                             decision="T2", security=True)
                bill.status, bill.tier = "held", "T2"
                bill.reasons = bill.reasons + [f"The governor refused to co-sign: {refused}"]
                return {"bill": bill_id, "tier": "T2", "reasons": bill.reasons, "governor": refused}
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

    def _gov_sign(self, d, bill: Bill, settings_id: int, ih: bytes) -> Optional[str]:
        """Get the governor's co-signature. With GOVERNOR_URL set, the separate governor service re-checks the bill
        and signs (spec X5); this process never holds the governor key. Otherwise sign locally (scripted runs).
        Returns the reason if the governor refused."""
        url = governor_url()
        if not url:
            self.gov.sign(d, bill.bill_id, bill.supplier_id, settings_id, ih)
            return None
        import httpx
        body = {"bill_id": bill.bill_id, "read": asdict(bill.read), "source": bill.source, "amount_usd": d.amount,
                "settings_id": settings_id, "input_hash": "0x" + ih.hex().removeprefix("0x"), "today": self.led.today}
        try:
            r = httpx.post(f"{url}/sign", json=body, timeout=60, headers=_governor_headers())
        except httpx.HTTPError as e:
            return f"governor service unreachable ({type(e).__name__})"
        if r.status_code != 200:
            return (r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text)[:300]
        out = r.json()
        d.settings_id, d.expiry, d.signature = out["settings_id"], out["expiry"], bytes.fromhex(out["signature"][2:])
        return None

    def approval_amount(self, bill_id: str, amount: Optional[float] = None) -> float:
        """The amount a T2 approval pays: the proposed resolution, or an edited amount, never above erp_bound."""
        bill = self.led.bills[bill_id]
        proposed = bill.resolution["amount"] if bill.resolution else bill.amount_usd
        usd = proposed if amount is None else amount
        return round(max(0.0, min(usd, bill.erp_bound)), 2)

    def approval_request(self, bill_id: str, amount: Optional[float] = None, ttl: int = 900) -> dict:
        """What the finance manager signs in their wallet for a T2 payment (EIP-712 PaymentApproval). When the
        manager has signed a payment above the two-signature threshold, this is what the owner signs: the same
        message, so both signatures cover the same bill, payee, amount and expiry."""
        bill = self.led.bills[bill_id]
        pend = self._pending_dual().get(bill_id)
        if pend:
            usd, exp, signer = pend["amount"], pend["expiry"], "owner"
        else:
            usd, exp, signer = self.approval_amount(bill_id, amount), self.chain.now() + ttl, "approver"
        dual = self.chain.dual_above_usd()
        return {"bill": bill_id, "amount": usd, "expiry": exp, "signer": self.chain.role_address(signer),
                "signer_role": signer, "needs_owner": bool(dual and usd > dual), "dual_above": dual,
                "typed_data": self.chain.typed_data(self.chain._pay_msg(bill_id, bill.supplier_id, usd, exp))}

    def _pending_dual(self) -> dict:
        return self.__dict__.setdefault("pending_dual", {})

    def cosign(self, bill_id: str, owner_signature: bytes) -> dict:
        """The owner's second signature on an approved payment above the threshold (spec D4)."""
        pend = self._pending_dual().get(bill_id)
        if not pend:
            return {"bill": bill_id, "error": "nothing waiting for the owner's signature"}
        return self.approve(bill_id, pend["amount"], actor="owner", signature=pend["signature"], expiry=pend["expiry"],
                            owner_signature=owner_signature)

    def approve(self, bill_id: str, amount: Optional[float] = None, actor: str = "finance_manager",
                plan_id: Optional[str] = None, signature: Optional[bytes] = None, expiry: Optional[int] = None,
                owner_signature: Optional[bytes] = None) -> dict:
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
            dual = self.chain.dual_above_usd()
            if dual and usd > dual:
                msg = self.chain._pay_msg(bill_id, bill.supplier_id, usd, expiry)
                if owner_signature is None and self.chain.has_key("owner"):
                    owner_signature = self.chain.approval_signature(bill_id, bill.supplier_id, usd, expiry, role="owner")
                if owner_signature is None:
                    self._pending_dual()[bill_id] = {"amount": usd, "expiry": expiry, "signature": signature}
                    self.log.add(actor, "approve_first", {"amount": usd, "threshold": dual}, bill_id=bill_id,
                                 plan_id=plan_id, decision="needs_owner")
                    return {"bill": bill_id, "needs_owner": True, "amount": usd, "threshold": dual,
                            "message": f"Above ${dual:,.0f}: the owner signs too"}
                if self.chain.recover(msg, owner_signature) != self.chain.role_address("owner"):
                    self.log.add("system", "bad_signature", {"for": "owner co-signature"}, bill_id=bill_id, security=True)
                    return {"bill": bill_id, "error": "the second signature is not the owner's for this bill and amount"}
            tx = self.chain.pay_approved(bill_id, bill.supplier_id, usd, expiry, signature, owner_sig=owner_signature)
            if tx.ok:
                self._pending_dual().pop(bill_id, None)
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
        if bill.status not in ("received", "held", "approved"):
            return {"bill": bill_id, "error": f"bill is {bill.status} and can no longer be rejected"}
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
        if mail.auto_email_on():
            self._notify_payment(bill, tx_hash)

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
            from .chain import b32
            tx = self._owner_tx(self.chain.vault.functions.unfreezePayee(b32(supplier_id)), tx_hash, self.chain.unfreeze,
                                supplier_id)
            if not tx.ok:
                return {"supplier": supplier_id, "error": tx.error, "needs_signature": tx.error == "needs the owner's wallet"}
        self.led.suppliers[supplier_id].frozen = False
        self.log.add("owner", "unfreeze_payee", {"supplier": supplier_id}, tx_hash=tx.tx_hash if tx else None)
        return {"supplier": supplier_id, "frozen": False, "tx": self._tx(tx) if tx else None}

    def _owner_tx(self, fn, tx_hash: Optional[str], server_call, *args):
        """An owner transaction: verify the one the owner sent (fn: the call we asked them to sign), or send it with
        the server's owner key if held."""
        from .chain import TxResult
        if tx_hash:
            return self._verify_once(tx_hash, "owner", fn)
        if self.chain.has_key("owner"):
            return server_call(*args)
        return TxResult(False, None, "needs the owner's wallet")

    def _verify_once(self, tx_hash: str, role: str, expect, contract=None):
        """verify_sent, and accept each transaction hash only once, so an old transaction cannot be replayed."""
        from .chain import TxResult
        used = self.__dict__.setdefault("used_tx", set())
        key = tx_hash.lower()
        if key in used:
            self.log.add("system", "tx_replay", {"tx": tx_hash, "role": role}, security=True)
            return TxResult(False, tx_hash, "this transaction was already used")
        tx = self.chain.verify_sent(tx_hash, role, contract or self.chain.vault, expect)
        if not tx.ok:
            self.log.add("system", "bad_owner_tx", {"tx": tx_hash, "role": role, "error": tx.error}, security=True)
            return tx
        used.add(key)
        return tx

    # ================================================================== suppliers: onboarding and bank change (X7)
    RAIL = {"token": 0, "bank": 1}

    def payee_tx_request(self, supplier_id: str, wallet: str, rail: str) -> dict:
        """The owner's addPayee transaction. The payee becomes payable only after the cool-down."""
        from web3 import Web3
        from .chain import b32
        w = Web3.to_checksum_address(wallet) if rail == "token" else "0x0000000000000000000000000000000000000000"
        return {"tx": self.chain.prepare("owner", self.chain.vault.functions.addPayee(b32(supplier_id), w, self.RAIL[rail])),
                "cool_down_s": self.chain.cool_down}

    def set_payee(self, supplier_id: str, wallet: str, rail: str, callback: dict, tx_hash: Optional[str] = None,
                  new: Optional[dict] = None) -> dict:
        """Record a payee the owner added or changed from their wallet. A change to an existing supplier needs the
        call-back done first: someone phoned the number already in the registry and the supplier confirmed."""
        from web3 import Web3
        from .chain import b32
        from .domain import Supplier
        existing = self.led.suppliers.get(supplier_id)
        if existing and not (callback or {}).get("confirmed"):
            return {"supplier": supplier_id, "error": "Do the call-back first: phone the number in the registry, not one from the message"}
        if not existing and not new:
            return {"supplier": supplier_id, "error": "A new supplier needs a name, tax ID, email domain and contact"}
        w = Web3.to_checksum_address(wallet) if rail == "token" else "0x0000000000000000000000000000000000000000"
        tx = None
        if self.chain:
            fn = self.chain.vault.functions.addPayee(b32(supplier_id), w, self.RAIL[rail])
            tx = self._owner_tx(fn, tx_hash, lambda: self.chain.add_payee(supplier_id, w, self.RAIL[rail]))
            if not tx.ok:
                return {"supplier": supplier_id, "error": tx.error, "needs_signature": tx.error == "needs the owner's wallet"}
        if existing:
            existing.wallet, existing.rail = (w if rail == "token" else ""), rail
        else:
            self.led.suppliers[supplier_id] = Supplier(id=supplier_id, name=new["name"], tax_id=new["tax_id"],
                                                       domain=new["domain"].lower(), contact=new["contact"], rail=rail,
                                                       wallet=w if rail == "token" else "", since=self.led.today,
                                                       probation_left=self.cfg.probation_bills)
        for c in self.led.cases.values():
            if c.supplier_id == supplier_id and c.kind == "bank_change" and c.status == "open":
                c.status = "confirmed"
                c.detail["callback"] = callback
        self.log.add("owner", "payee_set", {"supplier": supplier_id, "rail": rail, "new": not existing,
                                            "callback": callback}, tx_hash=tx.tx_hash if tx else None, security=True)
        p = self.chain.payee(supplier_id) if self.chain else {}
        return {"supplier": supplier_id, "active_at": p.get("active_at"), "frozen": p.get("frozen"),
                "tx": self._tx(tx) if tx else None}

    # ================================================================== early-payment offers (P4)
    @property
    def offers(self) -> dict:
        return self.__dict__.setdefault("_offers", {})

    def offer_terms(self, bill: Bill) -> Optional[dict]:
        """The discount that makes paying now worth it: the target annual return over the days gained, between
        0.5% and 2%. None if the bill is not a candidate (due soon, already discounted, or cash would dip)."""
        if bill.status not in ("approved", "held", "received") or not bill.supplier_id or bill.read.terms != "net30":
            return None
        if self.led.suppliers[bill.supplier_id].frozen or bill.tier in ("hold", "reject"):
            return None
        days = (date.fromisoformat(bill.read.due_date) - date.fromisoformat(self.led.today)).days
        if days < self.cfg.offer_min_days:
            return None
        amount = round(bill.resolution["amount"] if bill.resolution else bill.amount_usd, 2)
        if amount <= 0 or self.led.cash_usd - amount < self.cfg.cash_floor_usd:
            return None
        pct = min(0.02, max(0.005, round(self.cfg.offer_target_rate * days / 365, 3)))
        discount = round(amount * pct, 2)
        annual = pct / (1 - pct) * 365 / days
        return {"bill": bill.bill_id, "amount": amount, "pct": pct, "discount": discount, "net": round(amount - discount, 2),
                "days_early": days, "annual_return": round(annual, 4), "beats_credit_rate": annual > self.cfg.credit_rate}

    def offer_candidates(self) -> list[dict]:
        out = []
        for b in self.led.bills.values():
            if b.bill_id.startswith("H") or any(o["bill"] == b.bill_id for o in self.offers.values()):
                continue
            t = self.offer_terms(b)
            if t and t["beats_credit_rate"]:
                out.append({**t, "supplier": self.led.suppliers[b.supplier_id].name, "inv_no": b.read.inv_no,
                            "due": b.read.due_date})
        return sorted(out, key=lambda o: -o["discount"])

    def make_offer(self, bill_id: str, actor: str = "finance_manager") -> dict:
        """Draft the offer email; the finance manager sends it (it changes what we pay, policy S11)."""
        bill = self.led.bills[bill_id]
        t = self.offer_terms(bill)
        if not t:
            return {"bill": bill_id, "error": "not a candidate for an early-payment offer"}
        ref = f"OF-{len(self.offers) + 1:03d}"
        expires = (date.fromisoformat(self.led.today) + timedelta(days=3)).isoformat()
        em = self.send_email("early_payment_offer", bill.supplier_id, {
            "inv_no": T.of(mail.safe_id(bill.read.inv_no, bill_id), Src.SUPPLIER_DOC),
            "amount": T.of(f"${t['amount']:,.2f}", Src.ERP_BOUNDED), "due": T.of(bill.read.due_date, Src.SUPPLIER_DOC),
            "pct": T.of(f"{t['pct']:.1%}", Src.COMPUTED), "discount": T.of(f"${t['discount']:,.2f}", Src.COMPUTED),
            "net": T.of(f"${t['net']:,.2f}", Src.COMPUTED), "ref": T.of(ref, Src.COMPUTED),
            "expires": T.of(expires, Src.COMPUTED)}, bill_id=bill_id, actor=actor, draft_only=True)
        self.offers[ref] = {"ref": ref, **t, "supplier_id": bill.supplier_id, "email": em["id"], "status": "draft",
                            "expires": expires, "created": self.led.today}
        self.log.add(actor, "offer_draft", {"offer": ref, "pct": t["pct"], "discount": t["discount"]}, bill_id=bill_id)
        return self.offers[ref]

    def offer_reply(self, ref: str, text: str) -> dict:
        """ACCEPT: the bill is proposed at the discounted amount for the finance manager to sign. The reply text
        only selects 'accepted' or not; the amount comes from our own offer."""
        o = self.offers[ref]
        bill = self.led.bills[o["bill"]]
        if o["status"] not in ("sent", "draft") or self.led.today > o["expires"]:
            return {"offer": ref, "status": o["status"], "note": "offer no longer open"}
        if not re.search(r"\baccept(ed)?\b", text, re.I) or re.search(r"\b(not|don't|do not|cannot)\s+accept", text, re.I):
            o["status"] = "declined"
            self.log.add("agent", "offer_declined", {"offer": ref}, bill_id=bill.bill_id)
            return {"offer": ref, "status": "declined"}
        o["status"] = "accepted"
        net = min(o["net"], bill.erp_bound)
        bill.resolution = {**(bill.resolution or {}), "action": "pay_partial", "amount": net, "held": 0.0,
                           "text": f"The supplier accepted early payment ({ref}): pay {net:,.2f} now, {o['pct']:.1%} off.",
                           "tag": "computed:erp_bounded", "offer": ref}
        bill.status, bill.tier = "held", "T2"
        self.money["discounts_taken"] += o["discount"]
        self.log.add("agent", "offer_accepted", {"offer": ref, "net": net}, bill_id=bill.bill_id, decision="T2")
        return {"offer": ref, "status": "accepted", "resolution": bill.resolution}

    # ================================================================== budgets (D5)
    @property
    def budgets(self) -> dict:
        return self.__dict__.setdefault("_budgets", {})

    def set_budget(self, centre: str, usd: Optional[float], actor: str = "owner") -> dict:
        if usd is None:
            self.budgets.pop(centre, None)
        else:
            if usd < 0:
                raise ValueError("a budget cannot be negative")
            self.budgets[centre] = round(float(usd), 2)
        self.log.add(actor, "budget_set", {"centre": centre, "monthly_usd": usd})
        return {"centre": centre, "monthly_usd": usd}

    # ================================================================== market watch: draft purchase orders (C10)
    def draft_po(self, item: str, option: str, months: int = 2, actor: str = "owner") -> dict:
        """A buy-ahead suggestion turned into a draft purchase order (T0: a person places it in the ERP). The
        quantity comes from the company's own purchases, the supplier from its last order; market data only
        informs the choice (S7)."""
        from . import marketwatch
        mat = self.led.materials[item]
        card = next(c for c in marketwatch.watch(self.led) if c["item"] == item)
        cmp_ = marketwatch.buy_ahead(mat.series, card["need_t_per_month"], months=months,
                                     cash_available=self.led.cash_usd - self.cfg.cash_floor_usd)
        opt = cmp_["options"][option]
        if opt["now_t"] <= 0:
            return {"item": item, "option": option, "draft": None, "message": "Waiting: nothing to order now."}
        last = max((po for po in self.led.pos.values() if any(l.item == item for l in po.lines)), key=lambda p: p.date)
        unit_qty = round(opt["now_t"] / mat.tonnes_per_unit, 3)
        drafts = self.__dict__.setdefault("po_drafts", [])
        d = {"id": f"DPO-{len(drafts) + 1:03d}", "item": item, "material": mat.name, "supplier_id": last.supplier_id,
             "supplier": self.led.suppliers[last.supplier_id].name, "qty": unit_qty, "unit": mat.unit,
             "index_price_t": cmp_["price"], "option": option, "months": months, "created": self.led.today,
             "status": "draft", "comparison": cmp_}
        drafts.append(d)
        self.log.add(actor, "draft_po", {k: d[k] for k in ("id", "item", "qty", "unit", "supplier_id", "option")})
        return {"item": item, "option": option, "draft": d}

    def set_signing_key(self, supplier_id: str, address: str, actor: str = "owner") -> dict:
        """Enrol a supplier's invoice-signing key (spec C9); an empty address withdraws it."""
        from web3 import Web3
        sup = self.led.suppliers[supplier_id]
        if address and not Web3.is_address(address):
            raise ValueError("not an address")
        sup.signing_key = Web3.to_checksum_address(address) if address else ""
        self.log.add(actor, "signing_key", {"supplier": supplier_id, "key": sup.signing_key or None}, security=True)
        return {"supplier": supplier_id, "signing_key": sup.signing_key}

    # ================================================================== bank and arbiter decisions on claims (V4)
    def bank_tx_request(self, action: str, bill_id: Optional[str] = None, usd: Optional[float] = None) -> dict:
        """Unsigned transactions for the bank's or the arbiter's wallet."""
        from .chain import b32
        from .config import usd_to_units
        pf = self.chain.pool.functions
        if action == "dispute":
            return {"tx": self.chain.prepare("underwriter", pf.dispute(b32(bill_id)))}
        if action == "resolve":
            return {"tx": self.chain.prepare("arbiter", pf.resolve(b32(bill_id), usd_to_units(usd)))}
        if action == "fund":
            units = usd_to_units(usd)
            return {"txs": [self.chain.prepare("underwriter", self.chain.token.functions.approve(self.chain.pool.address, units)),
                            self.chain.prepare("underwriter", pf.fund(units))]}
        if action == "unpause":
            return {"tx": self.chain.prepare("underwriter", pf.unpause())}
        raise ValueError(f"unknown action {action}")

    def bank_action(self, action: str, tx_hash: str, bill_id: Optional[str] = None, usd: Optional[float] = None) -> dict:
        """Record a claim dispute (bank), a decision (arbiter), a top-up or an unpause, after checking the transaction."""
        from .chain import b32
        from .config import usd_to_units
        pf = self.chain.pool.functions
        role, expect = {
            "dispute": ("underwriter", lambda: pf.dispute(b32(bill_id))),
            "resolve": ("arbiter", lambda: pf.resolve(b32(bill_id), usd_to_units(usd))),
            "fund": ("underwriter", lambda: pf.fund(usd_to_units(usd))),
            "unpause": ("underwriter", lambda: pf.unpause()),
        }[action]
        tx = self._verify_once(tx_hash, role, expect(), contract=self.chain.pool)
        if not tx.ok:
            return {"error": tx.error}
        actor = "arbiter" if role == "arbiter" else "underwriter"
        self.log.add(actor, f"claim_{action}" if bill_id else f"pool_{action}", {"amount": usd}, bill_id=bill_id,
                     tx_hash=tx_hash)
        return {"ok": True, "tx": self._tx(tx)}

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
            tx = self._owner_tx(self.chain.vault.functions.unpauseAgent(), tx_hash, self.chain.unpause_agent)
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
        self.log.add("agent", "case_open", {"kind": kind, "case": cid, **detail}, decision="open")
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
            if governor_url():  # the separate governor tightens too
                import httpx
                try:
                    httpx.post(f"{governor_url()}/outcome", json={"supplier_id": c.supplier_id, "group": bill.group,
                                                                  "loss_ratio": ell}, timeout=30, headers=_governor_headers())
                except httpx.HTTPError as e:
                    self.log.add("system", "governor_outcome_failed", {"error": type(e).__name__}, security=True)
            out["cutoff"] = {"group": bill.group, "before": round(before, 4), "after": round(self.gov.cutoff(bill.group), 4)}
            self.log.add("governor", "cutoff_drop", out["cutoff"])
            if self._claim_needed(bill):
                out["claim"] = self.file_claim(bill.bill_id, amount, sig=claim_sig, expiry=expiry)
        out["probation"] = self.probation(c.supplier_id, reason=f"confirmed error on {bill.bill_id}")
        # A refund request is drafted for the finance manager; recovery from the next bill happens anyway (V5).
        out["refund_draft"] = self.send_email("refund_request", c.supplier_id, {
            "inv_no": T.of(mail.safe_id(bill.read.inv_no, bill.bill_id), Src.SUPPLIER_DOC),
            "amount": T.of(f"${amount:,.2f}", Src.ERP_BOUNDED), "date": T.of(bill.paid_on or self.led.today, Src.ERP),
            "ref": T.of(case_id, Src.COMPUTED)}, bill_id=bill.bill_id, draft_only=True)["id"]
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
        inj = injection.assess(text)
        self.log.add("agent", "message", {"supplier": supplier_id, "class": cls, "injection_p": inj["p"]},
                     security=cls == "bank_change" or inj["p"] >= self.cfg.injection_threshold)
        out = {"class": cls, "injection_p": inj["p"]}
        if cls == "bank_change":
            out["freeze"] = self.freeze_supplier(supplier_id, "Supplier message asks to change bank details", trigger=supplier_id)
            out["alert"] = self._alert_bank_change(supplier_id)
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
            inj = injection.assess(m["body"])
            self.log.add("agent", "email_unknown_sender", {"from": m["from"], "injection_p": inj["p"]}, security=True)
            return {"from": m["from"], "supplier": None, "action": "logged: sender is not a registered supplier"}
        offer = re.search(r"\bOF-\d{3}\b", f"{m['subject']} {m['body']}")
        if offer and offer.group(0) in self.offers and self.offers[offer.group(0)]["supplier_id"] == sid:
            return {"from": m["from"], "supplier": sid, "offer": offer.group(0), **self.offer_reply(offer.group(0), m["body"])}
        ref = re.search(r"\bQ-\d{3}\b", f"{m['subject']} {m['body']}")
        if ref and ref.group(0) in self.queries and self.led.bills[self.queries[ref.group(0)]["bill"]].supplier_id == sid:
            return {"from": m["from"], "supplier": sid, "reply_to": ref.group(0), **self.receive_reply(ref.group(0), m["body"])}
        return {"from": m["from"], "supplier": sid, **self.inbox(sid, m["body"])}

    # ================================================================== email (spec V2, policy S11)
    def _emails(self) -> list:
        return self.__dict__.setdefault("emails", [])

    def send_email(self, template: str, supplier_id: str, values: dict, bill_id: Optional[str] = None,
                   actor: str = "agent", approved_by: Optional[str] = None, draft_only: bool = False) -> dict:
        """Fill a template with typed values and send it to the supplier's registered contact. draft_only keeps it
        for the finance manager (templates that change what we pay)."""
        sup = self.led.suppliers[supplier_id]
        rec = {"id": f"M-{len(self._emails()) + 1:04d}", "template": template, "to": sup.contact, "supplier": supplier_id,
               "supplier_name": sup.name, "bill": bill_id, "status": "draft", "actor": actor, "created": self.led.today,
               "auto": template in mail.AUTO_TEMPLATES}
        plain = {k: v.value for k, v in values.items()}
        plain.update(supplier=sup.name, company=self.led.company.replace(" (fictional)", ""))
        rec["subject"], rec["body"] = mail.render(template, plain)
        self.__dict__.setdefault("_email_values", {})[rec["id"]] = values
        self._emails().append(rec)
        if draft_only:
            self.log.add(actor, "email_draft", {"email": rec["id"], "template": template, "to": sup.contact}, bill_id=bill_id)
            return rec
        return self._deliver(rec, values, approved_by)

    def _deliver(self, rec: dict, values: dict, approved_by: Optional[str]) -> dict:
        args = {"recipient": T.of(rec["to"], Src.REGISTRY), "template": T.of(rec["template"], Src.SETTINGS), **values}
        if self._gate(ToolCall("send_email", args, approved_by=approved_by), rec["bill"]):
            rec["status"] = "blocked"
            return rec
        m = mail.mailer()
        try:
            rec["message_id"] = m.send(mail.build(rec["to"], rec["subject"], rec["body"], rec["id"]))
            rec["status"], rec["via"], rec["sent"] = "sent", m.name, self.led.today
        except Exception as e:  # noqa: BLE001 - any mail failure is recorded, never fatal
            rec["status"], rec["error"] = "failed", str(e)[:200]
        self.log.add(rec["actor"] if not approved_by else approved_by, f"email_{rec['status']}",
                     {"email": rec["id"], "template": rec["template"], "to": rec["to"], "via": m.name}, bill_id=rec["bill"])
        return rec

    def release_email(self, email_id: str, actor: str = "finance_manager") -> dict:
        """The finance manager sends a drafted email (a refund request, for example)."""
        rec = next((e for e in self._emails() if e["id"] == email_id), None)
        if rec is None:
            raise KeyError(email_id)
        if rec["status"] not in ("draft", "failed"):
            return {**rec, "error": f"email is {rec['status']}"}
        rec["actor"] = actor
        out = self._deliver(rec, self.__dict__.get("_email_values", {}).get(email_id, {}), approved_by=actor)
        for o in self.offers.values():  # an offer counts from the moment its email goes out
            if o["email"] == email_id and out["status"] == "sent":
                o["status"] = "sent"
        return out

    def _notify_payment(self, bill: Bill, tx_hash: Optional[str]) -> None:
        ref = tx_hash or "recorded"
        if self.led.suppliers[bill.supplier_id].rail == "bank":
            ref = f"bank transfer, ledger {tx_hash}" if tx_hash else "bank transfer"
        self.send_email("payment_notice", bill.supplier_id, {
            "inv_no": T.of(mail.safe_id(bill.read.inv_no, bill.bill_id), Src.SUPPLIER_DOC),
            "amount": T.of(f"${bill.amount_usd:,.2f}", Src.ERP_BOUNDED), "date": T.of(self.led.today, Src.ERP),
            "ref": T.of(ref, Src.COMPUTED)}, bill_id=bill.bill_id)

    def _notify_duplicate(self, bill: Bill, dup_bill: str) -> None:
        if not mail.auto_email_on():
            return
        first = self.led.bills.get(dup_bill)
        self.send_email("duplicate_notice", bill.supplier_id, {
            "inv_no": T.of(mail.safe_id(bill.read.inv_no, bill.bill_id), Src.SUPPLIER_DOC),
            "billed": T.of(f"${bill.read.total:,.2f}", Src.SUPPLIER_DOC),
            "dup_of": T.of(mail.safe_id(first.read.inv_no, dup_bill) if first else dup_bill, Src.ERP)}, bill_id=bill.bill_id)

    def _alert_bank_change(self, supplier_id: str, bill_id: Optional[str] = None) -> Optional[str]:
        """Tell the real supplier, at the registered address, that someone asked to change their bank details.
        Once per supplier per day; never a reply to the message that asked."""
        if not mail.auto_email_on():
            return None
        if any(e["template"] == "bank_change_alert" and e["supplier"] == supplier_id and e["created"] == self.led.today
               for e in self._emails()):
            return None
        return self.send_email("bank_change_alert", supplier_id, {}, bill_id=bill_id)["id"]

    # ================================================================== supplier query
    def draft_query(self, bill_id: str, topic: str = "price") -> dict:
        for q in self.queries.values():  # one open query per bill and topic
            if q["bill"] == bill_id and q["topic"] == topic and q["status"] in ("draft", "sent"):
                return q
        bill = self.led.bills[bill_id]
        sup = self.led.suppliers[bill.supplier_id]
        fp = bill.fair_price
        res = self.checks.get(bill_id)
        hp = next((m.detail for m in res.mismatches if m.code == "price_history"), None) if res else None
        if topic == "price" and not fp and hp:
            body = (f"Re invoice {bill.read.inv_no} ({hp['material']}): unit price {hp['p_invoice']:,.2f} is "
                    f"{hp['actual']:+.1%} on our last order price {hp['p_last']:,.2f}. Over our last {hp['purchases']} "
                    f"orders this item's price has not moved more than {hp['band']:.0%}. Please explain the increase or "
                    f"issue a credit note for {hp['overcharge']:,.2f}.")
            fp = {"overcharge": hp["overcharge"]}
        elif topic == "price" and fp:
            body = (f"Re invoice {bill.read.inv_no} ({fp['material']}): unit price {fp['p_invoice']:,.2f} is "
                    f"{fp['actual']:+.1%} on our last price {fp['p_last']:,.2f}. The {fp['series']} index moved "
                    f"{fp['index_now'] / fp['index_last'] - 1:+.1%} over the same lagged period; with our agreed "
                    f"pass-through this justifies {fp['justified_price']:,.2f}. Please issue a credit note for "
                    f"{fp['overcharge']:,.2f} or explain the difference.")
        else:
            body = f"Re invoice {bill.read.inv_no}: please explain the {topic} on this invoice."
        qid = f"Q-{len(self.queries) + 1:03d}"
        q = {"id": qid, "bill": bill_id, "to": sup.contact, "topic": topic, "text": body,
             "subject": f"{qid}: invoice {bill.read.inv_no}",
             "body": body + f"\n\nPlease quote our reference {qid} in your reply.", "status": "draft",
             "amount": fp["overcharge"] if fp else None}
        self.queries[qid] = q
        self.log.add("agent", "draft_query", {"query": qid, "to": sup.contact}, bill_id=bill_id)
        return q

    def send_query(self, qid: str, actor: str = "finance_manager") -> dict:
        q = self.queries[qid]
        bill = self.led.bills[q["bill"]]
        call = ToolCall("send_query", {"recipient": T.of(self.led.suppliers[bill.supplier_id].contact, Src.REGISTRY),
                                       "bill": T.of(bill.bill_id, Src.ERP)})
        if q["status"] != "draft":
            return q
        if self._gate(call, bill.bill_id):
            return {"error": "policy"}
        inv = mail.safe_id(bill.read.inv_no, bill.bill_id)
        em = self.send_email("query", bill.supplier_id, {"qid": T.of(qid, Src.COMPUTED), "inv_no": T.of(inv, Src.SUPPLIER_DOC),
                                                         "text": T.of(q.get("text", q["body"]), Src.COMPUTED)},
                             bill_id=bill.bill_id, actor=actor)
        if em["status"] != "sent":
            return {**q, "error": em.get("error") or em["status"]}
        q["status"] = "sent"
        q["email"] = em["id"]
        bill.disputed = True
        self.log.add(actor, "send_query", {"query": qid, "to": q["to"], "email": em["id"]}, bill_id=bill.bill_id,
                     decision="sent")
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
        inj = injection.assess(reply_text)
        self.log.add("agent", "reply", {"query": qid, "class": cls, "injection_p": inj["p"], "fields": fields},
                     bill_id=bill.bill_id, security=inj["p"] >= self.cfg.injection_threshold)
        out = {"query": qid, "class": cls}
        if cls == "bank_change" or inj["p"] >= self.cfg.injection_threshold:
            out["action"] = self.freeze_supplier(bill.supplier_id, "Supplier reply asks to change bank details",
                                                 trigger=bill.supplier_id)
            self._alert_bank_change(bill.supplier_id, bill.bill_id)
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
        tx = self._owner_tx(self._settings_fn(proposal), tx_hash, lambda: self.chain.send("owner", self._settings_fn(proposal)))
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
        tx = self._verify_once(tx_hash, "underwriter", self.chain.vault.functions.approveSettings(settings_id))
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
        """Anchor the Merkle root of every journal line so far. The anchor records how many lines it covers, so
        any one of them can later be proved against the on-chain root (spec E4)."""
        n = len(self.log.lines)
        root = self.log.root()
        tx = self.chain.anchor_root(day, root) if self.chain else None
        if tx is None or tx.ok:
            self.__dict__.setdefault("anchors", []).append({"day": day, "lines": n, "root": "0x" + root.hex(),
                                                            "tx": tx.tx_hash if tx else None, "date": self.led.today})
        self.log.add("agent", "anchor", {"day": day, "root": "0x" + root.hex(), "lines": n},
                     tx_hash=tx.tx_hash if tx else None)
        return {"root": "0x" + root.hex(), "lines": n, "tx": self._tx(tx) if tx else None}

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
        from . import views
        card.update(stage=views.stage(b), paid_by=views.paid_by(b), received=b.received, paid_on=b.paid_on,
                    source=b.source, po=b.read.po_id, inv_date=b.read.date, currency=b.read.currency,
                    fx=getattr(b, "fx", None),
                    hold_reason=b.hold_reason, plan_id=b.plan_id, match=self.three_way(b),
                    confidence=b.read.confidence, low_confidence=sorted(k for k, v in b.read.confidence.items() if v < 0.9),
                    queries=[q["id"] for q in self.queries.values() if q["bill"] == bill_id],
                    emails=[e["id"] for e in self._emails() if e.get("bill") == bill_id],
                    cases=[c.case_id for c in self.led.cases.values() if c.detail.get("bill") == bill_id])
        return card

    def three_way(self, b: Bill) -> list[dict]:
        """Invoice vs purchase order vs goods received, per invoice line (spec C1). Each figure names its source."""
        po = self.led.pos.get(b.read.po_id)
        rows = []
        for l in b.read.lines:
            pl = next((x for x in po.lines if x.item == l.item), None) if po else None
            rec = self.led.received_qty(b.read.po_id, l.item) if po else None
            before = self.led.billed_qty(b.read.po_id, l.item, exclude=b.bill_id) if po else None
            rows.append({"item": l.item, "desc": l.desc, "unit": l.unit,
                         "invoice": {"qty": l.qty, "price": l.price, "amount": l.amount, "source": "supplier_doc"},
                         "order": {"qty": pl.qty, "price": pl.price, "source": "erp"} if pl else None,
                         "received": {"qty": rec, "billed_before": before, "source": "erp"} if po else None,
                         "qty_ok": bool(pl) and rec is not None and l.qty <= rec - (before or 0) + 1e-9,
                         "price_ok": bool(pl) and abs(l.price - pl.price) <= pl.price * (self.led.suppliers[b.supplier_id].price_tolerance
                                                                                         if b.supplier_id else 0.01) + 1e-9})
        return rows

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
        src["fair_price.p_invoice"] = {doc}
        for k in ("actual", "excess", "overcharge"):
            src[f"fair_price.{k}"] = {doc, comp}
        for k in ("index_last", "index_now", "justified"):
            src[f"fair_price.{k}"] = {mkt}
        tags: dict[str, T] = {}
        for k, v in policies._numbers(card).items():
            s = src.get(k)
            if s is not None:
                tags[k] = T(v, frozenset(s), note=when if mkt in s else "")
        return tags
