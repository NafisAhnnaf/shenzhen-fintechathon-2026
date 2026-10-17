"""CSV or Excel exports from any ERP, read through a column-mapping file.

A mapping file (JSON) names the export files and which column holds each field:

{
  "name": "Odoo export",
  "files": {"suppliers": "suppliers.csv", "order_lines": "purchase_lines.csv", "receipts": "receipts.csv",
            "returns": "returns.csv", "billed": "billed.csv"},
  "columns": {
    "suppliers":   {"id": "Reference", "name": "Name", "tax_id": "Tax ID", "email": "Email",
                    "bank_account": "Bank Account", "region": "Country Code"},
    "order_lines": {"po_id": "Order Reference", "supplier": "Vendor", "date": "Order Date",
                    "item": {"column": "Product", "transform": "bracket_code"}, "qty": "Quantity", "price": "Unit Price"},
    ...
  },
  "date_formats": ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"]
}

Rules: a supplier column may hold the supplier's reference or its name. "bracket_code" takes the code in square
brackets ("[CU-ROD] Copper rod" -> "CU-ROD"). Files may be .csv or .xlsx. Payments are written to an outbox CSV the
ERP can import.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..domain import GoodsReceipt, POLine, PurchaseOrder, ReturnRecord
from . import ErpData, ErpSupplier, PaymentRecord

TRANSFORMS = {
    "bracket_code": lambda v: (re.search(r"\[([^\]]+)\]", v).group(1) if re.search(r"\[([^\]]+)\]", v) else v).strip(),
    "upper": lambda v: v.strip().upper(),
    "strip": lambda v: v.strip(),
}


class MappingError(Exception):
    pass


def read_table(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".xlsx":
        import openpyxl

        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = list(ws.iter_rows(values_only=True))
        head = [str(h).strip() if h is not None else "" for h in rows[0]]
        return [{h: ("" if v is None else str(v)) for h, v in zip(head, r)} for r in rows[1:] if any(v is not None for v in r)]
    text = path.read_text(encoding="utf-8-sig")
    # Header names are compared without surrounding spaces (some ERPs export "Name " with a trailing space).
    return [{(k or "").strip(): v for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]


class CsvAdapter:
    name = "csv"

    def __init__(self, folder: str | Path, mapping: str | Path, outbox: Optional[Path] = None):
        self.folder = Path(folder)
        self.mapping_path = Path(mapping) if mapping else self.folder / "mapping.json"
        self.map = json.loads(self.mapping_path.read_text())
        self.outbox = outbox or self.folder / "payments_outbox.csv"

    # ------------------------------------------------------------------ helpers
    def _rows(self, kind: str) -> list[dict[str, str]]:
        f = self.map["files"].get(kind)
        if not f:
            return []
        p = self.folder / f
        if not p.exists():
            raise MappingError(f"{kind}: file {p.name} not found in {self.folder}")
        return read_table(p)

    def _get(self, row: dict, kind: str, field_name: str, required: bool = True, default: str = "") -> str:
        spec: Any = self.map["columns"][kind].get(field_name)
        if spec is None:
            if required:
                raise MappingError(f"{kind}: no column mapped for '{field_name}'")
            return default
        col, transform = (spec, None) if isinstance(spec, str) else (spec["column"], spec.get("transform"))
        if col not in row:
            if required:
                raise MappingError(f"{kind}: column '{col}' (for '{field_name}') is not in the file; columns are {list(row)}")
            return default
        v = (row[col] or "").strip()
        return TRANSFORMS[transform](v) if transform and v else v

    def _num(self, v: str) -> float:
        v = v.replace(",", "").replace("$", "").strip()
        return float(v) if v else 0.0

    def _date(self, v: str) -> str:
        for fmt in self.map.get("date_formats", ["%Y-%m-%d"]):
            try:
                return datetime.strptime(v.strip(), fmt).date().isoformat()
            except ValueError:
                continue
        raise MappingError(f"date '{v}' matches none of {self.map.get('date_formats')}")

    # ------------------------------------------------------------------ fetch
    def fetch(self) -> ErpData:
        sups: list[ErpSupplier] = []
        by_name: dict[str, str] = {}
        for r in self._rows("suppliers"):
            sid = self._get(r, "suppliers", "id")
            email = self._get(r, "suppliers", "email", required=False)
            wallet = self._get(r, "suppliers", "wallet", required=False)
            bank = self._get(r, "suppliers", "bank_account", required=False)
            if not wallet and bank.lower().startswith("0x"):
                wallet, bank = bank, ""
            s = ErpSupplier(id=sid, name=self._get(r, "suppliers", "name"), tax_id=self._get(r, "suppliers", "tax_id", required=False),
                            domain=email.split("@", 1)[1].lower() if "@" in email else "", contact=email,
                            rail="token" if wallet else "bank", wallet=wallet, bank_account=bank,
                            region=self._get(r, "suppliers", "region", required=False, default="HK") or "HK")
            sups.append(s)
            by_name[s.name.lower()] = sid

        def supplier_ref(v: str) -> str:
            return v if v in {s.id for s in sups} else by_name.get(v.lower(), v)

        lines: dict[str, list[POLine]] = defaultdict(list)
        heads: dict[str, tuple[str, str]] = {}
        for r in self._rows("order_lines"):
            po_id = self._get(r, "order_lines", "po_id")
            heads.setdefault(po_id, (supplier_ref(self._get(r, "order_lines", "supplier")), self._date(self._get(r, "order_lines", "date"))))
            lines[po_id].append(POLine(item=self._get(r, "order_lines", "item"),
                                       desc=self._get(r, "order_lines", "description", required=False),
                                       unit=self._get(r, "order_lines", "unit", required=False),
                                       qty=self._num(self._get(r, "order_lines", "qty")),
                                       price=self._num(self._get(r, "order_lines", "price"))))
        pos = [PurchaseOrder(po_id, sid, d, lines[po_id]) for po_id, (sid, d) in heads.items()]

        receipts = [GoodsReceipt(gr_id=f"GR-{i + 1}", po_id=self._get(r, "receipts", "po_id"), item=self._get(r, "receipts", "item"),
                                 qty=self._num(self._get(r, "receipts", "qty")),
                                 date=self._date(self._get(r, "receipts", "date")) if self._get(r, "receipts", "date", required=False) else "")
                    for i, r in enumerate(self._rows("receipts")) if self._num(self._get(r, "receipts", "qty")) > 0]
        line_price = {(po.po_id, l.item): l.price for po in pos for l in po.lines}
        returns = []
        for i, r in enumerate(self._rows("returns")):
            po_id, item = self._get(r, "returns", "po_id"), self._get(r, "returns", "item")
            qty = self._num(self._get(r, "returns", "qty"))
            credit = self._num(self._get(r, "returns", "credit", required=False))
            if not credit:  # no credit column (or zero): the credit owed is the returned quantity at the order price
                credit = round(qty * line_price.get((po_id, item), 0.0), 2)
            d = self._get(r, "returns", "date", required=False)
            returns.append(ReturnRecord(f"RET-{i + 1}", supplier_ref(self._get(r, "returns", "supplier")), po_id, item, qty,
                                        credit, self._date(d) if d else ""))
        if self.map.get("receipts_net_of_returns"):
            # Some ERPs (Odoo) report received quantities net of returns; the agent counts gross receipts and credits.
            back: dict[tuple, float] = defaultdict(float)
            for rt in returns:
                back[(rt.po_id, rt.item)] += rt.qty
            for g in receipts:
                g.qty += back.pop((g.po_id, g.item), 0.0)
        billed: dict[str, float] = defaultdict(float)
        for r in self._rows("billed"):
            billed[f"{self._get(r, 'billed', 'po_id')}|{self._get(r, 'billed', 'item')}"] += self._num(self._get(r, "billed", "qty"))
        counts: dict[str, int] = {}
        for r in self._rows("bills_count"):
            counts[supplier_ref(self._get(r, "bills_count", "supplier"))] = int(self._num(self._get(r, "bills_count", "count")))
        return ErpData("csv", sups, pos, receipts, returns, {k: v for k, v in billed.items() if v}, counts)

    # ------------------------------------------------------------------ payments back
    def record_payment(self, p: PaymentRecord) -> Optional[str]:
        new = not self.outbox.exists()
        with self.outbox.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["date", "supplier", "invoice", "purchase_order", "amount", "reference"])
            w.writerow([p.paid_on, p.supplier_id, p.inv_no, p.po_id, f"{p.amount:.2f}",
                        f"{p.network} tx {p.tx_hash}" if p.tx_hash else f"bill {p.bill_id}"])
        return f"csv:{self.outbox.name}"

    def describe(self) -> dict:
        return {"adapter": "csv", "folder": str(self.folder), "mapping": self.map.get("name", self.mapping_path.name),
                "payments_outbox": str(self.outbox)}
