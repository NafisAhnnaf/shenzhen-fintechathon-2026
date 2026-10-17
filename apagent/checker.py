"""Deterministic checker (plan section 6) with the fair-price check (9.2) and proposed resolutions (3.7).

Inputs: the reader's typed fields (untrusted) and the company's records (trusted).
Outputs: pass or mismatches, margins for the score, erp_bound for policy S2, and a proposed resolution.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Optional

from . import market
from .config import SETTINGS, Settings
from .domain import Bill, Ledger, PurchaseOrder, Supplier
from .tags import Src, T, bounded


@dataclass
class Mismatch:
    code: str
    reason: str
    detail: dict = field(default_factory=dict)


@dataclass
class FairPrice:
    item: str
    material: str
    p_last: float
    p_invoice: float
    actual: float  # a
    justified: float  # j
    excess: float  # e
    justified_price: float
    overcharge: float
    qty: float
    index_last: float
    index_now: float
    series: str
    flagged: bool

    def to_json(self) -> dict:
        return self.__dict__.copy()


@dataclass
class CheckResult:
    supplier: Optional[Supplier]
    po: Optional[PurchaseOrder]
    mismatches: list[Mismatch]
    margins: dict[str, float]
    erp_bound: T  # trusted cap from ERP and settings only (policy S2)
    group: str
    fair: list[FairPrice]
    deductions: dict[str, float]
    amount: T = None  # bounded(payable from the bill, erp_bound): tagged computed:erp_bounded
    resolution: Optional[dict] = None
    duplicate_of: Optional[str] = None

    @property
    def passed(self) -> bool:
        return not self.mismatches

    @property
    def codes(self) -> list[str]:
        return [m.code for m in self.mismatches]


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def match_supplier(led: Ledger, bill: Bill) -> tuple[Optional[Supplier], list[Mismatch]]:
    r = bill.read
    out: list[Mismatch] = []
    sup = next((s for s in led.suppliers.values() if s.tax_id == r.tax_id), None)
    if sup is None:
        best = max(led.suppliers.values(), key=lambda s: _sim(s.name, r.supplier_name), default=None)
        if best is None or _sim(best.name, r.supplier_name) < 0.85:
            return None, [Mismatch("unknown_supplier", "No registered supplier matches the tax ID or name")]
        sup = best
        out.append(Mismatch("tax_id", "Tax ID does not match the registered supplier", {"registered": sup.tax_id}))
    if r.sender_domain and r.sender_domain != sup.domain:
        out.append(Mismatch("domain", "Sender domain differs from the registered domain",
                            {"registered": sup.domain, "lookalike": _sim(r.sender_domain, sup.domain) > 0.7}))
    registered = sup.bank_account if sup.rail == "bank" else sup.wallet
    if r.bank_account and r.bank_account != registered:
        out.append(Mismatch("bank_change", "Bank details on the bill differ from the registry"))
    return sup, out


def match_order(led: Ledger, bill: Bill, sup: Supplier) -> tuple[Optional[PurchaseOrder], list[Mismatch]]:
    r = bill.read
    po = led.pos.get(r.po_id)
    if po and po.supplier_id == sup.id:
        return po, []
    items = {l.item for l in r.lines}
    ranked = sorted(
        (p for p in led.pos.values() if p.supplier_id == sup.id),
        key=lambda p: -len(items & {l.item for l in p.lines}),
    )
    if not ranked or not items & {l.item for l in ranked[0].lines}:
        return None, [Mismatch("no_order", "No purchase order matches this bill")]
    best = len(items & {l.item for l in ranked[0].lines})
    ties = [p for p in ranked if len(items & {l.item for l in p.lines}) == best]
    if len(ties) > 1:
        return None, [Mismatch("order_tie", "More than one order matches", {"orders": [p.po_id for p in ties]})]
    return ranked[0], []


def find_duplicate(led: Ledger, bill: Bill, sup: Supplier) -> Optional[tuple[str, str]]:
    """Exact duplicate, or a fuzzy one by Fellegi-Sunter style agreement weights."""
    r = bill.read
    for b in led.bills.values():
        if b.bill_id == bill.bill_id or b.supplier_id != sup.id or b.status == "rejected":
            continue
        if b.read.inv_no == r.inv_no:
            return b.bill_id, "exact"
        # log2(m/u) weights for agreement; disagreement weights are negative
        w = 0.0
        w += 6.0 if _sim(b.read.inv_no, r.inv_no) > 0.8 else -2.0
        w += 7.0 if abs(b.read.total - r.total) < 0.01 else -4.0
        w += 3.0 if b.read.po_id == r.po_id else -1.0
        w += 2.0 if b.read.date == r.date else -1.0
        if w >= 12.0:
            return b.bill_id, "fuzzy"
    return None


def fair_price_check(led: Ledger, sup: Supplier, line, inv_date: str, cfg: Settings,
                     po_date: Optional[str] = None) -> Optional[FairPrice]:
    """Compare the price change since the last purchase before this bill's own order with the index change."""
    mat = led.materials.get(line.item)
    if mat is None or mat.series is None:
        return None
    # The supplier set its current price when it last changed it: compare the index from that date.
    last = led.price_since(sup.id, line.item, before=po_date or inv_date)
    if last is None:
        return None
    p_last, last_date = last
    if abs(line.price - p_last) < 1e-9:
        return None
    i_last = market.index_value(mat.series, last_date, mat.lag_months)
    i_now = market.index_value(mat.series, inv_date, mat.lag_months)
    a = line.price / p_last - 1
    j = mat.pass_through * (i_now / i_last - 1)
    e = a - j
    justified_price = round(p_last * (1 + j), 2)
    overcharge = round(max(0.0, (line.price - justified_price) * line.qty), 2)
    hist = _past_excess(led, sup, line.item, mat, inv_date)
    band = sorted(hist)[int(0.9 * (len(hist) - 1))] if len(hist) >= 5 else 0.0
    flagged = e > cfg.fair_price_tolerance and e > band
    return FairPrice(line.item, mat.name, p_last, line.price, round(a, 4), round(j, 4), round(e, 4),
                     justified_price, overcharge, line.qty, i_last, i_now, mat.series, flagged)


def _past_excess(led: Ledger, sup: Supplier, item: str, mat, before: str) -> list[float]:
    pts = sorted(((po.date, l.price) for po in led.pos.values() if po.supplier_id == sup.id and po.date < before
                  for l in po.lines if l.item == item))
    out = []
    for (d0, p0), (d1, p1) in zip(pts, pts[1:]):
        if p0 == p1:
            continue
        j = mat.pass_through * (market.index_value(mat.series, d1, mat.lag_months)
                                / market.index_value(mat.series, d0, mat.lag_months) - 1)
        out.append(p1 / p0 - 1 - j)
    return out


def group_of(led: Ledger, sup: Supplier, bill: Bill) -> str:
    if sup.bills_paid < 3:
        return "new_supplier"
    po = led.pos.get(bill.read.po_id)
    before = po.date if po and po.supplier_id == sup.id else bill.read.date
    for l in bill.read.lines:
        last = led.last_price(sup.id, l.item, before=before)
        if last and abs(last[0] - l.price) / last[0] > 1e-6:
            return "price_change"
    if bill.read.credit > 0 or len(bill.read.lines) > 3:
        return "other"
    return "routine"


def check(led: Ledger, bill: Bill, cfg: Settings = SETTINGS) -> CheckResult:
    r = bill.read
    mismatches: list[Mismatch] = []
    margins = {"price": 1.0, "qty": 1.0, "arith": 1.0}
    sup, mm = match_supplier(led, bill)
    mismatches += mm
    if sup is None:
        zero = T.of(0.0, Src.ERP)
        res = CheckResult(None, None, mismatches, margins, zero, "new_supplier", [], {}, amount=bounded(zero, zero))
        res.resolution = {"action": "hold", "amount": 0.0, "held": bill.read.total, "tag": "computed:erp_bounded",
                          "text": "Hold. The sender is not a registered supplier."}
        return res

    dup = find_duplicate(led, bill, sup)
    po, mm = match_order(led, bill, sup)
    mismatches += mm
    fair: list[FairPrice] = []
    cap = 0.0  # ERP only: what the company owes for goods received and not yet billed
    payable = 0.0  # from the bill, each line bounded by ERP quantities and prices
    if dup:
        mismatches.append(Mismatch("duplicate", f"Duplicate of bill {dup[0]} ({dup[1]})", {"of": dup[0], "kind": dup[1]}))

    tol = sup.price_tolerance
    if po is not None:
        po_lines = {l.item: l for l in po.lines}
        for pl in po.lines:
            avail = max(0.0, led.received_qty(po.po_id, pl.item) - led.billed_qty(po.po_id, pl.item, exclude=bill.bill_id))
            cap += avail * pl.price * (1 + tol)
        for line in r.lines:
            pl = po_lines.get(line.item)
            if pl is None:
                cand = max(po.lines, key=lambda x: _sim(x.desc, line.desc))
                if _sim(cand.desc, line.desc) > 0.8 and cand.unit == line.unit:
                    pl = cand
                else:
                    mismatches.append(Mismatch("no_line", f"Item {line.item} is not on order {po.po_id}"))
                    continue
            received = led.received_qty(po.po_id, pl.item)
            billed = led.billed_qty(po.po_id, pl.item, exclude=bill.bill_id)
            avail = max(0.0, received - billed)
            margins["qty"] = min(margins["qty"], (avail - line.qty) / max(line.qty, 1e-9))
            if line.qty > avail + 1e-9:
                mismatches.append(Mismatch("qty", f"Billed {line.qty:g} {line.unit} of {pl.item}; received and not yet billed: {avail:g}",
                                           {"item": pl.item, "billed": line.qty, "available": avail, "price": pl.price}))
            dev = (line.price - pl.price) / pl.price
            margins["price"] = min(margins["price"], (tol - dev) / tol if tol else 0.0)
            if dev > tol + 1e-12:
                mismatches.append(Mismatch("price", f"Unit price {line.price:,.2f} is {dev:+.1%} vs order price {pl.price:,.2f}",
                                           {"item": pl.item, "invoice_price": line.price, "order_price": pl.price, "qty": line.qty}))
            pay_price = line.price if dev <= tol + 1e-12 else pl.price  # above tolerance: pay at the order price
            fp = fair_price_check(led, sup, line, r.date, cfg, po_date=po.date)
            if fp:
                fair.append(fp)
                if fp.flagged:
                    pay_price = min(pay_price, fp.justified_price)  # pay at the justified price, hold the excess
                    mismatches.append(Mismatch("fair_price", f"{pl.desc}: price {fp.actual:+.1%} while the index justifies {fp.justified:+.1%}",
                                               fp.to_json()))
            payable += min(line.qty, avail) * pay_price

    # arithmetic and currency
    gross = round(sum(l.amount for l in r.lines), 2)
    if abs(gross - r.credit - r.total) > 0.01:
        margins["arith"] = 0.0
        mismatches.append(Mismatch("arith", f"Lines add up to {gross - r.credit:,.2f}, bill total says {r.total:,.2f}"))
    if r.currency != "USD":
        mismatches.append(Mismatch("currency", f"Currency {r.currency} does not match the order currency USD"))

    # credits recorded in the ERP and not yet used, and open receivables, are deducted
    deductions: dict[str, float] = {}
    if po is not None:
        unused = led.recorded_credits(sup.id, po.po_id) - led.credits_used(sup.id, po.po_id, exclude=bill.bill_id)
        if unused > 0.005:
            deductions["recorded_credit"] = round(unused, 2)
    recv = led.open_receivable(sup.id)
    if recv > 0.005:
        deductions["open_receivable"] = recv
    recorded = deductions.get("recorded_credit", 0.0)
    if recorded > r.credit + 0.005:
        mismatches.append(Mismatch("credit_missing", "A recorded return credit is missing from the bill",
                                   {"recorded": recorded, "on_bill": r.credit}))

    erp_bound = T.of(round(max(0.0, cap - recorded - recv), 2), Src.ERP, Src.SETTINGS)
    # The bill can only make the amount smaller: its own net total and its own credit count.
    from_bill = min(payable - max(r.credit, recorded), r.total) - recv
    amount = bounded(T.of(max(0.0, round(from_bill, 2)), Src.SUPPLIER_DOC), erp_bound)

    group = group_of(led, sup, bill)
    res = CheckResult(sup, po, mismatches, margins, erp_bound, group, fair, deductions, amount=amount,
                      duplicate_of=dup[0] if dup else None)
    res.resolution = propose_resolution(res, bill)
    return res


# ---------------------------------------------------------------- proposed resolutions (plan 3.7)

def propose_resolution(res: CheckResult, bill: Bill) -> dict:
    """A decision for the manager, not only evidence. All amounts come from ERP values."""
    codes = set(res.codes)
    r = bill.read
    if "duplicate" in codes:
        return {"action": "reject", "amount": 0.0, "text": f"Reject: duplicate of bill {res.duplicate_of}. Tell the supplier."}
    if "bank_change" in codes:
        return {"action": "hold", "amount": 0.0,
                "text": "Hold. Bank details differ from the registry: freeze the payee and call the supplier on the registered number."}
    if codes & {"no_order", "order_tie", "unknown_supplier", "no_line"}:
        return {"action": "hold", "amount": 0.0, "text": "Hold. Ask the manager to pick the order."}
    steps = []
    for m in res.mismatches:
        if m.code == "price":
            steps.append(f"pay {m.detail['item']} at the order price {m.detail['order_price']:,.2f}; hold the difference; draft a query")
        elif m.code == "qty":
            steps.append(f"pay for the {m.detail['available']:g} received; hold the rest")
        elif m.code == "fair_price":
            d = m.detail
            steps.append(f"pay {d['material']} at the justified price {d['justified_price']:,.2f}; "
                         f"hold the excess {d['overcharge']:,.2f}; draft a query")
        elif m.code == "credit_missing":
            steps.append(f"pay net of the recorded credit {m.detail['recorded']:,.2f}")
        elif m.code == "arith":
            steps.append("pay the amount computed from the lines and the order")
        elif m.code in ("domain", "tax_id", "currency"):
            steps.append(f"check {m.code.replace('_', ' ')} with the supplier before paying")
    if res.deductions.get("open_receivable"):
        steps.append(f"deduct the open receivable {res.deductions['open_receivable']:,.2f}")
    text = "; ".join(steps) if steps else "Pay as billed."
    held = round(max(0.0, r.total - res.amount.value), 2)
    return {
        "action": "pay" if not res.mismatches else "pay_partial",
        "amount": res.amount.value,
        "held": held,
        "text": text[0].upper() + text[1:] + ".",
        "tag": "computed:erp_bounded",
    }
