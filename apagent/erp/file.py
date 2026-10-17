"""The demo ledger file as an ERP: the records the simulator produced. Payments are appended to a journal file."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR
from ..domain import Ledger
from . import ErpData, ErpSupplier, PaymentRecord


class FileAdapter:
    name = "file"

    def __init__(self, path: Optional[Path] = None, journal: Optional[Path] = None):
        self.path = path or DATA_DIR / "demo" / "ledger.json"
        self.journal = journal or DATA_DIR / "state" / "erp_file_payments.jsonl"

    def fetch(self) -> ErpData:
        led = Ledger.load(self.path)
        sups = [ErpSupplier(s.id, s.name, s.tax_id, s.domain, s.contact, s.rail, s.wallet, s.bank_account, s.region)
                for s in led.suppliers.values()]
        # The file's own settled history counts as bills already posted.
        counts: dict[str, int] = {}
        for b in led.bills.values():
            if b.status == "paid" and b.supplier_id:
                counts[b.supplier_id] = counts.get(b.supplier_id, 0) + 1
        return ErpData("file", sups, list(led.pos.values()), list(led.receipts), list(led.returns), {}, counts)

    def record_payment(self, p: PaymentRecord) -> Optional[str]:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a") as f:
            f.write(json.dumps(asdict(p)) + "\n")
        return f"file:{p.bill_id}"

    def describe(self) -> dict:
        return {"adapter": "file", "path": str(self.path), "payments_journal": str(self.journal)}
