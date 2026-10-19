"""Notifications when something needs a person (spec E8).

Every journal line is offered to `on_line`. Lines that need someone become a notification: shown in the app
(GET /api/notifications, computed from the journal, so nothing extra is stored) and, if NOTIFY_WEBHOOK_URL is set,
posted to a chat webhook. NOTIFY_FORMAT picks the body: wecom (WeCom group robot), slack, or teams.
The message carries IDs and amounts only, never supplier text.
"""
from __future__ import annotations

import os
import threading
from typing import Callable, Optional

# kind -> (who should act, severity, text built from the line's typed fields)
RULES: dict[str, tuple[str, str, Callable]] = {
    "decision": ("finance_manager", "action",
                 lambda l: f"Bill {l.bill_id} needs your signature: {l.detail.get('reasons', [''])[0]}"
                 if l.decision == "T2" else None),
    "approve_first": ("owner", "action",
                      lambda l: f"Bill {l.bill_id} (${l.detail.get('amount', 0):,.2f}) needs the owner's signature too"),
    "freeze_payee": ("owner", "alert", lambda l: f"Payee {l.detail.get('supplier')} frozen: {l.detail.get('reason')}"),
    "pause_self": ("owner", "alert", lambda l: f"The agent paused itself: {l.detail.get('reason')}"),
    "case_open": ("finance_manager", "action", lambda l: f"New case {l.detail.get('case')}: {l.detail.get('kind', '').replace('_', ' ')}"),
    "file_claim": ("underwriter", "action", lambda l: f"Reserve claim filed on {l.bill_id}: ${l.detail.get('amount', 0):,.2f}"),
    "claim_dispute": ("arbiter", "action", lambda l: f"The bank disputed the claim on {l.bill_id}"),
    "email_draft": ("finance_manager", "action", lambda l: f"Email {l.detail.get('email')} ({l.detail.get('template', '').replace('_', ' ')}) is waiting for you"),
    "tx_replay": ("owner", "alert", lambda l: "Someone tried to reuse an old owner transaction"),
    "policy_block": ("owner", "alert", lambda l: f"Blocked by policy {l.policy}: {l.detail.get('reason')}"),
    "mailbox_error": ("owner", "alert", lambda l: "The mailbox could not be read"),
    "erp_payment_failed": ("finance_manager", "alert", lambda l: f"Payment for {l.bill_id} could not be posted to the ERP"),
}


def message(line) -> Optional[dict]:
    rule = RULES.get(line.kind)
    if not rule:
        return None
    who, severity, build = rule
    text = build(line)
    if not text:
        return None
    return {"ts": line.ts, "for": who, "severity": severity, "text": text, "bill": line.bill_id, "kind": line.kind}


def _body(text: str) -> dict:
    fmt = os.environ.get("NOTIFY_FORMAT", "wecom").lower()
    if fmt == "slack":
        return {"text": text}
    if fmt == "teams":
        return {"type": "message", "text": text}
    return {"msgtype": "text", "text": {"content": text}}


def on_line(line) -> None:
    url = os.environ.get("NOTIFY_WEBHOOK_URL", "").strip()
    if not url:
        return
    m = message(line)
    if not m:
        return

    def post():
        import httpx
        try:
            httpx.post(url, json=_body(f"[{m['for'].replace('_', ' ')}] {m['text']}"), timeout=10)
        except httpx.HTTPError:
            pass  # a chat outage must not affect payments; the in-app list still has it

    threading.Thread(target=post, daemon=True).start()
