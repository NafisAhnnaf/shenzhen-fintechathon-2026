"""Market watch (spec C10): adaptive conformal ranges, alert signals, buy-ahead comparison."""
from apagent import marketwatch as mw


def test_aci_keeps_long_run_coverage_near_target():
    for name, r in mw.backtest().items():
        assert r["months"] > 600 and abs(r["coverage"] - 0.9) < 0.03, (name, r)


def test_range_uses_only_data_up_to_the_month():
    a = mw.aci("Copper", "2024-06")
    assert a.month == "2024-06" and a.low < a.price < a.high


def test_alert_needs_two_signals():
    s = mw.signals("Copper", "2025-12")
    assert s["alert"] == (s["signals"] >= 2)


def test_buy_ahead_respects_cash_and_budget():
    out = mw.buy_ahead("Copper", 10.0, until="2025-12")
    assert set(out["options"]) == {"buy_all", "buy_half", "wait"}
    base = out["options"]["wait"]["expected"]
    pick = out["options"][out["suggestion"]]
    assert pick["expected"] - base <= mw.HEDGE_BUDGET * base + 1e-6
    poor = mw.buy_ahead("Copper", 10.0, until="2025-12", cash_available=1000.0)
    assert poor["suggestion"] == "wait"  # cannot pay for stock now


def test_draft_po_uses_company_quantities_and_last_supplier(ledger, calib):
    from apagent.agent import Agent

    ag = Agent(ledger, calib, chain=None)
    out = ag.draft_po("CU-ROD", "buy_half")
    d = out["draft"]
    assert d["status"] == "draft" and d["unit"] == "t" and d["qty"] > 0
    assert d["supplier_id"] in ledger.suppliers
