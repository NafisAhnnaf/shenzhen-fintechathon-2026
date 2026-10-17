"""Injection flag (plan 3.8, 5): probability that supplier text contains instructions to the system.

It can only escalate (bill to T2, security log). An attacker who evades it gains nothing the other layers allow.
The text is decoded first (base64, Morse, zero-width and look-alike characters) so encoded text cannot slip past.
The default backend is a deterministic scorer; an LLM or Jev backend can sit behind decide.Decider.
"""
from __future__ import annotations

import base64
import binascii
import math
import re
import unicodedata

MORSE = {
    ".-": "a", "-...": "b", "-.-.": "c", "-..": "d", ".": "e", "..-.": "f", "--.": "g", "....": "h", "..": "i",
    ".---": "j", "-.-": "k", ".-..": "l", "--": "m", "-.": "n", "---": "o", ".--.": "p", "--.-": "q", ".-.": "r",
    "...": "s", "-": "t", "..-": "u", "...-": "v", ".--": "w", "-..-": "x", "-.--": "y", "--..": "z",
    "-----": "0", ".----": "1", "..---": "2", "...--": "3", "....-": "4", ".....": "5", "-....": "6",
    "--...": "7", "---..": "8", "----.": "9",
}
ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)

PATTERNS = [
    (r"\bignore (all |any |your |the )?(previous|prior|above|earlier)?\s*(rules|instructions|policies)", 3.0),
    (r"\b(system|admin|developer) (note|message|prompt|override)\b", 2.5),
    (r"\b(ai|assistant|agent|bot)s?\b.{0,40}\b(must|should|please|are to|will)\b", 2.0),
    (r"\b(transfer|send|wire|move|pay)\b.{0,40}\b(full|entire|all|whole|remaining)\b.{0,20}\b(balance|funds|amount|invoices)\b", 3.0),
    (r"\b(new|updated|changed|different) (bank|account|wallet|payment) (details|account|instructions|address)\b", 2.0),
    (r"\bpay\b.{0,30}\b(to|into)\b.{0,15}\b(our )?(new|this|the following) (account|wallet|address)\b", 2.5),
    (r"\bpre-?approved\b|\bmark (it |this )?as paid\b|\bskip (the )?(check|review|approval)s?\b", 2.5),
    (r"\b(send|transfer|wire|pay)\s+\$?\d[\d,.]*\s*(\w+\s+){0,3}(to|into)\b", 2.0),
    (r"\b(automated|ai)\s+(agents?|assistants?|systems?)\b", 1.5),
    (r"\b(wallet|account) (below|above|here)\b", 1.0),
    (r"\b0x[0-9a-fA-F]{40}\b", 1.5),
    (r"\bimmediately\b|\burgent(ly)?\b", 0.7),
    (r"\bdo not (tell|inform|notify)\b", 2.0),
]


def _decode_base64(text: str) -> list[str]:
    out = []
    for tok in re.findall(r"[A-Za-z0-9+/]{16,}={0,2}", text):
        try:
            s = base64.b64decode(tok + "=" * (-len(tok) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if sum(c.isprintable() for c in s) / max(1, len(s)) > 0.9:
            out.append(s)
    return out


def _decode_morse(text: str) -> list[str]:
    out = []
    for run in re.findall(r"(?:[.\-]{1,6}[ /]+){4,}[.\-]{1,6}", text):
        words = [w.strip() for w in re.split(r"\s*/\s*|\s{3,}", run)]
        dec = " ".join("".join(MORSE.get(ch, "") for ch in w.split()) for w in words)
        if len(dec.replace(" ", "")) >= 4:
            out.append(dec)
    return out


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text.translate(ZERO_WIDTH))
    return t


def decoded_views(text: str) -> list[str]:
    t = normalise(text)
    return [t] + _decode_base64(t) + _decode_morse(t)


def score(text: str) -> dict:
    """Return {p, hits, decoded}. p is a logistic squash of pattern weights over all decoded views."""
    if not text or not text.strip():
        return {"p": 0.0, "hits": [], "decoded": []}
    views = decoded_views(text)
    hits, w = [], 0.0
    for v in views:
        for pat, weight in PATTERNS:
            if re.search(pat, v, flags=re.IGNORECASE):
                hits.append(pat)
                w += weight
    if len(views) > 1:
        w += 1.0  # encoded content on a bill is itself suspicious
    p = 1 / (1 + math.exp(-(w - 2.5)))
    return {"p": round(p, 4), "hits": hits, "decoded": views[1:]}
