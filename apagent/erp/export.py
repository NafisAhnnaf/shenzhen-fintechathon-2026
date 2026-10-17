"""Write ERP data as CSV files with a mapping, for the CSV adapter.

- export_standard(data, folder): our own column names and a matching mapping.json (a template for any ERP).
- export_from_odoo(odoo, folder): what Odoo's own Export screen produces (its field labels as headers, related
  records as display names, products as "[CODE] Name"), plus a mapping for reading it back.

    python -m apagent.erp.export odoo data/erp/odoo_export
    python -m apagent.erp.export standard data/erp/standard
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from . import ErpData

STANDARD_MAPPING = {
    "name": "Standard export",
    "files": {"suppliers": "suppliers.csv", "order_lines": "purchase_lines.csv", "receipts": "receipts.csv",
              "returns": "returns.csv", "billed": "billed.csv", "bills_count": "bills_count.csv"},
    "columns": {
        "suppliers": {"id": "id", "name": "name", "tax_id": "tax_id", "email": "email", "bank_account": "bank_account",
                      "wallet": "wallet", "region": "region"},
        "order_lines": {"po_id": "po_id", "supplier": "supplier_id", "date": "date", "item": "item",
                        "description": "description", "unit": "unit", "qty": "qty", "price": "price"},
        "receipts": {"po_id": "po_id", "item": "item", "qty": "qty", "date": "date"},
        "returns": {"po_id": "po_id", "supplier": "supplier_id", "item": "item", "qty": "qty", "credit": "credit", "date": "date"},
        "billed": {"po_id": "po_id", "item": "item", "qty": "qty"},
        "bills_count": {"supplier": "supplier_id", "count": "count"},
    },
    "date_formats": ["%Y-%m-%d"],
}


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def export_standard(data: ErpData, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    _write(folder / "suppliers.csv", ["id", "name", "tax_id", "email", "bank_account", "wallet", "region"],
           [[s.id, s.name, s.tax_id, s.contact, s.bank_account, s.wallet, s.region] for s in data.suppliers])
    _write(folder / "purchase_lines.csv", ["po_id", "supplier_id", "date", "item", "description", "unit", "qty", "price"],
           [[po.po_id, po.supplier_id, po.date, l.item, l.desc, l.unit, l.qty, l.price] for po in data.pos for l in po.lines])
    _write(folder / "receipts.csv", ["po_id", "item", "qty", "date"], [[g.po_id, g.item, g.qty, g.date] for g in data.receipts])
    _write(folder / "returns.csv", ["po_id", "supplier_id", "item", "qty", "credit", "date"],
           [[r.po_id, r.supplier_id, r.item, r.qty, r.credit, r.date] for r in data.returns])
    _write(folder / "billed.csv", ["po_id", "item", "qty"], [[*k.split("|"), v] for k, v in data.billed.items()])
    _write(folder / "bills_count.csv", ["supplier_id", "count"], [[k, v] for k, v in data.bills_count.items()])
    (folder / "mapping.json").write_text(json.dumps(STANDARD_MAPPING, indent=1))
    return folder


def export_from_odoo(od, folder: Path) -> Path:
    """Use Odoo's export_data (the same call as its Export screen), with Odoo's field labels as column headers."""
    folder.mkdir(parents=True, exist_ok=True)

    def export(model: str, domain: list, fields: list[str], fname: str) -> None:
        labels = od.x(model, "fields_get", [f.split("/")[0] for f in fields], attributes=["string"])
        header = [labels[f.split("/")[0]]["string"] + ("" if "/" not in f else f" / {f.split('/')[1]}") for f in fields]
        ids = od.x(model, "search", domain)
        rows = od.x(model, "export_data", ids, fields)["datas"] if ids else []
        _write(folder / fname, header, rows)

    export("res.partner", [["supplier_rank", ">", 0]], ["ref", "name", "vat", "email", "bank_ids/acc_number", "country_id/code"], "vendors.csv")
    export("purchase.order.line", [["order_id.state", "in", ["purchase", "done"]], ["display_type", "=", False]],
           ["order_id/name", "partner_id", "date_order", "product_id", "name", "product_qty", "price_unit", "qty_received", "qty_invoiced"],
           "purchase_order_lines.csv")
    export("stock.move", [["state", "=", "done"], ["origin_returned_move_id", "!=", False], ["purchase_line_id", "!=", False]],
           ["purchase_line_id/order_id", "partner_id", "product_id", "quantity", "price_unit", "date"], "returns.csv")
    mapping = {
        "name": "Odoo 17 export (Export screen, field labels as headers)",
        "files": {"suppliers": "vendors.csv", "order_lines": "purchase_order_lines.csv", "receipts": "purchase_order_lines.csv",
                  "billed": "purchase_order_lines.csv", "returns": "returns.csv"},
        "receipts_net_of_returns": True,
        "columns": {
            "suppliers": {"id": "Reference", "name": "Name", "tax_id": "Tax ID", "email": "Email",
                          "bank_account": "Banks / acc_number", "region": "Country / code"},
            "order_lines": {"po_id": "Order Reference / name", "supplier": "Partner", "date": "Order Date",
                            "item": {"column": "Product", "transform": "bracket_code"}, "description": "Description",
                            "qty": "Quantity", "price": "Unit Price"},
            "receipts": {"po_id": "Order Reference / name", "item": {"column": "Product", "transform": "bracket_code"},
                         "qty": "Received Qty"},
            "billed": {"po_id": "Order Reference / name", "item": {"column": "Product", "transform": "bracket_code"},
                       "qty": "Billed Qty"},
            "returns": {"po_id": "Purchase Order Line / order_id", "supplier": "Destination Address", "item": {"column": "Product", "transform": "bracket_code"},
                        "qty": "Quantity", "date": "Date Scheduled"},
        },
        "date_formats": ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"],
    }
    (folder / "mapping.json").write_text(json.dumps(mapping, indent=1))
    return folder


if __name__ == "__main__":
    kind, out = sys.argv[1], Path(sys.argv[2])
    if kind == "odoo":
        from .odoo import OdooAdapter
        print(export_from_odoo(OdooAdapter.from_env(), out))
    else:
        from .file import FileAdapter
        print(export_standard(FileAdapter().fetch(), out))
