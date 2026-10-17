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
