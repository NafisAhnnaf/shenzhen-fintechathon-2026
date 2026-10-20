"""Intake of real inputs: e-invoices, PDFs, emails, statements, replies."""
import json

import pytest

from apagent import demo
from apagent.intake import (BadDocument, ReaderUnavailable, extract_reply_fields, parse_email, parse_statement,
                            pdf_pages, read_document, supplier_by_sender)
from apagent.reader import VLMReader


def test_e_invoice_is_read(demo_world):
    p = demo.DOCS_DIR / "t01_routine.json"
    r, kind = read_document(p.name, p.read_bytes())
    assert kind == "e-invoice" and r.inv_no == json.loads(p.read_text())["inv_no"]


def test_bad_json_and_unknown_type_rejected():
    with pytest.raises(BadDocument):
        read_document("x.json", b'{"inv_no": 1}')
    with pytest.raises(BadDocument):
        read_document("x.docx", b"hello")


def test_pdf_without_reader_is_refused_not_guessed(demo_world):
    p = demo.DOCS_DIR / "t04_missed_credit.pdf"
    with pytest.raises(ReaderUnavailable):
        read_document(p.name, p.read_bytes(), VLMReader(api_key=""))


def test_rendered_pdfs_are_real(demo_world):
    import io

    from pypdf import PdfReader

    for key in ("t01_routine", "t07_poisoned", "t16_fair_price"):
        raw = (demo.DOCS_DIR / f"{key}.pdf").read_bytes()
        pages = pdf_pages(raw)
        assert pages and pages[0][:4] == b"\x89PNG"
        text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
        assert json.loads((demo.DOCS_DIR / f"{key}.json").read_text())["inv_no"] in text


def test_email_sender_identifies_supplier(ledger):
    m = parse_email((demo.INBOX_DIR / "lionrock_bank_change.eml").read_text())
    assert supplier_by_sender(ledger, m["from"]) == "LIONROCK"
    m2 = parse_email((demo.INBOX_DIR / "lookalike_sender.eml").read_text())
    assert supplier_by_sender(ledger, m2["from"]) is None


def test_statement_csv(demo_world):
    p = demo.STATEMENTS_DIR / "SHATINPCB-2025-12.csv"
    rows = parse_statement(p.name, p.read_bytes())
    assert [r["kind"] for r in rows] == ["invoice", "credit"] and rows[1]["amount"] < 0
    with pytest.raises(BadDocument):
        parse_statement("s.csv", b"date,ref,kind,amount,against\n2025-12-01,X,refund,5,\n")


@pytest.mark.parametrize("text,want", [
    ("Credit note CN-7781 for USD 3,858.76 is attached.", {"credit_note": "CN-7781", "amount": 3858.76}),
    ("We have issued credit note no. 4471 for $1,140.00", {"credit_note": "CN-4471", "amount": 1140.0}),
    ("We will look into it.", {}),
])
def test_reply_fields(text, want):
    assert extract_reply_fields(text) == want


# ------------------------------------------------------------------ vision reader fallback
def _vlm_answer(inv_no="FB-1"):
    return {"inv_no": inv_no, "supplier_name": "S", "tax_id": "T", "sender_domain": "s.hk", "po_id": "PO-1", "date": "2025-12-01",
            "due_date": "2025-12-31", "terms": "net30", "currency": "USD", "lines": [{"item": "X", "desc": "x", "unit": "pc", "qty": 2, "price": 3}],
            "credit": 0, "total": 6, "bank_account": "", "confidence": {"total": 0.9}, "free_text": ""}


class _Resp:
    def __init__(self, code, body):
        self.status_code, self.text, self.headers = code, json.dumps(body), {}

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        import httpx

        if self.status_code >= 400:
            raise httpx.HTTPStatusError(str(self.status_code), request=None, response=self)


def test_reader_falls_back_when_the_first_provider_is_out_of_quota(monkeypatch):
    import httpx

    from apagent.reader import VLMReader

    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append((url, json["response_format"]["type"]))
        if "primary" in url:
            return _Resp(429, {"error": "GenerateRequestsPerDay quota"})
        if json["response_format"]["type"] == "json_schema":  # the fallback's strict mode refuses our schema
            return _Resp(400, {"error": {"message": "invalid JSON schema for response_format"}})
        return _Resp(200, {"choices": [{"message": {"content": "Here you go: " + __import__("json").dumps(_vlm_answer())}}]})

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr("apagent.reader.time.sleep", lambda s: None)
    r = VLMReader("https://primary/v1", "a", "k1", fallback=VLMReader("https://backup/v1", "b", "k2"))
    out = r.read_images([b"img"])
    assert out.inv_no == "FB-1" and out.total == 6
    assert out.reader == "b (fallback)"
    assert ("https://backup/v1/chat/completions", "json_object") in calls  # plain-JSON retry after the schema refusal


def test_reader_without_fallback_raises(monkeypatch):
    import httpx

    from apagent.reader import VLMReader

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(401, {"error": "bad key"}))
    with pytest.raises(httpx.HTTPStatusError):
        VLMReader("https://primary/v1", "a", "k1").read_images([b"img"])
