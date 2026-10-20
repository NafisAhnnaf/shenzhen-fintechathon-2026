"""Bank payment files (pain.001) and statements (camt.053): approved bank transfers go into a file once, the bank's
statement confirms them, and a debit nobody approved becomes a security event."""
import xml.etree.ElementTree as ET

import pytest

from apagent.bankfiles import BadStatement, BankDesk, camt053, pain001, parse_camt053
from apagent.session import Session

NS = {"p": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"}


@pytest.fixture()
def desk():
    s = Session(network=None, signing="server")
    r = s.ingest("t15_bank_rail")  # a mainland supplier paid by bank transfer
    assert r["tier"] == "T1"
    return s, BankDesk(s.agent), r["bill"]


def test_payment_file_is_valid_pain001_and_made_once(desk):
    s, b, bill = desk
    out = b.make_file("finance_manager", "HSBC 400-123456-001")
    doc = ET.fromstring(out["xml"].split("\n", 1)[1])
    assert doc.tag == "{urn:iso:std:iso:20022:tech:xsd:pain.001.001.09}Document"
    assert doc.find(".//p:GrpHdr/p:NbOfTxs", NS).text == "1"
    tx = doc.find(".//p:CdtTrfTxInf", NS)
    assert tx.find("p:PmtId/p:EndToEndId", NS).text == bill
    amt = tx.find("p:Amt/p:InstdAmt", NS)
    assert float(amt.text) == s.led.bills[bill].amount_usd and amt.get("Ccy") == "USD"
    assert tx.find("p:CdtrAcct/p:Id/p:Othr/p:Id", NS).text == "HSBC 323-905550-394"
    assert out["sha256"].startswith("0x") and any(l.kind == "bank_file" for l in s.agent.log.lines)
    with pytest.raises(ValueError, match="no approved bank transfers"):
        b.make_file("finance_manager", "HSBC 400-123456-001")  # each transfer goes into one file only


def test_statement_confirms_payments_and_flags_money_that_left_outside(desk):
    s, b, bill = desk
    f = b.make_file("finance_manager", "HSBC 400-123456-001")
    p = f["payments"][0]
    xml = camt053("HSBC 400-123456-001", [
        {"amount": p["amount"], "direction": "debit", "booked": "2025-12-11", "end_to_end": bill,
         "counterparty": p["creditor"], "account": p["account"], "bank_ref": "B1"},
        {"amount": 4870.0, "direction": "debit", "booked": "2025-12-11", "end_to_end": "",
         "counterparty": "Pearl Delta Alloys Ltd", "account": "BOC 168-318904-551", "bank_ref": "B2"},
        {"amount": 1200.0, "direction": "credit", "booked": "2025-12-11", "counterparty": "A customer", "bank_ref": "B3"},
    ], "S1", "2025-12-11")
    r = b.import_statement("system", xml.encode())
    assert [m["bill"] for m in r["matched"]] == [bill] and b.confirmed[bill]["booked"] == "2025-12-11"
    assert len(r["outside"]) == 1 and r["outside"][0]["supplier"] == "PEARLDELTA" and len(r["credits"]) == 1
    sec = [l for l in s.agent.log.security() if l.kind == "paid_outside_system"]
    assert len(sec) == 1 and sec[0].detail["amount"] == 4870.0
    from apagent import notify
    assert "without an approval" in notify.message(sec[0])["text"]
    again = b.import_statement("system", xml.encode())  # the same statement twice changes nothing
    assert again["repeated"] == 3 and not again["matched"] and not again["outside"]


def test_statement_matches_by_amount_and_creditor_when_the_bank_drops_the_reference(desk):
    s, b, bill = desk
    p = b.make_file("finance_manager", "X")["payments"][0]
    xml = camt053("X", [{"amount": p["amount"], "direction": "debit", "booked": "2025-12-12", "end_to_end": "",
                         "counterparty": p["creditor"].upper(), "account": p["account"], "bank_ref": "R9"}], "S2", "2025-12-12")
    r = b.import_statement("system", xml.encode())
    assert [m["bill"] for m in r["matched"]] == [bill] and not r["outside"] and not r["outstanding"]


def test_hostile_or_wrong_statements_are_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><Document>&a;</Document>'
    with pytest.raises(BadStatement, match="DTD"):
        parse_camt053(bomb)
    with pytest.raises(BadStatement, match="camt.053"):
        parse_camt053(pain001("Co", "A", [], "M1", "2025-12-01").encode())
    with pytest.raises(BadStatement, match="readable"):
        parse_camt053(b"not xml")
