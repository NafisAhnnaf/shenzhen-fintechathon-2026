"""A live Odoo (Community or Enterprise, v17) through its official XML-RPC API.

Reads:  suppliers (res.partner with supplier_rank > 0; the partner's Reference is the agent's supplier ID),
        confirmed purchase orders and lines, quantities received and returned (stock moves), quantities already
        billed (posted supplier-bill lines linked to order lines), and bills posted per supplier.
Writes: for each payment, a posted supplier bill linked to the order lines, and a payment registered against it,
        with the on-chain transaction in the memo. Bills the agent posts are tagged (payment reference
        "agent:<bill id>") so a later sync does not count them twice.

Configuration (environment): ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD (a password or an API key).
"""
from __future__ import annotations

import os
import xmlrpc.client
from collections import defaultdict
from typing import Any, Optional

from ..domain import GoodsReceipt, POLine, PurchaseOrder, ReturnRecord
from . import ErpData, ErpSupplier, PaymentRecord

AGENT_TAG = "agent:"


class OdooError(Exception):
    pass


class OdooAdapter:
    name = "odoo"

    def __init__(self, url: str, db: str, user: str, password: str):
        self.url, self.db, self.user, self.password = url.rstrip("/"), db, user, password
        self._uid: Optional[int] = None

    @staticmethod
    def from_env() -> "OdooAdapter":
        return OdooAdapter(os.environ.get("ODOO_URL", "http://127.0.0.1:8069"), os.environ.get("ODOO_DB", "payables"),
                           os.environ.get("ODOO_USER", "admin"), os.environ.get("ODOO_PASSWORD", "admin"))

    # ------------------------------------------------------------------ connection
    @property
    def uid(self) -> int:
        if self._uid is None:
            common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
            uid = common.authenticate(self.db, self.user, self.password, {})
            if not uid:
                raise OdooError(f"Odoo refused the login for {self.user} on database {self.db}")
            self._uid = uid
        return self._uid

    def x(self, model: str, method: str, *args: Any, **kw: Any) -> Any:
        models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)
        return models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kw)

    def x_void(self, model: str, method: str, *args: Any, **kw: Any) -> None:
        """Call a method that returns nothing. Odoo's XML-RPC cannot send back None, so it answers with a fault
        after the call has run; that one fault means success."""
        try:
            self.x(model, method, *args, **kw)
        except xmlrpc.client.Fault as f:
            if "cannot marshal None" not in str(f.faultString):
                raise

    def __getstate__(self):  # the agent's state is pickled; connections are not
        return {"url": self.url, "db": self.db, "user": self.user, "password": self.password, "_uid": None}

    # ------------------------------------------------------------------ fetch
    def fetch(self) -> ErpData:
        partners = self.x("res.partner", "search_read", [["supplier_rank", ">", 0]],
                          fields=["id", "ref", "name", "vat", "email", "country_id", "bank_ids"])
        pid_to_sid = {p["id"]: (p["ref"] or f"ODOO{p['id']}") for p in partners}
        bank_fields = self.x("res.partner.bank", "fields_get", [], {"attributes": ["type"]})
        acc_field = "account_number" if "account_number" in bank_fields else "acc_number"
        banks = {b["id"]: b[acc_field] for b in self.x("res.partner.bank", "search_read",
                                                          [["partner_id", "in", list(pid_to_sid)]], fields=[acc_field])}
        countries = {c["id"]: c["code"] for c in self.x("res.country", "search_read", [["id", "in", [p["country_id"][0] for p in partners if p["country_id"]]]], fields=["code"])}
        sups = []
        for p in partners:
            acct = next((banks[b] for b in p["bank_ids"] if b in banks), "")
            wallet = acct if acct.lower().startswith("0x") else ""
            email = p["email"] or ""
            sups.append(ErpSupplier(id=pid_to_sid[p["id"]], name=p["name"], tax_id=p["vat"] or "",
                                    domain=email.split("@", 1)[1].lower() if "@" in email else "", contact=email,
                                    rail="token" if wallet else "bank", wallet=wallet, bank_account="" if wallet else acct,
                                    region=countries.get(p["country_id"][0], "HK") if p["country_id"] else "HK"))

        orders = self.x("purchase.order", "search_read", [["state", "in", ["purchase", "done"]], ["partner_id", "in", list(pid_to_sid)]],
                        fields=["id", "name", "partner_id", "date_order"])
        oid_to_name = {o["id"]: o["name"] for o in orders}
        lines = self.x("purchase.order.line", "search_read", [["order_id", "in", list(oid_to_name)], ["display_type", "=", False]],
                       fields=["id", "order_id", "product_id", "name", "product_qty", "price_unit", "qty_received"])
        prods = {p["id"]: p for p in self.x("product.product", "read", list({l["product_id"][0] for l in lines if l["product_id"]}),
                                            fields=["default_code", "name", "uom_name"])}
        line_item = {l["id"]: (oid_to_name[l["order_id"][0]], prods[l["product_id"][0]]["default_code"] or f"P{l['product_id'][0]}") for l in lines}

        # Returns to the supplier: done stock moves that return a receipt of an order line.
        rets = self.x("stock.move", "search_read",
                      [["state", "=", "done"], ["origin_returned_move_id", "!=", False], ["purchase_line_id", "in", list(line_item)]],
                      fields=["purchase_line_id", "quantity", "date"])
        returned: dict[int, float] = defaultdict(float)
        price = {l["id"]: l["price_unit"] for l in lines}
        returns = []
        for i, m in enumerate(rets):
            lid = m["purchase_line_id"][0]
            returned[lid] += m["quantity"]
            po_name, item = line_item[lid]
            sid = pid_to_sid[next(o["partner_id"][0] for o in orders if o["name"] == po_name)]
            returns.append(ReturnRecord(f"ODOO-RET-{i + 1}", sid, po_name, item, m["quantity"],
                                        round(m["quantity"] * price[lid], 2), str(m["date"])[:10]))

        by_order: dict[str, list[POLine]] = defaultdict(list)
        receipts = []
        for l in lines:
            po_name, item = line_item[l["id"]]
            p = prods[l["product_id"][0]]
            by_order[po_name].append(POLine(item, p["name"], p["uom_name"], l["product_qty"], l["price_unit"]))
            gross = l["qty_received"] + returned.get(l["id"], 0.0)  # Odoo nets returns out of qty_received
            if gross > 0:
                receipts.append(GoodsReceipt(f"ODOO-GR-{l['id']}", po_name, item, gross, ""))
        pos = [PurchaseOrder(o["name"], pid_to_sid[o["partner_id"][0]], str(o["date_order"])[:10], by_order[o["name"]]) for o in orders]

        # Quantities already billed: posted supplier-bill lines linked to order lines, except bills the agent posted.
        bill_lines = self.x("account.move.line", "search_read",
                            [["purchase_line_id", "in", list(line_item)], ["move_id.move_type", "=", "in_invoice"],
                             ["move_id.state", "=", "posted"], ["move_id.payment_reference", "not ilike", AGENT_TAG]],
                            fields=["purchase_line_id", "quantity"])
        billed: dict[str, float] = defaultdict(float)
        for bl in bill_lines:
            po_name, item = line_item[bl["purchase_line_id"][0]]
            billed[f"{po_name}|{item}"] += bl["quantity"]
        counts = {}
        try:
            groups = self.x("account.move", "read_group", [["move_type", "=", "in_invoice"], ["state", "=", "posted"],
                                                           ["partner_id", "in", list(pid_to_sid)]], ["partner_id"], ["partner_id"])
            counts = {pid_to_sid[g["partner_id"][0]]: g.get("partner_id_count", 1) for g in groups if g.get("partner_id")}
        except Exception:
            # Odoo 20+ fallback: count posted moves directly per partner
            try:
                moves = self.x("account.move", "search_read", [["move_type", "=", "in_invoice"], ["state", "=", "posted"],
                                                               ["partner_id", "in", list(pid_to_sid)]], fields=["partner_id"])
                for m in moves:
                    if m.get("partner_id"):
                        sid = pid_to_sid.get(m["partner_id"][0])
                        if sid:
                            counts[sid] = counts.get(sid, 0) + 1
            except Exception:
                pass
        return ErpData("odoo", sups, pos, receipts, returns, dict(billed), counts)

    # ------------------------------------------------------------------ payments back
    def record_payment(self, p: PaymentRecord) -> Optional[str]:
        """A posted supplier bill linked to the order lines, and a payment registered against it."""
        partner = self.x("res.partner", "search_read", [["ref", "=", p.supplier_id]], fields=["id"], limit=1)
        if not partner:
            raise OdooError(f"supplier {p.supplier_id} is not in Odoo")
        po = self.x("purchase.order", "search_read", [["name", "=", p.po_id]], fields=["id", "order_line"], limit=1)
        memo = f"{p.network} tx {p.tx_hash}" if p.tx_hash else f"bill {p.bill_id}"
        line_cmds = []
        if po:
            lines = self.x("purchase.order.line", "read", po[0]["order_line"], fields=["product_id", "name", "qty_received", "qty_invoiced", "price_unit"])
            open_value = sum(max(0.0, l["qty_received"] - l["qty_invoiced"]) * l["price_unit"] for l in lines) or 1.0
            scale = p.amount / open_value  # amounts the agent paid can be below the order value (fair price, credits)
            for l in lines:
                q = max(0.0, l["qty_received"] - l["qty_invoiced"])
                if q > 0:
                    line_cmds.append((0, 0, {"purchase_line_id": l["id"], "product_id": l["product_id"][0], "name": l["name"],
                                             "quantity": q, "price_unit": round(l["price_unit"] * scale, 6), "tax_ids": [(6, 0, [])]}))
        if not line_cmds:
            line_cmds = [(0, 0, {"name": f"Invoice {p.inv_no}", "quantity": 1, "price_unit": p.amount, "tax_ids": [(6, 0, [])]})]
        bill_id = self.x("account.move", "create", {
            "move_type": "in_invoice", "partner_id": partner[0]["id"], "ref": p.inv_no, "invoice_date": p.paid_on,
            "payment_reference": f"{AGENT_TAG}{p.bill_id}", "narration": f"Paid by the payables agent ({p.tier}). {memo}",
            "invoice_line_ids": line_cmds})
        self.x_void("account.move", "action_post", [bill_id])
        wiz = self.x("account.payment.register", "create", {"payment_date": p.paid_on, "communication": memo},
                     context={"active_model": "account.move", "active_ids": [bill_id]})
        self.x("account.payment.register", "action_create_payments", [wiz])
        name = self.x("account.move", "read", [bill_id], fields=["name", "payment_state"])[0]
        return f"odoo:{name['name']} ({name['payment_state']})"

    def remove_agent_postings(self) -> int:
        """Demo reset only: delete the supplier bills and payments the agent posted, so Odoo matches a fresh agent
        ledger. The agent's bills carry payment reference "agent:<bill id>" and its payments a memo starting with
        "<network> tx " or "bill B-". Anything people entered in Odoo is not touched. Safe to repeat."""
        try:
            bills = []
            try:
                bills = self.x("account.move", "search", [["move_type", "=", "in_invoice"], ["payment_reference", "ilike", AGENT_TAG]])
            except Exception:
                pass

            pays = set()
            if bills:
                for bill_field in ("reconciled_bill_ids", "reconciled_invoice_ids"):
                    try:
                        p = self.x("account.payment", "search", [[bill_field, "in", bills]])
                        pays |= set(p)
                        break
                    except Exception:
                        continue

            for memo_field in ("memo", "ref", "payment_reference"):
                try:
                    p = self.x("account.payment", "search", [["partner_type", "=", "supplier"], "|",
                                                             [memo_field, "ilike", " tx 0x"], [memo_field, "=like", "bill B-%"]])
                    pays |= set(p)
                    break
                except Exception:
                    continue

            pays_l = sorted(pays)
            if pays_l:
                try:
                    posted = self.x("account.payment", "search", [["id", "in", pays_l], ["state", "=", "posted"]])
                    if posted:
                        self.x_void("account.payment", "action_draft", posted)
                    self.x_void("account.payment", "unlink", pays_l)
                except Exception:
                    pass

            if bills:
                try:
                    posted_bills = self.x("account.move", "search", [["id", "in", bills], ["state", "=", "posted"]])
                    if posted_bills:
                        self.x_void("account.move", "button_draft", posted_bills)
                    self.x_void("account.move", "unlink", bills)
                except Exception:
                    pass

            return len(bills)
        except Exception:
            return 0

    def describe(self) -> dict:
        return {"adapter": "odoo", "url": self.url, "database": self.db, "user": self.user}
