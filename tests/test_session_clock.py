"""The ledger clock: the sample company keeps its demo date; a company on a real ERP (or CLOCK=real) runs on the
calendar, closing (anchoring) the last open day before it moves."""
from datetime import date

from apagent.session import Session


def test_demo_company_keeps_its_date_and_real_clock_follows_the_calendar(monkeypatch):
    s = Session(network=None, signing="server")
    start = s.led.today
    monkeypatch.delenv("CLOCK", raising=False)
    assert s.clock() == "demo" and not s.sync_clock() and s.led.today == start
    monkeypatch.setenv("CLOCK", "real")
    s.led.today = "2026-01-05"
    closed = []
    monkeypatch.setattr(s, "close_day", lambda: closed.append(s.led.today))
    assert s.sync_clock() and s.led.today == date.today().isoformat() and closed == ["2026-01-05"]
    assert not s.sync_clock()  # already today
