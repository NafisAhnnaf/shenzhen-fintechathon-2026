"""ERP adapters: where the company's own records come from, and where payments are recorded back.

The agent needs six things from an ERP. Each adapter supplies them in one shape (ErpData):
- suppliers with tax ID, contact, bank account or wallet;
- purchase orders and their lines (item, quantity, agreed price);
- goods received per order line;
- returns to suppliers (with the credit owed);
- quantity already billed per order line (bills the agent never saw);
- and it records each payment back (record_payment).

Adapters:
- FileAdapter  (file)  the demo ledger file, as before.
- CsvAdapter   (csv)   CSV or Excel exports from any ERP, read through a column-mapping file.
- OdooAdapter  (odoo)  a live Odoo instance through its official XML-RPC API.
Adding another ERP means writing one more adapter with fetch() and record_payment().
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Protocol

from ..domain import GoodsReceipt, Ledger, PurchaseOrder, ReturnRecord, Supplier


@dataclass
class ErpSupplier:
    id: str  # stable reference used by the agent and the on-chain payee registry
    name: str
    tax_id: str
    domain: str
    contact: str
    rail: str  # "token" (stablecoin wallet) or "bank"
    wallet: str = ""
    bank_account: str = ""
    region: str = "HK"


@dataclass
class ErpData:
    source: str
    suppliers: list[ErpSupplier]
    pos: list[PurchaseOrder]
    receipts: list[GoodsReceipt]
    returns: list[ReturnRecord]
    billed: dict[str, float] = field(default_factory=dict)  # "po_id|item" -> quantity already billed
    bills_count: dict[str, int] = field(default_factory=dict)  # supplier id -> bills already posted in the ERP


@dataclass
class PaymentRecord:
    bill_id: str
    supplier_id: str
    inv_no: str
    po_id: str
    amount: float
    paid_on: str
    tx_hash: Optional[str]
    tier: str
    network: str


class ErpAdapter(Protocol):
    name: str

    def fetch(self) -> ErpData: ...

    def record_payment(self, p: PaymentRecord) -> Optional[str]: ...

    def describe(self) -> dict: ...


def merge_into(led: Ledger, data: ErpData) -> dict:
    """Refresh the company records in the agent's ledger from the ERP. The agent's own state (bills it handled,
    receivables, cases, probation, freezes, error counts) is kept."""
    seen = set()
    added = 0
    # Bills already posted per supplier, for tenure. When the ERP data has no count, use orders already billed.
    counts = dict(data.bills_count)
    if not counts:
        billed_pos = {k.split("|")[0] for k, v in data.billed.items() if v > 0}
        for po in data.pos:
            if po.po_id in billed_pos:
                counts[po.supplier_id] = counts.get(po.supplier_id, 0) + 1
    for s in data.suppliers:
        seen.add(s.id)
        cur = led.suppliers.get(s.id)
        if cur is None:
            first = min((po.date for po in data.pos if po.supplier_id == s.id), default=date.today().isoformat())
            led.suppliers[s.id] = Supplier(id=s.id, name=s.name, tax_id=s.tax_id, domain=s.domain, contact=s.contact,
                                           rail=s.rail, wallet=s.wallet, bank_account=s.bank_account, region=s.region,
                                           since=first, bills_paid=counts.get(s.id, 0))
            added += 1
        else:
            cur.name, cur.tax_id, cur.domain, cur.contact = s.name, s.tax_id, s.domain, s.contact
            cur.rail, cur.wallet, cur.bank_account, cur.region = s.rail, s.wallet, s.bank_account, s.region
            if s.id in counts:
                own = sum(1 for b in led.bills.values() if b.supplier_id == s.id and b.status == "paid" and not b.bill_id.startswith("H"))
                cur.bills_paid = max(cur.bills_paid, counts[s.id] + own)
    led.pos = {po.po_id: po for po in data.pos}
    led.receipts = list(data.receipts)
    led.returns = list(data.returns)
    led.billed_external = dict(data.billed)
    led.erp_source = data.source
    return {"source": data.source, "suppliers": len(data.suppliers), "new_suppliers": added, "orders": len(data.pos),
            "receipts": len(data.receipts), "returns": len(data.returns)}


def make_adapter(kind: Optional[str] = None) -> ErpAdapter:
    kind = kind or os.environ.get("ERP", "file")
    if kind == "file":
        from .file import FileAdapter
        return FileAdapter()
    if kind == "csv":
        from .csvfiles import CsvAdapter
        return CsvAdapter(os.environ.get("ERP_CSV_DIR", ""), os.environ.get("ERP_CSV_MAPPING", ""))
    if kind == "odoo":
        from .odoo import OdooAdapter
        return OdooAdapter.from_env()
    raise ValueError(f"unknown ERP adapter {kind}")
