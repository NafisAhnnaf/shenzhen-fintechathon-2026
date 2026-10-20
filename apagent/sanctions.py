"""Sanctions screening (spec X10): every supplier is checked against the US Treasury's OFAC Specially Designated
Nationals list, names and aliases, before the agent pays it.

    data/sanctions/sdn.csv, alt.csv   the published lists (python -m apagent.sanctions --update downloads them again)
    SANCTIONS_THRESHOLD               match score that holds a bill (default 0.92)

Names are compared after removing punctuation and company-form words (Ltd, Co, Limited, ...). The score is the
higher of the token overlap and the character similarity, so word order and small spelling changes still match.
A match never pays: the bill is held for a person, who checks the listing (a common name can match by chance).
"""
from __future__ import annotations

import csv
import re
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Optional

from .config import DATA_DIR

LIST_DIR = DATA_DIR / "sanctions"
SOURCES = {"sdn.csv": "https://www.treasury.gov/ofac/downloads/sdn.csv",
           "alt.csv": "https://www.treasury.gov/ofac/downloads/alt.csv"}
FORMS = {"ltd", "limited", "co", "company", "corp", "corporation", "inc", "incorporated", "llc", "plc", "sa", "ag",
         "gmbh", "bv", "the", "and", "of", "group", "holdings", "holding", "trading", "international", "intl", "hk",
         "hong", "kong", "china", "products", "industrial", "industries", "co.,", "limited.", "jsc", "pjsc", "ooo"}


def tokens(name: str) -> tuple[str, ...]:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return tuple(w for w in words if w not in FORMS and len(w) > 1)


@lru_cache(maxsize=1)
def _index() -> tuple[list[tuple[str, tuple, str]], dict[str, list[int]]]:
    """[(listed name, tokens, program)], and token -> rows, for a quick shortlist."""
    rows: list[tuple[str, tuple, str]] = []
    programs: dict[str, str] = {}
    sdn, alt = LIST_DIR / "sdn.csv", LIST_DIR / "alt.csv"
    if sdn.exists():
        with sdn.open(encoding="latin-1", newline="") as f:
            for r in csv.reader(f):
                if len(r) > 3 and r[1].strip():
                    programs[r[0]] = r[3].strip()
                    rows.append((r[1].strip(), tokens(r[1]), r[3].strip()))
    if alt.exists():
        with alt.open(encoding="latin-1", newline="") as f:
            for r in csv.reader(f):
                if len(r) > 3 and r[3].strip():
                    rows.append((r[3].strip(), tokens(r[3]), programs.get(r[0], "")))
    by_token: dict[str, list[int]] = {}
    for i, (_, t, _) in enumerate(rows):
        for w in set(t):
            by_token.setdefault(w, []).append(i)
    return rows, by_token


def loaded() -> int:
    return len(_index()[0])


def score(a: tuple, b: tuple) -> float:
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    overlap = len(sa & sb) / len(sa | sb)
    chars = SequenceMatcher(None, " ".join(sorted(sa)), " ".join(sorted(sb))).ratio()
    return round(max(overlap, chars), 3)


@lru_cache(maxsize=4096)
def screen(name: str, threshold: Optional[float] = None) -> Optional[dict]:
    """The best listing at or above the threshold for `name`, or None."""
    import os

    limit = threshold if threshold is not None else float(os.environ.get("SANCTIONS_THRESHOLD", "0.92"))
    t = tokens(name)
    if not t:
        return None
    rows, by_token = _index()
    shortlist = {i for w in t for i in by_token.get(w, [])}
    best = None
    for i in shortlist:
        listed, lt, program = rows[i]
        s = score(t, lt)
        if s >= limit and (best is None or s > best["score"]):
            best = {"listed": listed, "program": program, "score": s, "list": "OFAC SDN"}
    return best


def update() -> dict:
    import httpx

    LIST_DIR.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, url in SOURCES.items():
        r = httpx.get(url, timeout=120, follow_redirects=True)
        r.raise_for_status()
        (LIST_DIR / name).write_bytes(r.content)
        out[name] = len(r.content)
    _index.cache_clear()
    screen.cache_clear()
    return out


if __name__ == "__main__":
    import sys

    if "--update" in sys.argv:
        print(update())
    print(f"{loaded()} names and aliases loaded")
