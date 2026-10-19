"""Email the agent sends and reads (spec V2, R4, policy S11).

Outgoing: every message comes from a fixed template filled with typed values (amounts, dates, invoice numbers
that pass a strict pattern, transaction references). Supplier text never goes into an email (S6), the recipient is
always the supplier's registered contact (S1), and no template asks for, confirms or changes bank details.
Templates that change what the company will pay need the finance manager first (S11).

    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_TLS (starttls|ssl|none)
    without SMTP_HOST, messages are written as .eml files to data/state/outbox/ (the demo can show them)

Incoming: an IMAP inbox, or a local drop folder for the demo.

    IMAP_HOST, IMAP_PORT (993), IMAP_USER, IMAP_PASSWORD, IMAP_FOLDER (INBOX)
    without IMAP_HOST, .eml files placed in data/state/mailbox/ are read once each
"""
from __future__ import annotations

import email
import hashlib
import os
import re
import smtplib
import ssl
import time
from email import policy
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Optional

from .config import DATA_DIR

OUTBOX_DIR = DATA_DIR / "state" / "outbox"
MAILBOX_DIR = DATA_DIR / "state" / "mailbox"
BILL_TYPES = {".json", ".pdf", ".png", ".jpg", ".jpeg", ".webp"}

SIGNOFF = "Accounts payable\n{company}"

# name -> (subject, body, sent without a person?)
TEMPLATES: dict[str, tuple[str, str, bool]] = {
    "payment_notice": (
        "Payment for invoice {inv_no}",
        "Dear {supplier},\n\nWe have paid invoice {inv_no}: {amount} on {date}.\nPayment reference: {ref}\n\n"
        "No action is needed.\n\n" + SIGNOFF,
        True),
    "query": (
        "{qid}: invoice {inv_no}",
        "Dear {supplier},\n\n{text}\n\nPlease quote our reference {qid} in your reply.\n\n" + SIGNOFF,
        True),
    "duplicate_notice": (
        "Invoice {inv_no} not paid: already processed",
        "Dear {supplier},\n\nInvoice {inv_no} for {billed} repeats invoice {dup_of}, which we have already "
        "processed. We will not pay it a second time.\nIf this is a different delivery, please reply with the "
        "purchase order and delivery note.\n\n" + SIGNOFF,
        True),
    "bank_change_alert": (
        "Request to change your payment details",
        "Dear {supplier},\n\nWe received a message asking us to change the bank details we hold for your company. "
        "We never change payment details because of an email or an invoice.\nOur finance team will call you on the "
        "number we have on file to confirm. Until then, payments to you are paused.\nIf you did not send this "
        "request, someone may be impersonating your company.\n\n" + SIGNOFF,
        True),
    "refund_request": (
        "Refund of {amount} for invoice {inv_no}",
        "Dear {supplier},\n\nOur reconciliation of your statement shows a credit of {amount} against invoice "
        "{inv_no}, which we paid in full on {date}.\nPlease refund {amount} to the account you have for us, or "
        "confirm that you will deduct it from your next invoice.\nOur reference: {ref}\n\n" + SIGNOFF,
        False),
}
AUTO_TEMPLATES = {k for k, v in TEMPLATES.items() if v[2]}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./_-]{0,39}$")
MONEY = re.compile(r"^\$[\d,]+\.\d{2}$")  # a formatted amount, e.g. $2,397.60


def auto_email_on() -> bool:
    return os.environ.get("AUTO_EMAIL", "on").lower() not in ("off", "0", "false", "no")


def safe_id(value: str, fallback: str) -> str:
    """Invoice numbers come from supplier documents: echo one only if it looks like an identifier."""
    return value if SAFE_ID.match(value or "") else fallback


def render(template: str, values: dict) -> tuple[str, str]:
    subject, body, _ = TEMPLATES[template]
    return subject.format(**values), body.format(**values)


# ------------------------------------------------------------------ outgoing
class Outbox:
    """No mail server configured: keep each message as an .eml file."""

    name = "outbox"

    def __init__(self, folder: Optional[Path] = None):
        self.folder = folder or OUTBOX_DIR

    def send(self, msg: EmailMessage) -> str:
        self.folder.mkdir(parents=True, exist_ok=True)
        mid = msg["Message-ID"]
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{hashlib.sha1(mid.encode()).hexdigest()[:8]}.eml"
        (self.folder / name).write_bytes(msg.as_bytes())
        return name

    def describe(self) -> dict:
        return {"kind": "outbox", "folder": str(self.folder)}


class Smtp:
    name = "smtp"

    def __init__(self):
        self.host = os.environ["SMTP_HOST"]
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.user = os.environ.get("SMTP_USER", "")
        self.password = os.environ.get("SMTP_PASSWORD", "")
        self.tls = os.environ.get("SMTP_TLS", "starttls")

    def send(self, msg: EmailMessage) -> str:
        ctx = ssl.create_default_context()
        if self.tls == "ssl":
            s = smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=30)
        else:
            s = smtplib.SMTP(self.host, self.port, timeout=30)
            if self.tls == "starttls":
                s.starttls(context=ctx)
        with s:
            if self.user:
                s.login(self.user, self.password)
            s.send_message(msg)
        return msg["Message-ID"]

    def describe(self) -> dict:
        return {"kind": "smtp", "host": self.host, "port": self.port, "user": self.user}


def mailer():
    return Smtp() if os.environ.get("SMTP_HOST") else Outbox()


def sender_address() -> str:
    return os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "ap@harbour-precision.example"


def build(to: str, subject: str, body: str, reply_ref: Optional[str] = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender_address()
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=sender_address().split("@")[-1])
    if reply_ref:
        msg["X-AP-Reference"] = reply_ref
    msg.set_content(body)
    return msg


# ------------------------------------------------------------------ incoming
class FolderMailbox:
    """Demo mailbox: .eml files dropped into a folder are read once each."""

    name = "folder"

    def __init__(self, folder: Optional[Path] = None):
        self.folder = folder or MAILBOX_DIR

    def fetch(self, seen: set) -> list[tuple[str, bytes]]:
        if not self.folder.exists():
            return []
        out = []
        for p in sorted(self.folder.glob("*.eml")):
            if p.name.startswith("._") or p.name in seen:
                continue
            out.append((p.name, p.read_bytes()))
        return out

    def describe(self) -> dict:
        return {"kind": "folder", "folder": str(self.folder)}


class ImapMailbox:
    name = "imap"

    def __init__(self):
        self.host = os.environ["IMAP_HOST"]
        self.port = int(os.environ.get("IMAP_PORT", "993"))
        self.user = os.environ.get("IMAP_USER", "")
        self.password = os.environ.get("IMAP_PASSWORD", "")
        self.folder = os.environ.get("IMAP_FOLDER", "INBOX")

    def fetch(self, seen: set) -> list[tuple[str, bytes]]:
        import imaplib

        out = []
        with imaplib.IMAP4_SSL(self.host, self.port) as m:
            m.login(self.user, self.password)
            m.select(self.folder)
            _, data = m.search(None, "UNSEEN")
            for num in (data[0] or b"").split():
                _, parts = m.fetch(num, "(RFC822)")
                raw = parts[0][1]
                mid = email.message_from_bytes(raw, policy=policy.default).get("Message-ID") or num.decode()
                if mid not in seen:
                    out.append((mid, raw))
        return out

    def describe(self) -> dict:
        return {"kind": "imap", "host": self.host, "user": self.user, "folder": self.folder}


def mailbox():
    return ImapMailbox() if os.environ.get("IMAP_HOST") else FolderMailbox()


def split_message(raw: bytes) -> tuple[str, list[tuple[str, bytes]]]:
    """(the message as text for the reply path, [(filename, bytes) of bill attachments])."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    files = []
    for part in msg.iter_attachments():
        name = part.get_filename() or ""
        if Path(name).suffix.lower() in BILL_TYPES:
            files.append((Path(name).name, part.get_payload(decode=True) or b""))
    return raw.decode("utf-8", errors="replace"), files
