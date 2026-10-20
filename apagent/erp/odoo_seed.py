"""Load the demo company into a real Odoo 17: database, apps, suppliers, products, purchase orders, receipts,
history bills and one return. After this, the agent reads the company's records live from Odoo.

    python -m apagent.erp.odoo_seed            (Odoo at ODOO_URL, default http://127.0.0.1:8069)

History loaded: orders of the demo suppliers from HISTORY_FROM, all received; those settled before December get
posted supplier bills. December orders are received but not billed: they are the bills the agent will handle.
"""
from __future__ import annotations

import os
import sys
import time
import xmlrpc.client

from .. import demo
from ..domain import Ledger
from .odoo import OdooAdapter

HISTORY_FROM = os.environ.get("ODOO_HISTORY_FROM", "2025-10-01")
NO_VAT_CHECK = {"no_vat_validation": True}  # the demo suppliers' tax numbers are fictional
MASTER = os.environ.get("ODOO_MASTER_PASSWORD", "admin")


def log(*a):
    print(*a, flush=True)


def ensure_database(url: str, db: str, user: str, password: str) -> None:
    dbs = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/db", allow_none=True)
    try:
        names = dbs.list()
    except xmlrpc.client.Fault:  # Odoo Online (SaaS) hides the database list; the database is the hosted one
        log(f"database list not available; using {db}")
        return
    if db in names:
        log(f"database {db} exists")
        return
    log(f"creating database {db} (a minute)")
    dbs.create_database(MASTER, db, False, "en_US", password, user, None)


def install(od: OdooAdapter, modules: list[str]) -> None:
    mods = od.x("ir.module.module", "search_read", [["name", "in", modules]], fields=["id", "name", "state"])
    todo = [m["id"] for m in mods if m["state"] != "installed"]
    if todo:
        log("installing", [m["name"] for m in mods if m["state"] != "installed"], "(a few minutes)")
        od.x("ir.module.module", "button_immediate_install", todo)
        od._uid = None


def seed(od: OdooAdapter, led: Ledger) -> dict:
    x = od.x
    # Company: Hong Kong address, US dollars (amounts in the demo are USD).
    usd = x("res.currency", "search_read", [["name", "=", "USD"], ["active", "in", [True, False]]], fields=["id"])[0]["id"]
    x("res.currency", "write", [usd], {"active": True})
    hk = x("res.country", "search_read", [["code", "=", "HK"]], fields=["id"])[0]["id"]
    cn = x("res.country", "search_read", [["code", "=", "CN"]], fields=["id"])[0]["id"]
    company = x("res.company", "search_read", [], fields=["id", "currency_id"], limit=1)[0]
    x("res.company", "write", [company["id"]], {"name": led.company.replace(" (fictional)", ""), "country_id": hk})

    # Suppliers (Odoo 20 names the bank account field account_number; earlier versions acc_number)
    acc_field = "account_number" if "account_number" in x("res.partner.bank", "fields_get", attributes=["type"]) else "acc_number"
    sup_ids = {}
    for sid in demo.DEMO_SUPPLIERS:
        s = led.suppliers[sid]
        found = x("res.partner", "search_read", [["ref", "=", sid]], fields=["id"])
        vals = {"name": s.name, "ref": sid, "vat": s.tax_id, "email": s.contact, "is_company": True, "supplier_rank": 1,
                "country_id": hk if s.region == "HK" else cn}
        if found:
            pid = found[0]["id"]
            x("res.partner", "write", [pid], vals, context=NO_VAT_CHECK)
        else:
            pid = x("res.partner", "create", vals, context=NO_VAT_CHECK)
        if not x("res.partner.bank", "search_count", [["partner_id", "=", pid]]):
            x("res.partner.bank", "create", {"partner_id": pid, acc_field: s.wallet or s.bank_account})
        sup_ids[sid] = pid
    log("suppliers", len(sup_ids))

    # Products (storable, billed on received quantities)
    prod_ids = {}
    for code, m in led.materials.items():
        found = x("product.product", "search_read", [["default_code", "=", code]], fields=["id"])
        prod_ids[code] = found[0]["id"] if found else _create_product(od, {
            "name": m.name, "default_code": code, "purchase_method": "receive", "supplier_taxes_id": [(6, 0, [])]})
    log("products", len(prod_ids))

    # Purchase orders
    pos = [po for po in led.pos.values() if po.supplier_id in sup_ids and (po.date >= HISTORY_FROM or po.po_id.startswith("PO-DEC"))]
    pos.sort(key=lambda p: (p.date, p.po_id))
    received = {}
    for g in led.receipts:
        received[(g.po_id, g.item)] = received.get((g.po_id, g.item), 0.0) + g.qty
    settled = {b.read.po_id for b in led.bills.values() if b.status == "paid"}
    # Odoo 20 names the order-line taxes tax_ids; earlier versions taxes_id
    line_tax = "tax_ids" if "tax_ids" in x("purchase.order.line", "fields_get", attributes=["type"]) else "taxes_id"
    existing = {o["name"] for o in x("purchase.order", "search_read", [], fields=["name"])}
    n = billed = 0
    t0 = time.time()
    for po in pos:
        if po.po_id in existing:
            continue
        oid = x("purchase.order", "create", {
            "name": po.po_id, "partner_id": sup_ids[po.supplier_id], "date_order": f"{po.date} 09:00:00", "currency_id": usd,
            "order_line": [(0, 0, {"product_id": prod_ids[l.item], "name": l.desc, "product_qty": l.qty, "price_unit": l.price,
                                   "date_planned": f"{po.date} 09:00:00", line_tax: [(6, 0, [])]}) for l in po.lines]})
        x("purchase.order", "button_confirm", [oid])
        # Receive what the ledger says was received
        picks = x("purchase.order", "read", [oid], fields=["picking_ids"])[0]["picking_ids"]
        for pk in picks:
            moves = x("stock.move", "search_read", [["picking_id", "=", pk]], fields=["id", "product_id"])
            any_qty = False
            for mv in moves:
                code = next(c for c, i in prod_ids.items() if i == mv["product_id"][0])
                q = received.get((po.po_id, code), 0.0)
                x("stock.move", "write", [mv["id"]], {"quantity": q, "picked": q > 0})
                any_qty = any_qty or q > 0
            if any_qty:
                x("stock.picking", "button_validate", [pk], context={"skip_backorder": True, "picking_ids_not_to_backorder": [pk]})
        # History: orders settled before December get a posted supplier bill
        if po.po_id in settled and not po.po_id.startswith("PO-DEC"):
            x("purchase.order", "action_create_invoice", [oid])
            inv = x("purchase.order", "read", [oid], fields=["invoice_ids"])[0]["invoice_ids"]
            if inv:
                x("account.move", "write", inv, {"invoice_date": po.date, "ref": f"HIST-{po.po_id}"})
                x("account.move", "action_post", inv)
                billed += 1
        n += 1
        if n % 25 == 0:
            log(f"  {n}/{len(pos)} orders ({time.time() - t0:.0f}s)")
    log("orders", n, "history bills", billed)

    # One return to a supplier on a history order, so returns are read from real Odoo data.
    try:
        ret = _one_return(od, [p for p in pos if p.po_id in settled and not p.po_id.startswith("PO-DEC")])
    except xmlrpc.client.Fault as e:  # the return wizard differs between Odoo versions; returns are optional
        log("no return recorded:", str(e.faultString).strip().splitlines()[-1][:160])
        ret = None
    return {"orders": n, "history_bills": billed, "return": ret}


def _create_product(od: OdooAdapter, vals: dict) -> int:
    """A stocked product: Odoo 18 and later mark it with is_storable, Odoo 17 and earlier with detailed_type."""
    try:
        return od.x("product.product", "create", {**vals, "type": "consu", "is_storable": True})
    except xmlrpc.client.Fault:
        return od.x("product.product", "create", {**vals, "detailed_type": "product"})


def _one_return(od: OdooAdapter, history) -> str | None:
    x = od.x
    if x("stock.move", "search_count", [["origin_returned_move_id", "!=", False]]):
        return "exists"
    for po in reversed(history):
        o = x("purchase.order", "search_read", [["name", "=", po.po_id]], fields=["picking_ids"])
        if not o or not o[0]["picking_ids"]:
            continue
        pk = o[0]["picking_ids"][0]
        wiz = x("stock.return.picking", "create", {"picking_id": pk}, context={"active_id": pk, "active_model": "stock.picking"})
        x("stock.return.picking", "_compute_moves_locations", [wiz]) if False else None
        lines = x("stock.return.picking.line", "search_read", [["wizard_id", "=", wiz]], fields=["id", "quantity"])
        if not lines:
            continue
        for ln in lines:
            x("stock.return.picking.line", "write", [ln["id"]], {"quantity": round(ln["quantity"] * 0.2, 2) or 1, "to_refund": True})
        action = x("stock.return.picking", "create_returns", [wiz])
        new_pk = action.get("res_id")
        mv = x("stock.move", "search_read", [["picking_id", "=", new_pk]], fields=["id", "product_uom_qty"])
        for m in mv:
            x("stock.move", "write", [m["id"]], {"quantity": m["product_uom_qty"], "picked": True})
        x("stock.picking", "button_validate", [new_pk], context={"skip_backorder": True})
        return po.po_id
    return None


def main() -> None:
    od = OdooAdapter.from_env()
    ensure_database(od.url, od.db, od.user, od.password)
    install(od, ["purchase", "stock", "account"])
    led = Ledger.load(demo.DEMO_DIR / "ledger.json")
    out = seed(od, led)
    data = od.fetch()
    log("read back from Odoo:", {"suppliers": len(data.suppliers), "orders": len(data.pos), "receipts": len(data.receipts),
                                 "returns": len(data.returns), "billed lines": len(data.billed)}, out)


if __name__ == "__main__":
    sys.exit(main())
