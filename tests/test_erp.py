"""ERP adapters: CSV/Excel through a mapping, live Odoo, and that both give the agent the same records and decisions."""
import json
import shutil
import urllib.request
from pathlib import Path

import pytest

from apagent import demo
from apagent.domain import Bill, Ledger
from apagent.erp import ErpData, merge_into
from apagent.erp.csvfiles import CsvAdapter, MappingError
from apagent.erp.export import export_from_odoo, export_standard
from apagent.erp.file import FileAdapter


def _odoo_up() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:8069/web/database/selector", timeout=2)
        from apagent.erp.odoo import OdooAdapter
        return bool(OdooAdapter.from_env().uid)
    except Exception:
        return False


def _pos_key(d: ErpData):
    return {(p.po_id, p.supplier_id, p.date, tuple(sorted((l.item, round(l.qty, 4), round(l.price, 4)) for l in p.lines))) for p in d.pos}


def test_csv_standard_round_trip(tmp_path, demo_world):
    src = FileAdapter().fetch()
    export_standard(src, tmp_path)
    got = CsvAdapter(tmp_path, tmp_path / "mapping.json").fetch()
    assert _pos_key(got) == _pos_key(src)
    assert sorted((g.po_id, g.item, g.qty) for g in got.receipts) == sorted((g.po_id, g.item, g.qty) for g in src.receipts if g.qty > 0)
    assert {s.id: (s.tax_id, s.contact, s.wallet, s.bank_account) for s in got.suppliers} == \
           {s.id: (s.tax_id, s.contact, s.wallet, s.bank_account) for s in src.suppliers}


def test_excel_and_wrong_mapping(tmp_path, demo_world):
    import openpyxl

    export_standard(FileAdapter().fetch(), tmp_path)
    # Excel works the same as CSV
    wb = openpyxl.Workbook()
    ws = wb.active
    rows = list(__import__("csv").reader(open(tmp_path / "suppliers.csv")))
    for r in rows:
        ws.append(r)
    wb.save(tmp_path / "suppliers.xlsx")
    m = json.loads((tmp_path / "mapping.json").read_text())
    m["files"]["suppliers"] = "suppliers.xlsx"
    (tmp_path / "mapping.json").write_text(json.dumps(m))
    assert len(CsvAdapter(tmp_path, tmp_path / "mapping.json").fetch().suppliers) == len(rows) - 1
    # A wrong column name gives a clear error, not silent empty data
    m["columns"]["order_lines"]["qty"] = "Quantity Ordered"
    (tmp_path / "mapping.json").write_text(json.dumps(m))
    with pytest.raises(MappingError, match="Quantity Ordered"):
        CsvAdapter(tmp_path, tmp_path / "mapping.json").fetch()


def test_merge_keeps_agent_state(ledger):
    ledger.suppliers["ACME"].probation_left = 3
    ledger.suppliers["ACME"].frozen = True
    data = FileAdapter().fetch()
    merge_into(ledger, data)
    assert ledger.suppliers["ACME"].probation_left == 3 and ledger.suppliers["ACME"].frozen


def test_billed_quantities_from_erp_count_once(ledger):
    po = next(iter(ledger.pos.values()))
    item = po.lines[0].item
    before = ledger.billed_qty(po.po_id, item)
    ledger.billed_external[f"{po.po_id}|{item}"] = 2.0
    assert ledger.billed_qty(po.po_id, item) == before + 2.0


odoo = pytest.mark.skipif(not _odoo_up(), reason="Odoo not running (docker compose -f erp/odoo/docker-compose.yml up -d)")


@odoo
def test_odoo_reads_the_company():
    from apagent.erp.odoo import OdooAdapter

    d = OdooAdapter.from_env().fetch()
    assert {s.id for s in d.suppliers} == set(demo.DEMO_SUPPLIERS)
    assert len(d.pos) > 100 and len(d.receipts) > 100 and d.returns and d.billed
    assert all(n >= 3 for n in d.bills_count.values())


@odoo
def test_odoo_export_screen_csv_equals_live_odoo(tmp_path):
    from apagent.erp.odoo import OdooAdapter

    od = OdooAdapter.from_env()
    export_from_odoo(od, tmp_path)
    a, b = CsvAdapter(tmp_path, tmp_path / "mapping.json").fetch(), od.fetch()
    assert _pos_key(a) == _pos_key(b)
    assert sorted((g.po_id, g.item, round(g.qty, 4)) for g in a.receipts) == sorted((g.po_id, g.item, round(g.qty, 4)) for g in b.receipts)
    assert [(r.po_id, r.item, r.qty, r.credit) for r in a.returns] == [(r.po_id, r.item, r.qty, r.credit) for r in b.returns]
    assert {k: round(v, 4) for k, v in a.billed.items()} == {k: round(v, 4) for k, v in b.billed.items() if v}


@odoo
def test_same_decisions_from_file_and_odoo():
    from apagent.session import Session

    keys = sorted(k for k in demo.load_docs() if k != "t02_resent")
    out = {}
    for erp in ("file", "odoo"):
        s = Session(network=None, erp=erp)
        s.agent.erp = None  # decisions only, nothing posted
        out[erp] = {k: (lambda r: (r["tier"], round(s.led.bills[r["bill"]].amount_usd, 2)))(s.ingest(k, auto_pay=False)) for k in keys}
    assert out["file"] == out["odoo"]


@odoo
def test_payment_recorded_in_odoo_and_counted_once():
    from apagent.erp.odoo import OdooAdapter
    from apagent.session import Session

    od = OdooAdapter.from_env()
    od.remove_agent_postings()
    try:
        s = Session(network=None, erp="odoo")
        r = s.ingest("t01_routine")
        b = s.led.bills[r["bill"]]
        assert r["tier"] == "T1" and b.erp_ref and "(paid)" in b.erp_ref
        mv = od.x("account.move", "search_read", [["payment_reference", "=", f"agent:{b.bill_id}"]], fields=["state", "payment_state", "amount_total"])
        assert mv and mv[0]["state"] == "posted" and mv[0]["payment_state"] == "paid" and abs(mv[0]["amount_total"] - b.amount_usd) < 0.01
        s.sync_erp()
        assert s.led.billed_qty(b.read.po_id, b.read.lines[0].item) == b.read.lines[0].qty  # not double-counted
    finally:
        assert od.remove_agent_postings() >= 1


def test_mapper_drafts_the_odoo_mapping_from_headers_alone(tmp_path):
    """Spec R2: the draft mapping reads the real Odoo export exactly as the hand-written one does."""
    import json
    import shutil

    from apagent.erp.csvfiles import CsvAdapter
    from apagent.erp.mapper import suggest

    src = Path(__file__).resolve().parent.parent / "data" / "erp" / "odoo_export"
    for p in src.glob("*.csv"):
        if not p.name.startswith("._"):
            shutil.copy(p, tmp_path / p.name)
    draft = suggest(tmp_path)
    assert not draft["unmatched"] and draft["receipts_net_of_returns"]
    (tmp_path / "mapping.json").write_text(json.dumps({k: v for k, v in draft.items() if k not in ("unmatched", "notes")}))
    ours = CsvAdapter(tmp_path, tmp_path / "mapping.json").fetch()
    theirs = CsvAdapter(src, src / "mapping.json").fetch()
    assert ours.receipts == theirs.receipts and ours.returns == theirs.returns and ours.billed == theirs.billed
    assert [(p.po_id, p.supplier_id, [(l.item, l.qty, l.price) for l in p.lines]) for p in ours.pos] == \
           [(p.po_id, p.supplier_id, [(l.item, l.qty, l.price) for l in p.lines]) for p in theirs.pos]


def test_mapper_reads_a_kingdee_style_chinese_export(tmp_path):
    from apagent.erp.csvfiles import CsvAdapter
    from apagent.erp.mapper import suggest
    import json

    (tmp_path / "供应商.csv").write_text("供应商编码,供应商名称,税号,邮箱,银行账号\nSZ01,深圳精密五金,91440300X,ap@szjm.cn,6222 0001\n", encoding="utf-8")
    (tmp_path / "采购订单.csv").write_text("采购订单号,供应商名称,订单日期,物料编码,物料名称,数量,单价,入库数量,已开票数量\n"
                                         "PO-1,深圳精密五金,2025-12-01,M-01,螺丝,100,0.8,100,0\n", encoding="utf-8")
    m = suggest(tmp_path)
    assert not m["unmatched"] and m["files"]["suppliers"] == "供应商.csv" and m["files"]["order_lines"] == "采购订单.csv"
    (tmp_path / "mapping.json").write_text(json.dumps({k: v for k, v in m.items() if k not in ("unmatched", "notes")}, ensure_ascii=False))
    d = CsvAdapter(tmp_path, tmp_path / "mapping.json").fetch()
    assert d.suppliers[0].id == "SZ01" and d.pos[0].supplier_id == "SZ01" and d.receipts[0].qty == 100
