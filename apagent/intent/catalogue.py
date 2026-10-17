"""Intent catalogue v1 (plan 3.6). One action per request; every slot comes from a closed list."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Intent:
    name: str
    key_slot: str | None  # the slot that gets its own conformal set
    required: bool  # key slot must be filled
    control: str  # T0, P, T1/T2, T3
    example: str
    roles: tuple = ("owner", "finance_manager")
    extra_slots: tuple = field(default_factory=tuple)


CATALOGUE = {
    "ASK_STATUS": Intent("ASK_STATUS", "supplier", False, "T0", "What do we owe Acme this month?", extra_slots=("window",)),
    "ASK_WHY": Intent("ASK_WHY", "bill", True, "T0", "Why was bill 0412 held?"),
    "WHAT_IF": Intent("WHAT_IF", "supplier", False, "T0", "What happens to cash if we pay all copper bills today?", extra_slots=("window",)),
    "PAY_SET": Intent("PAY_SET", "supplier", True, "T1/T2", "Pay Acme's bills due this week except the disputed one", extra_slots=("window", "exclusions")),
    "HOLD_SET": Intent("HOLD_SET", "supplier", True, "P", "Hold all copper bills until the index updates"),
    "RELEASE": Intent("RELEASE", "supplier", True, "T1/T2", "Release the Acme hold"),
    "QUERY_SUPPLIER": Intent("QUERY_SUPPLIER", "bill", True, "T2", "Ask Acme about the price on bill 0412", extra_slots=("topic",)),
    "TIGHTEN": Intent("TIGHTEN", "supplier", True, "P", "Be more careful with Ganjiang Copper"),
    "SET_DIAL": Intent("SET_DIAL", "bundle", True, "T3", "Be more careful this month", roles=("owner",)),
    "PAUSE": Intent("PAUSE", None, False, "P", "Stop all payments"),
    "RESUME": Intent("RESUME", None, False, "T3", "Start again", roles=("owner",)),
    "UNSUPPORTED": Intent("UNSUPPORTED", None, False, "-", "Add this new bank account"),
}

INTENTS = list(CATALOGUE)
WINDOWS = ["today", "this_week", "next_week", "this_month", "overdue", "all"]
EXCLUSIONS = ["disputed", "flagged", "probation", "above_cap"]
TOPICS = ["price", "quantity", "credit"]
BUNDLES = ["careful", "standard", "more", "most"]

WHAT_IT_CAN_DO = [
    "Pay Acme's bills due this week except the disputed one",
    "Why was bill 0412 held?",
    "Be more careful this month",
]
