"""Policies S1-S10 (plan section 5), checked before every tool call that has an effect.

A tool call names its arguments as tagged values. The gate refuses the call if any policy fails and
logs the attempt as a security event. The contract repeats S1/S2-style rules as a second layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .tags import Src, T

EFFECT_TOOLS = {"pay_autonomous", "pay_approved", "send_query", "propose_settings", "file_claim", "open_receivable",
                "record_offset", "freeze", "pause", "hold", "probation"}
PROTECTIVE = {"freeze", "pause", "hold", "probation", "record_offset"}  # S10: may run on untrusted triggers
PAY_TOOLS = {"pay_autonomous", "pay_approved"}


class PolicyViolation(Exception):
    def __init__(self, policy: str, msg: str):
        super().__init__(f"{policy}: {msg}")
        self.policy = policy
        self.msg = msg


@dataclass
class ToolCall:
    tool: str
    args: dict  # name -> T
    plan_confirmed: bool = False  # S9: the user confirmed the preview (for request-driven steps)
    from_request: bool = False
    trigger_supplier: Optional[str] = None  # S10: supplier whose data triggered a protective action


def check(call: ToolCall) -> None:
    a = call.args
    if call.tool in PAY_TOOLS:
        payee: T = a["payee"]
        amount: T = a["amount"]
        # S1: a payee comes only from the registry.
        if payee.sources != frozenset({Src.REGISTRY}):
            raise PolicyViolation("S1", f"payee must come from the registry, got {sorted(s.value for s in payee.sources)}")
        # S2: the amount must carry computed:erp_bounded. A raw supplier amount never reaches pay*.
        if amount.sources != frozenset({Src.ERP_BOUNDED}):
            raise PolicyViolation("S2", "payment amount must be computed:erp_bounded")
    if call.tool == "send_query":
        # A query goes only to the registered contact, built from typed values.
        if a["recipient"].sources != frozenset({Src.REGISTRY}):
            raise PolicyViolation("S1", "query recipient must be the registered contact")
        for k, v in a.items():
            if k != "recipient" and isinstance(v, T) and Src.SUPPLIER_MSG in v.sources and not isinstance(v.value, (int, float)):
                raise PolicyViolation("S6", f"free supplier text cannot be placed in an outgoing message ({k})")
    if call.tool == "propose_settings":
        bundle: T = a["bundle"]
        if bundle.untrusted:
            raise PolicyViolation("S3", "untrusted values cannot change settings")
    # S9: request-driven steps with an external effect need a confirmed preview.
    if call.from_request and call.tool in EFFECT_TOOLS - PROTECTIVE and not call.plan_confirmed:
        raise PolicyViolation("S9", "the user has not confirmed the plan preview")
    # S8/S3: untrusted values can only push toward more scrutiny.
    if call.tool not in PROTECTIVE:
        for k, v in a.items():
            if isinstance(v, T) and v.untrusted and k in ("payee", "amount", "bundle", "recipient", "settings"):
                raise PolicyViolation("S3", f"untrusted value cannot set {k}")
    # S10: protective actions on untrusted triggers only against the supplier the data came from.
    if call.tool in PROTECTIVE and call.trigger_supplier is not None:
        target = a.get("supplier")
        if target is not None and target.value != call.trigger_supplier:
            raise PolicyViolation("S10", "a protective action may target only the supplier whose data triggered it")


def card_numbers_ok(numbers: dict) -> None:
    """S5: every number on a card equals a tagged value."""
    for k, v in numbers.items():
        if not isinstance(v, T):
            raise PolicyViolation("S5", f"untagged number on card: {k}")
