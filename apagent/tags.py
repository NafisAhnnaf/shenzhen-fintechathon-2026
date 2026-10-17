"""Capability tags on every value (plan section 5, CaMeL-style).

A value carries the set of sources it came from. A derived value carries all of its inputs' sources.
Untrusted sources can only push a bill toward more scrutiny (policy S3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class Src(str, Enum):
    OWNER = "owner"
    SETTINGS = "settings"
    REGISTRY = "registry"
    ERP = "erp"
    COMPUTED = "computed"
    INTENT = "intent"
    SUPPLIER_DOC = "supplier_doc"
    SUPPLIER_MSG = "supplier_msg"
    MARKET = "market"
    ERP_BOUNDED = "computed:erp_bounded"


UNTRUSTED = frozenset({Src.SUPPLIER_DOC, Src.SUPPLIER_MSG, Src.MARKET})


@dataclass(frozen=True)
class T:
    """A tagged value."""

    value: Any
    sources: frozenset = field(default_factory=frozenset)
    note: str = ""

    @staticmethod
    def of(value: Any, *sources: Src, note: str = "") -> "T":
        return T(value, frozenset(sources), note)

    @property
    def untrusted(self) -> bool:
        return bool(self.sources & UNTRUSTED)

    def has(self, src: Src) -> bool:
        return src in self.sources

    def derive(self, value: Any, *others: "T", extra: Iterable[Src] = ()) -> "T":
        srcs = set(self.sources) | {Src.COMPUTED} | set(extra)
        for o in others:
            srcs |= o.sources
        return T(value, frozenset(srcs))

    def label(self) -> str:
        """How a card must label this number (policy S5)."""
        if Src.SUPPLIER_DOC in self.sources or Src.SUPPLIER_MSG in self.sources:
            return "supplier says"
        if Src.MARKET in self.sources:
            return self.note or "market"
        return ""

    def to_json(self) -> dict:
        return {"value": self.value, "sources": sorted(s.value for s in self.sources), "label": self.label()}


def bounded(x: T, erp_bound: T) -> T:
    """The only endorsement: min(x, erp_bound). A supplier can make it smaller, never larger.

    erp_bound must come from ERP and settings only.
    """
    if erp_bound.untrusted:
        raise ValueError("erp_bound must not carry untrusted sources")
    v = min(float(x.value), float(erp_bound.value))
    return T(round(v, 2), frozenset({Src.ERP_BOUNDED}))


def trusted(value: Any, src: Src) -> T:
    if src in UNTRUSTED:
        raise ValueError("use T.of for untrusted values")
    return T.of(value, src)
