"""The Postgres store: business records as rows, a hash-chained append-only journal, signed working memory,
one set of rows per company. Runs against a local Postgres (TEST_DATABASE_URL), never the production database."""
import os

import pytest

from apagent import demo

URL = os.environ.get("TEST_DATABASE_URL", "postgresql://apagent@/apagent_test?host=/tmp&port=5544")


def _pg_up() -> bool:
    try:
        import psycopg
        with psycopg.connect(URL, connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_up(), reason="local test Postgres not running")


@pytest.fixture()
def store(monkeypatch):
    import psycopg

    from apagent.store import Store

    monkeypatch.setenv("APP_SECRET", "test-secret")
    with psycopg.connect(URL, autocommit=True) as c:  # a clean schema for each test
        c.execute("drop schema public cascade")
        c.execute("create schema public")
    st = Store(URL)
    st.migrate()
    return st


def _session_with_work():
    from apagent.session import Session

    s = Session(network=None, signing="server")
    for k in ("t01_routine", "t16_fair_price", "t04_missed_credit", "t07_poisoned"):
        s.ingest(k)
    return s


def test_round_trip_keeps_every_record(store):
    s = _session_with_work()
    store.create_company("acme-co", s.led.company, "localhost", {"contracts": {}, "roles": {}})
    counts = store.save("acme-co", s)
    assert counts["bills"] == 4 and counts["journal"] == len(s.agent.log.lines) and counts["erp"] == 1
    r = store.load("acme-co")
    live = lambda x: {k: (b.status, b.amount_usd, b.tier) for k, b in x.led.bills.items() if not k.startswith("H")}
    assert live(r) == live(s)
    assert len(r.led.bills) == len(s.led.bills)  # history from the ERP mirror, live bills from rows
    assert [l.kind for l in r.agent.log.lines] == [l.kind for l in s.agent.log.lines]
    assert [e["id"] for e in r.agent._emails()] == [e["id"] for e in s.agent._emails()]
    assert r.led.suppliers["TSUENWAN"].frozen and r.agent.money == s.agent.money
    paid = next(k for k, b in s.led.bills.items() if not k.startswith("H") and b.status == "paid")
    assert r.agent.bill_card(paid)["amount"] == s.agent.bill_card(paid)["amount"]
    # the restored session keeps working
    r.ingest("t13_net30")
    assert store.save("acme-co", r)["bills"] >= 1


def test_second_save_sends_only_changes(store):
    s = _session_with_work()
    store.create_company("c1", s.led.company, "localhost", {"contracts": {}, "roles": {}})
    store.save("c1", s)
    again = store.save("c1", s)
    assert again == {"bills": 0, "suppliers": 0, "journal": 0, "emails": 0, "cases": 0, "erp": 0}
    s.ingest("t13_net30")
    after = store.save("c1", s)
    assert after["bills"] == 1 and after["journal"] > 0 and after["erp"] == 0


def test_journal_is_append_only_and_tamper_evident(store):
    import psycopg

    s = _session_with_work()
    store.create_company("c2", s.led.company, "localhost", {"contracts": {}, "roles": {}})
    store.save("c2", s)
    v = store.verify_journal("c2")
    assert v["ok"] and v["rows"] == len(s.agent.log.lines)
    with pytest.raises(psycopg.errors.RaiseException):
        with store.connect() as c:
            c.execute("update journal set kind='approve' where company_id='c2' and seq=1")
    with store.connect() as c:  # someone with database admin rights bypasses the rule
        c.execute("set local app.allow_purge = 'on'")
        c.execute("update journal set leaf=%s where company_id='c2' and seq=2", ("0x" + "ab" * 32,))
    v = store.verify_journal("c2")
    assert not v["ok"] and v["broken_at"][0] == 2


def test_altered_working_memory_is_refused(store):
    s = _session_with_work()
    store.create_company("c3", s.led.company, "localhost", {"contracts": {}, "roles": {}})
    store.save("c3", s)
    with store.connect() as c:
        c.execute("update agent_state set data = data || '\\x00'::bytea where company_id='c3'")
    with pytest.raises(RuntimeError, match="signature"):
        store.load("c3")


def test_companies_are_kept_apart(store):
    a, b = _session_with_work(), __import__("apagent.session", fromlist=["Session"]).Session(network=None, signing="server")
    b.ingest("t13_net30")
    for cid, s in (("a", a), ("b", b)):
        store.create_company(cid, s.led.company, "localhost", {"contracts": {}, "roles": {}})
        store.save(cid, s)
    ra, rb = store.load("a"), store.load("b")
    count = lambda x: sum(1 for k in x.led.bills if not k.startswith("H"))
    assert count(ra) == 4 and count(rb) == 1
    store.delete_company("b")
    assert store.load("b") is None and store.load("a") is not None


def test_api_runs_on_the_database_and_survives_a_restart(store, monkeypatch):
    """The API with STATE_STORE=postgres: reset, pay a bill, restart, and the state comes back from the rows."""
    from fastapi.testclient import TestClient

    from apagent import session as S
    from tests.test_e2e_chain import _node_up

    if not _node_up():
        pytest.skip("local hardhat node not running")
    monkeypatch.setenv("STATE_STORE", "postgres")
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("AUTH", "off")
    monkeypatch.setattr(S, "_STORE", None)
    from apagent import api
    api._sessions.clear()
    c = TestClient(api.app)
    assert c.post("/api/admin/reset").status_code == 200
    paid = c.post("/api/inbox/documents/t01_routine").json()
    assert paid["tier"] == "T1" and paid["tx"]["ok"]
    api._sessions.clear()  # restart
    S._STORE = None
    st = c.get("/api/state").json()
    assert st["consistency"]["ok"]
    bill = c.get(f"/api/bills/{paid['bill']}").json()
    assert bill["status"] == "paid" and bill["tx_hash"] == paid["tx"]["tx_hash"]
    assert store.verify_journal("demo")["ok"]
    api._sessions.clear()


def test_public_anchor_seals_every_company_and_gives_each_a_proof(store):
    """One root per period over every company's journal head; each company gets a proof; an unchanged hour sends
    nothing; an altered row no longer matches what was anchored."""
    from tests.test_e2e_chain import _node_up
    if not _node_up():
        pytest.skip("local hardhat node not running")
    from apagent import public_anchor as P
    from apagent.chain import Chain

    for cid, doc in (("co-a", "t01_routine"), ("co-b", "t13_net30")):
        s = __import__("apagent.session", fromlist=["Session"]).Session(network=None, signing="server")
        s.ingest(doc)
        store.create_company(cid, s.led.company, "localhost", {"contracts": {}, "roles": {}})
        store.save(cid, s)
    ch = Chain("localhost", anchor_only=True)
    import time as _t
    period = int(_t.time())  # unique per run on the shared local chain
    rec = P.anchor_once(store, ch, period=period)
    assert rec and rec["tx_hash"] and [h["company"] for h in rec["leaves"]] == ["co-a", "co-b"]
    assert P.anchor_once(store, ch, period=period + 1) is None  # nothing changed
    for cid in ("co-a", "co-b"):
        p = P.proof_for(store, cid)
        assert p["included"] and p["proof_ok"] and p["rows_match"] and p["anchor"]["root"] == rec["root"]
    on_chain = ch.anchor.functions.roots(period).call() if hasattr(ch.anchor.functions, "roots") else None
    if on_chain is not None:
        assert "0x" + on_chain.hex() == rec["root"]
    with store.connect() as c:
        c.execute("set local app.allow_purge = 'on'")
        c.execute("update journal set leaf=%s where company_id='co-a' and seq=0", ("0x" + "cd" * 32,))
    assert P.proof_for(store, "co-a")["rows_match"] is False
