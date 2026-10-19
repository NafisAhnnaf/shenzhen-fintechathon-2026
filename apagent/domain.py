"""Company records (the ERP side) and bills. Everything here is trusted except what the reader extracted."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional


@dataclass
class Material:
    code: str
    name: str
    unit: str
    series: Optional[str] = None  # World Bank series name, None if no public index
    pass_through: float = 0.0  # s
    lag_months: int = 1  # L
    tonnes_per_unit: float = 1.0


@dataclass
class Supplier:
    id: str
    name: str
    tax_id: str
    domain: str
    contact: str
    rail: str  # "token" or "bank"
    wallet: str = ""
    bank_account: str = ""
    region: str = "HK"
    since: str = "2020-01-01"
    price_tolerance: float = 0.01
    probation_left: int = 0
    frozen: bool = False
    confirmed_errors: int = 0
    bills_paid: int = 0


@dataclass
class POLine:
    item: str
    desc: str
    unit: str
    qty: float
    price: float


@dataclass
class PurchaseOrder:
    po_id: str
    supplier_id: str
    date: str
    lines: list[POLine]


@dataclass
class GoodsReceipt:
    gr_id: str
    po_id: str
    item: str
    qty: float
    date: str


@dataclass
class ReturnRecord:
    ret_id: str
    supplier_id: str
    po_id: str
    item: str
    qty: float
    credit: float
    date: str


@dataclass
class InvLine:
    item: str
    desc: str
    unit: str
    qty: float
    price: float

    @property
    def amount(self) -> float:
        return round(self.qty * self.price, 2)


@dataclass
class Invoice:
    """What a supplier sends. In the simulator this is ground truth; in production only the reader sees it."""

    inv_no: str
    supplier_id: str
    supplier_name: str
    tax_id: str
    sender_domain: str
    po_id: str
    date: str
    due_date: str
    terms: str  # "net30" or "2/10net30"
    currency: str
    lines: list[InvLine]
    credit: float = 0.0  # credit for returned goods shown on the invoice
    credit_note_ref: str = ""
    bank_account: str = ""
    notes: str = ""
    layout: int = 0
    photo: bool = False

    @property
    def gross(self) -> float:
        return round(sum(l.amount for l in self.lines), 2)

    @property
    def total(self) -> float:
        return round(self.gross - self.credit, 2)


@dataclass
class Read:
    """Typed fields extracted by the quarantined reader. All tagged supplier_doc."""

    inv_no: str
    supplier_name: str
    tax_id: str
    sender_domain: str
    po_id: str
    date: str
    due_date: str
    terms: str
    currency: str
    lines: list[InvLine]
    credit: float
    total: float
    bank_account: str
    confidence: dict[str, float]
    raw_text: str = ""  # free text from the document; only the injection flag sees it

    @property
    def min_confidence(self) -> float:
        return min(self.confidence.values()) if self.confidence else 1.0


@dataclass
class Bill:
    bill_id: str
    received: str
    source: str  # file name or "sim"
    read: Read
    supplier_id: Optional[str] = None
    status: str = "received"  # received, held, approved, paid, rejected, partial
    tier: Optional[str] = None
    amount_usd: float = 0.0  # computed:erp_bounded amount proposed / paid
    erp_bound: float = 0.0
    group: str = "routine"
    score: Optional[float] = None
    reasons: list[str] = field(default_factory=list)
    resolution: Optional[dict] = None
    tx_hash: Optional[str] = None
    paid_on: Optional[str] = None
    injection_p: float = 0.0
    fair_price: Optional[dict] = None
    plan_id: Optional[str] = None
    disputed: bool = False
    hold_reason: Optional[str] = None
    offsets: list[dict] = field(default_factory=list)
    erp_ref: Optional[str] = None  # the payment as recorded in the ERP
    fx: Optional[dict] = None  # a bill in HKD or CNY: original currency, total and the reference rate used (spec C5)


@dataclass
class Receivable:
    bill_id: str
    supplier_id: str
    amount: float
    open: float
    cause: str
    on_chain: bool = False
    claim: Optional[dict] = None


@dataclass
class Case:
    case_id: str
    kind: str  # missed_credit, bank_change, injection, duplicate, fair_price
    supplier_id: str
    status: str  # open, confirmed, dismissed
    detail: dict
    created: str


@dataclass
class Ledger:
    """The company's ERP view plus the agent's own state."""

    company: str
    today: str
    materials: dict[str, Material] = field(default_factory=dict)
    suppliers: dict[str, Supplier] = field(default_factory=dict)
    pos: dict[str, PurchaseOrder] = field(default_factory=dict)
    receipts: list[GoodsReceipt] = field(default_factory=list)
    returns: list[ReturnRecord] = field(default_factory=list)
    bills: dict[str, Bill] = field(default_factory=dict)
    receivables: dict[str, Receivable] = field(default_factory=dict)
    cases: dict[str, Case] = field(default_factory=dict)
    cash_usd: float = 500_000.0
    # Quantity already billed per order line according to the ERP ("po_id|item" -> qty), for bills the agent
    # never saw (billed before it was connected). Bills the agent handles are counted from self.bills.
    billed_external: dict[str, float] = field(default_factory=dict)
    erp_source: str = "file"

    # ------------------------------------------------------------ ERP queries
    def received_qty(self, po_id: str, item: str) -> float:
        return sum(g.qty for g in self.receipts if g.po_id == po_id and g.item == item)

    def billed_qty(self, po_id: str, item: str, exclude: Optional[str] = None) -> float:
        q = self.billed_external.get(f"{po_id}|{item}", 0.0)
        for b in self.bills.values():
            if b.bill_id == exclude or b.status not in ("paid", "approved", "partial"):
                continue
            if b.read.po_id != po_id:
                continue
            q += sum(l.qty for l in b.read.lines if l.item == item)
        return q

    def recorded_credits(self, supplier_id: str, po_id: str) -> float:
        return round(sum(r.credit for r in self.returns if r.supplier_id == supplier_id and r.po_id == po_id), 2)

    def credits_used(self, supplier_id: str, po_id: str, exclude: Optional[str] = None) -> float:
        used = 0.0
        for b in self.bills.values():
            if b.bill_id != exclude and b.supplier_id == supplier_id and b.read.po_id == po_id and b.status in ("paid", "approved"):
                used += b.read.credit
        return used

    def open_receivable(self, supplier_id: str) -> float:
        return round(sum(r.open for r in self.receivables.values() if r.supplier_id == supplier_id), 2)

    def last_price(self, supplier_id: str, item: str, before: str) -> Optional[tuple[float, str]]:
        best = None
        for po in self.pos.values():
            if po.supplier_id != supplier_id or po.date >= before:
                continue
            for l in po.lines:
                if l.item == item and (best is None or po.date > best[1]):
                    best = (l.price, po.date)
        return best

    def price_since(self, supplier_id: str, item: str, before: str) -> Optional[tuple[float, str]]:
        """Current price before a date, and the date that price was first ordered (when it was last changed)."""
        pts = sorted((po.date, l.price) for po in self.pos.values() if po.supplier_id == supplier_id and po.date < before
                     for l in po.lines if l.item == item)
        if not pts:
            return None
        price, since = pts[-1][1], pts[-1][0]
        for d, p in reversed(pts):
            if abs(p - price) > 1e-9:
                break
            since = d
        return price, since

    def paid_bills(self, supplier_id: Optional[str] = None) -> list[Bill]:
        return [b for b in self.bills.values() if b.status == "paid" and (supplier_id is None or b.supplier_id == supplier_id)]

    # ------------------------------------------------------------ persistence
    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=1, default=str))

    @staticmethod
    def load(path: Path) -> "Ledger":
        d = json.loads(path.read_text())
        return ledger_from_dict(d)


def _read_from(d: dict) -> Read:
    d = dict(d)
    d["lines"] = [InvLine(**l) for l in d["lines"]]
    return Read(**d)


def ledger_from_dict(d: dict) -> Ledger:
    led = Ledger(company=d["company"], today=d["today"], cash_usd=d.get("cash_usd", 0.0),
                 billed_external=d.get("billed_external", {}), erp_source=d.get("erp_source", "file"))
    led.materials = {k: Material(**v) for k, v in d["materials"].items()}
    led.suppliers = {k: Supplier(**v) for k, v in d["suppliers"].items()}
    led.pos = {
        k: PurchaseOrder(v["po_id"], v["supplier_id"], v["date"], [POLine(**l) for l in v["lines"]])
        for k, v in d["pos"].items()
    }
    led.receipts = [GoodsReceipt(**g) for g in d["receipts"]]
    led.returns = [ReturnRecord(**r) for r in d["returns"]]
    for k, v in d["bills"].items():
        v = dict(v)
        v["read"] = _read_from(v["read"])
        led.bills[k] = Bill(**v)
    led.receivables = {k: Receivable(**v) for k, v in d["receivables"].items()}
    led.cases = {k: Case(**v) for k, v in d["cases"].items()}
    return led


def iso(d: date) -> str:
    return d.isoformat()
