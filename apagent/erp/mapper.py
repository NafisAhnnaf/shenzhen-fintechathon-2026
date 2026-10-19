"""Draft a column mapping for any ERP's export files (spec R2).

    python -m apagent.erp.mapper data/erp/odoo_export           # prints the draft and what it could not match
    python -m apagent.erp.mapper <folder> --write                # writes <folder>/mapping.json

It decides which file holds suppliers, order lines, receipts, billed quantities and returns from the headers, then
matches each field by known column names: English labels used by Odoo, SAP Business One, QuickBooks, Xero and
Dynamics exports, and the Chinese labels used by Kingdee and Yonyou. A person checks the draft once; after that the
CSV adapter reads the exports every sync. Fields it cannot match are listed, never guessed.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

from .csvfiles import read_table

# Known names per field. Matching is on normalised headers (lower case, letters and digits only).
SYN: dict[str, dict[str, list[str]]] = {
    "suppliers": {
        "id": ["reference", "vendor id", "vendor code", "supplier id", "supplier code", "bp code", "card code",
               "account number", "contact id", "供应商编码", "供应商代码"],
        "name": ["name", "vendor name", "supplier name", "company name", "contact name", "card name", "bp name",
                 "vendor", "supplier", "供应商名称", "名称"],
        "tax_id": ["tax id", "tax number", "vat number", "vat", "federal tax id", "br number", "business registration",
                   "统一社会信用代码", "纳税人识别号", "税号"],
        "email": ["email", "email address", "e mail", "邮箱", "电子邮件"],
        "bank_account": ["banks acc number", "bank account", "bank account number", "acc number", "iban",
                         "account no", "银行账号", "开户银行账号"],
        "region": ["country code", "country", "region", "国家"],
    },
    "order_lines": {
        "po_id": ["order reference name", "order reference", "po number", "purchase order number", "purchase order",
                  "po no", "doc num", "document number", "num", "采购订单号", "订单编号", "单据编号"],
        "supplier": ["partner", "vendor", "supplier", "contact name", "vendor name", "card name", "供应商", "供应商名称"],
        "date": ["order date", "po date", "date", "document date", "doc date", "订单日期", "日期", "单据日期"],
        "item": ["product", "item code", "item", "product service", "inventory item code", "sku", "物料编码", "物料代码"],
        "description": ["description", "item description", "memo description", "memo", "物料名称", "名称"],
        "qty": ["quantity", "qty", "ordered qty", "order qty", "数量", "采购数量"],
        "price": ["unit price", "rate", "unit amount", "price", "单价", "含税单价"],
        "unit": ["unit of measure", "uom", "unit", "单位"],
    },
    "receipts": {
        "po_id": ["order reference name", "order reference", "po number", "purchase order", "base ref", "源单编号", "采购订单号"],
        "item": ["product", "item code", "item", "sku", "物料编码"],
        "qty": ["received qty", "qty received", "received quantity", "quantity received", "入库数量", "实收数量"],
        "date": ["receipt date", "date received", "delivery date", "入库日期"],
    },
    "billed": {
        "po_id": ["order reference name", "order reference", "po number", "purchase order", "采购订单号"],
        "item": ["product", "item code", "item", "sku", "物料编码"],
        "qty": ["billed qty", "qty billed", "invoiced qty", "invoiced quantity", "已开票数量", "开票数量"],
    },
    "returns": {
        "po_id": ["purchase order line order id", "order reference", "po number", "purchase order", "base ref", "采购订单号"],
        "supplier": ["destination address", "partner", "vendor", "supplier", "供应商"],
        "item": ["product", "item code", "item", "sku", "物料编码"],
        "qty": ["quantity", "qty", "returned qty", "退货数量", "数量"],
        "date": ["date scheduled", "date", "return date", "退货日期", "日期"],
    },
}
REQUIRED = {"suppliers": ["id", "name"], "order_lines": ["po_id", "supplier", "date", "item", "qty", "price"],
            "receipts": ["po_id", "item", "qty"], "billed": ["po_id", "item", "qty"],
            "returns": ["po_id", "supplier", "item", "qty"]}
# Headers that tell a file's kind apart: present in that kind of export, rare elsewhere.
SIGNS = {"suppliers": ["email", "tax id", "tax number", "bank account", "banks acc number", "邮箱", "税号"],
         "order_lines": ["unit price", "rate", "unit amount", "单价"],
         "receipts": ["received qty", "qty received", "入库数量"],
         "billed": ["billed qty", "invoiced qty", "已开票数量"],
         "returns": ["destination address", "returned qty", "退货数量", "return date"]}
DATE_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y"]


def norm(h: str) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", " ", (h or "").lower()).strip()


def _match(headers: list[str], names: list[str], loose: bool = True) -> Optional[str]:
    """Exact normalised match first, in the order of `names`; then (loose) a header that contains a name as whole
    words. Optional fields use exact matches only, so "Unit Price" is never taken for "unit"."""
    nh = {norm(h): h for h in headers}
    for n in names:
        if norm(n) in nh:
            return nh[norm(n)]
    if not loose:
        return None
    for n in names:
        for k, h in nh.items():
            if re.search(rf"(^| ){re.escape(norm(n))}( |$)", k):
                return h
    return None


def _kinds(headers: list[str]) -> list[str]:
    hs = {norm(h) for h in headers}
    return [k for k, signs in SIGNS.items() if any(norm(s) in hs for s in signs)]


def suggest(folder: Path) -> dict:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".csv", ".xlsx") and not p.name.startswith(("._", "payments_outbox")))
    heads = {p.name: list(read_table(p)[0].keys()) if read_table(p) else [] for p in files}
    mapping = {"name": f"Draft mapping for {folder.name} (check once)", "files": {}, "columns": {},
               "date_formats": DATE_FORMATS, "unmatched": {}}
    for kind in ("suppliers", "order_lines", "receipts", "billed", "returns"):
        cands = [f for f, h in heads.items() if kind in _kinds(h)]
        if not cands:
            continue
        f = cands[0]
        cols, missing = {}, []
        for field, names in SYN[kind].items():
            h = _match(heads[f], names, loose=field in REQUIRED[kind])
            if h is None:
                if field in REQUIRED[kind]:
                    missing.append(field)
                continue
            if field == "item" and any("[" in (r.get(h) or "") for r in read_table(folder / f)[:20]):
                cols[field] = {"column": h, "transform": "bracket_code"}
            else:
                cols[field] = h
        mapping["files"][kind] = f
        mapping["columns"][kind] = cols
        if missing:
            mapping["unmatched"][kind] = missing
    if "receipts" in mapping["files"] and mapping["files"].get("receipts") == mapping["files"].get("returns"):
        mapping["files"].pop("returns")
    mapping["notes"] = []
    if any(" / " in h for hs in heads.values() for h in hs) and "returns" in mapping["files"]:
        # Odoo's Export screen names related fields "Model / field"; Odoo reports receipts net of returns.
        mapping["receipts_net_of_returns"] = True
        mapping["notes"].append("Looks like an Odoo export: received quantities are net of returns, so they are added back.")
    return mapping


def main(argv: list[str]) -> None:
    folder = Path(argv[0])
    m = suggest(folder)
    print(json.dumps(m, indent=1, ensure_ascii=False))
    if m["unmatched"]:
        print("\nNot matched (map these by hand):", json.dumps(m["unmatched"], ensure_ascii=False), file=sys.stderr)
    if "--write" in argv:
        out = {k: v for k, v in m.items() if k not in ("unmatched", "notes")}
        (folder / "mapping.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
        print(f"\nwrote {folder / 'mapping.json'}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
