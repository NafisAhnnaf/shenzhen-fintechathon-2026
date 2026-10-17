# Connecting another ERP

The agent needs six things from an ERP and gives back one. An adapter (`apagent/erp/`) supplies them as `ErpData`.

| The agent needs | Field in `ErpData` | Odoo | SAP Business One | Dynamics 365 Business Central | Xero |
| --- | --- | --- | --- | --- | --- |
| Suppliers, tax ID, email, bank account or wallet | `suppliers` | `res.partner`, `res.partner.bank` | BusinessPartners | vendors | Contacts |
| Purchase orders and lines | `pos` | `purchase.order(.line)` | PurchaseOrders | purchaseOrders | PurchaseOrders |
| Goods received per line | `receipts` | stock moves (`qty_received`) | PurchaseDeliveryNotes | purchaseReceipts | (none: no receipts) |
| Returns to the supplier | `returns` | return stock moves | PurchaseReturns | purchaseCreditMemos | CreditNotes |
| Quantity already billed per line | `billed` | posted bill lines | PurchaseInvoices | purchaseInvoices | Bills |
| Bills posted per supplier (tenure) | `bills_count` | posted bills | PurchaseInvoices | purchaseInvoices | Bills |
| **Gives back:** the payment | `record_payment()` | bill + registered payment | VendorPayments | vendorPayments | Payments |

Three ways in, from least to most work:

1. **Export files.** Every ERP can export these lists. Write a mapping file that names the files and columns
   (see `data/erp/odoo_export/mapping.json` for a real Odoo export, or `apagent/erp/export.py` for the standard
   layout) and run with `ERP=csv`. Options: `bracket_code` takes codes like `[CU-ROD]` out of product names;
   `receipts_net_of_returns` adds returns back when the ERP nets them out.
2. **A live adapter.** Copy `apagent/erp/odoo.py`, implement `fetch()` with the ERP's API and `record_payment()`,
   and register it in `make_adapter()`. Keep the agent's own postings tagged so a sync does not count them twice.
3. **Test it** the way `tests/test_erp.py` tests Odoo: the same December bills must get the same decisions as from
   the demo file.

Known limits: Xero and QuickBooks Online have no goods receipts, so the quantity check falls back to ordered
quantities, which is weaker. Kingdee and Yonyou have APIs but need a partner account.
