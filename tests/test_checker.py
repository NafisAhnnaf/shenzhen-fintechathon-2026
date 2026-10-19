"""Checker, fair-price check and proposed resolutions."""
import copy

import pytest

from apagent import checker, demo
from apagent.domain import Bill
from apagent.sim import simulate


def _bill(led, docs, key, bid="T-1", mutate=None):
    r = demo.read_from_doc(docs[key])
    if mutate:
        mutate(r)
    b = Bill(bid, led.today, "pdf", r)
    led.bills[bid] = b
    return b


def test_routine_bill_passes(ledger, docs):
    res = checker.check(ledger, _bill(ledger, docs, "t01_routine"))
    assert res.passed and res.group == "routine"
    assert res.amount.value == pytest.approx(demo.read_from_doc(docs["t01_routine"]).total, abs=0.01)
    assert res.amount.value <= res.erp_bound.value


def test_price_above_tolerance(ledger, docs):
    def up(r):
        r.lines[0].price = round(r.lines[0].price * 1.05, 2)
        r.total = round(sum(l.amount for l in r.lines), 2)
    b = _bill(ledger, docs, "t01_routine", mutate=up)
    res = checker.check(ledger, b)
    assert "price" in res.codes
    assert res.amount.value < b.read.total  # paid at the order price


def test_quantity_above_received(ledger, docs):
    def more(r):
        r.lines[0].qty = r.lines[0].qty * 2
        r.total = round(sum(l.amount for l in r.lines), 2)
    res = checker.check(ledger, _bill(ledger, docs, "t01_routine", mutate=more))
    assert "qty" in res.codes
    assert res.resolution["held"] > 0


def test_exact_and_fuzzy_duplicates(ledger, docs):
    b1 = _bill(ledger, docs, "t02_pdf", "T-1")
    checker.check(ledger, b1)
    b1.status, b1.supplier_id = "paid", "SUNKEE"
    res = checker.check(ledger, _bill(ledger, docs, "t02_pdf", "T-2"))
    assert "duplicate" in res.codes
    res = checker.check(ledger, _bill(ledger, docs, "t02_resent", "T-3"))
    assert "duplicate" in res.codes and res.resolution["action"] == "reject"


def test_bank_change_held(ledger, docs):
    res = checker.check(ledger, _bill(ledger, docs, "t07_poisoned"))
    assert "bank_change" in res.codes and res.resolution["action"] == "hold"


def test_fair_price_flag_uses_real_index(ledger, docs):
    res = checker.check(ledger, _bill(ledger, docs, "t16_fair_price"))
    fp = next(f for f in res.fair if f.flagged)
    assert fp.actual == pytest.approx(0.09, abs=0.002)
    assert fp.excess > 0.05
    assert res.amount.value == pytest.approx(res.erp_bound.value - fp.overcharge, abs=1.0) or res.amount.value < demo.read_from_doc(docs["t16_fair_price"]).total


def test_missed_credit_is_not_catchable_by_matching(ledger, docs):
    """The return was never recorded and the credit is not on the bill: matching cannot see it.
    Statement reconciliation finds it later (test_agent)."""
    res = checker.check(ledger, _bill(ledger, docs, "t04_missed_credit"))
    assert res.passed


def test_amount_never_exceeds_erp_bound_on_simulated_year():
    w = simulate(11, n=300)
    led = copy.deepcopy(w.ledger)
    for ev in w.events:
        b = Bill(f"S{ev.idx}", ev.invoice.date, "pdf", copy.deepcopy(ev.read))
        res = checker.check(led, b)
        assert res.amount.value <= res.erp_bound.value + 1e-6
        assert res.amount.value <= max(0.0, ev.read.total) + 1e-6 or res.deductions
        b.status = "rejected" if "duplicate" in res.codes or not res.supplier else "paid"
        b.supplier_id = res.supplier.id if res.supplier else None
        b.amount_usd = res.amount.value
        led.bills[b.bill_id] = b


def test_hkd_bill_converted_and_checked_like_usd(ledger, docs, calib):
    """Spec C5: a bill in HKD is converted at the reference rate and passes the same checks as its USD twin."""
    from dataclasses import replace

    from apagent.agent import Agent
    from apagent.domain import InvLine

    r = demo.read_from_doc(docs["t01_routine"])
    hkd = replace(r, currency="HKD", lines=[InvLine(l.item, l.desc, l.unit, l.qty, round(l.price * 7.8, 2)) for l in r.lines],
                  credit=round(r.credit * 7.8, 2), total=round(r.total * 7.8, 2))
    ag = Agent(ledger, calib, chain=None)
    b = ag.intake(hkd)
    assert b.fx["currency"] == "HKD" and b.fx["total"] == hkd.total and b.read.currency == "USD"
    out = ag.process(b.bill_id)
    assert out["tier"] == "T1" and abs(ledger.bills[b.bill_id].amount_usd - r.total) < 0.05


def test_unsupported_currency_is_held(ledger, docs, calib):
    from dataclasses import replace

    from apagent.agent import Agent

    ag = Agent(ledger, calib, chain=None)
    b = ag.intake(replace(demo.read_from_doc(docs["t01_routine"]), currency="EUR"))
    out = ag.process(b.bill_id)
    assert out["tier"] != "T1" and any("Currency EUR" in x for x in out["reasons"])


def test_price_rise_on_unindexed_item_flagged_by_supplier_history(ledger, docs):
    """Spec C4: fasteners have no public index; a 30% rise is far above Kai Tak's usual price changes."""
    from dataclasses import replace

    from apagent.domain import InvLine

    r = demo.read_from_doc(docs["t01_routine"])
    assert ledger.materials.get(r.lines[0].item) is None or ledger.materials[r.lines[0].item].series is None
    up = replace(r, inv_no="KAI-2512099", lines=[InvLine(l.item, l.desc, l.unit, l.qty, round(l.price * 1.3, 2)) for l in r.lines])
    up = replace(up, total=round(sum(l.amount for l in up.lines) - up.credit, 2))
    res = checker.check(ledger, Bill("B-HIST", ledger.today, "test", up))
    hp = next(m.detail for m in res.mismatches if m.code == "price_history")
    assert hp["flagged"] and hp["actual"] > hp["band"] and res.amount.value < up.total
