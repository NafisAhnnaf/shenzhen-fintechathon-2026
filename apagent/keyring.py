"""Gemini API keys: one (GEMINI_API_KEY) or several (GEMINI_API_KEYS=key1,key2). When a key's daily allowance is
used up (429 RESOURCE_EXHAUSTED), it is set aside until Google says it resets and the next key is used, so a busy
demo or a test run does not stop at the first limit. Calls are also spaced to the per-minute limit (GEMINI_RPM,
15 by default, the free tier of Gemini 3.1 Flash-Lite), so a burst of bills waits briefly instead of being refused.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque
from typing import Optional

from .config import load_env

_resting: dict[str, float] = {}  # key -> time it can be used again
_sent: dict[str, deque] = {}  # key -> times of the calls in the last minute
_sent_lock = threading.Lock()


def _slot(key: str, max_wait: float) -> None:
    """Wait (at most max_wait seconds) until the key has made fewer than GEMINI_RPM calls in the last minute. Past
    that the call goes out anyway, and the caller's back-off handles a refusal."""
    rpm = max(1, int(os.environ.get("GEMINI_RPM", "15")))
    give_up = time.time() + max_wait
    while True:
        with _sent_lock:
            q = _sent.setdefault(key, deque())
            now = time.time()
            while q and q[0] <= now - 60:
                q.popleft()
            if len(q) < rpm or now >= give_up:
                q.append(now)
                return
            pause = min(q[0] + 60 - now, give_up - now)
        time.sleep(max(0.05, pause))


def keys() -> list[str]:
    load_env()
    many = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]
    one = os.environ.get("GEMINI_API_KEY") or os.environ.get("gemini_api_key", "")
    return many or ([one] if one else [])


def current() -> Optional[str]:
    now = time.time()
    ks = keys()
    for k in ks:
        if _resting.get(k, 0) <= now:
            return k
    return min(ks, key=lambda k: _resting.get(k, 0)) if ks else None  # all resting: the one that resets first


def exhausted(r) -> bool:
    """A used-up daily allowance (not a per-minute limit)."""
    return r.status_code == 429 and ("RESOURCE_EXHAUSTED" in r.text or "per day" in r.text.lower()) \
        and not re.search(r"retry in \d+(\.\d+)?s\b", r.text)


def rest(key: str, r=None) -> None:
    """Set a key aside until its allowance resets (from Google's "retry in 2h28m" message; one hour if absent)."""
    wait = 3600.0
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", getattr(r, "text", "") or "")
    if m and any(m.groups()):
        h, mi, s = (float(x) if x else 0.0 for x in m.groups())
        wait = h * 3600 + mi * 60 + s
    _resting[key] = time.time() + wait


def post(url: str, body: dict, timeout: float = 60, key: Optional[str] = None):
    """POST with the first usable key; on a used-up daily allowance, move to the next key."""
    import httpx

    tried: set = set()
    r = None
    while True:
        k = key or current()
        if k is None or k in tried:
            return r
        tried.add(k)
        _slot(k, max_wait=min(20.0, timeout / 2))
        r = httpx.post(url, json=body, headers={"Authorization": f"Bearer {k}"}, timeout=timeout)
        if key is not None or not exhausted(r):
            return r
        rest(k, r)
