"""Intake: documents, supplier emails, supplier replies and statements, as they arrive.

Documents:
- JSON e-invoice (structured invoice file) -> JsonReader. No OCR is involved.
- PDF or image (PNG/JPEG) -> the quarantined vision-language reader. PDF pages are rendered to images first.
  If no reader is configured (VLM_API_KEY), intake refuses the document with ReaderUnavailable; nothing is guessed.
Emails: the sender's domain identifies the supplier against the registry (trusted). Unknown senders are logged only.
"""
from __future__ import annotations

import csv
import email
import io
import json
import re
from email import policy
from typing import Optional

from .domain import Ledger, Read
from .reader import JsonReader, VLMReader

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class ReaderUnavailable(Exception):
    pass


class BadDocument(Exception):
    pass


def _ext(name: str) -> str:
    m = re.search(r"\.[A-Za-z0-9]+$", name or "")
    return m.group(0).lower() if m else ""


def read_document(filename: str, data: bytes, vlm: Optional[VLMReader] = None) -> tuple[Read, str]:
    """Returns (typed fields, source kind: 'e-invoice' | 'pdf' | 'photo')."""
    ext = _ext(filename)
    if ext == ".json":
        try:
            return JsonReader().read_dict(json.loads(data)), "e-invoice"
        except (KeyError, TypeError, ValueError) as e:
            raise BadDocument(f"not a valid JSON invoice: {e}") from e
    vlm = vlm or VLMReader()
    if ext == ".pdf" or ext in IMAGE_TYPES:
        if not vlm.available():
            raise ReaderUnavailable("PDF and image bills need the vision reader: set VLM_API_KEY (and VLM_MODEL, VLM_BASE_URL)")
        if ext == ".pdf":
            return vlm.read_images(pdf_pages(data), "image/png"), "pdf"
        return vlm.read_images([data], IMAGE_TYPES[ext]), "photo"
    raise BadDocument(f"unsupported file type {ext or '(none)'}: send a .json e-invoice, a .pdf or an image")


def pdf_pages(data: bytes, scale: float = 2.0, max_pages: int = 4) -> list[bytes]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    out = []
    for i in range(min(len(pdf), max_pages)):
        img = pdf[i].render(scale=scale).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


# ---------------------------------------------------------------------------- emails
def parse_email(raw: str) -> dict:
    """Accepts an RFC 822 message (with From:/Subject: headers) or plain text with a leading 'From:' line."""
    msg = email.message_from_string(raw, policy=policy.default)
    sender = msg.get("From", "") or ""
    if msg.is_multipart():
        part = msg.get_body(preferencelist=("plain",))
        body = part.get_content() if part else ""
    else:
        body = msg.get_content() if msg.get("From") else raw
    addr = re.search(r"[\w.+-]+@([\w-]+\.)+[\w-]+", sender)
    return {"from": addr.group(0).lower() if addr else "", "subject": msg.get("Subject", ""), "body": body.strip()}


def supplier_by_sender(led: Ledger, address: str) -> Optional[str]:
    """Exact domain match against the registry. A look-alike domain does not match."""
    if "@" not in address:
        return None
    dom = address.split("@", 1)[1].lower()
    for sid, s in led.suppliers.items():
        if s.domain.lower() == dom:
            return sid
    return None


# ---------------------------------------------------------------------------- supplier replies
def extract_reply_fields(text: str) -> dict:
    """Typed fields from a supplier reply: credit note number and amount. Values are untrusted (supplier_msg)."""
    out: dict = {}
    m = re.search(r"\b(?:credit note|credit memo|CN)\s*(?:no\.?|number|#|:)?\s*([A-Z]{0,4}-?\d{2,10})\b", text, re.I)
    if m:
        ref = m.group(1).upper()
        out["credit_note"] = ref if ref.startswith(("CN", "CR")) else f"CN-{ref.lstrip('-')}"
    amt = re.search(r"(?:US\$|USD|\$|HK\$|HKD)\s*([\d,]+(?:\.\d{1,2})?)", text, re.I) or \
        re.search(r"\bfor\s+([\d,]+\.\d{2})\b", text)
    if amt:
        out["amount"] = float(amt.group(1).replace(",", ""))
    return out


# ---------------------------------------------------------------------------- statements
STATEMENT_COLUMNS = ("date", "ref", "kind", "amount", "against")


def parse_statement(filename: str, data: bytes) -> list[dict]:
    """CSV with columns date, ref, kind (invoice|credit|payment), amount, against; or a JSON list of the same."""
    ext = _ext(filename)
    if ext == ".json":
        rows = json.loads(data)
    elif ext == ".csv":
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    else:
        raise BadDocument("statement must be .csv or .json")
    out = []
    for r in rows:
        try:
            kind = str(r["kind"]).strip().lower()
            if kind not in ("invoice", "credit", "payment"):
                raise ValueError(f"unknown kind {kind}")
            amount = float(str(r["amount"]).replace(",", ""))
            out.append({"date": str(r["date"]).strip(), "ref": str(r["ref"]).strip(), "kind": kind,
                        "amount": -abs(amount) if kind == "credit" else amount,
                        "against": str(r.get("against") or "").strip() or None})
        except (KeyError, ValueError) as e:
            raise BadDocument(f"bad statement row {r}: {e}") from e
    return out
