"""100 owner/manager requests with labels, written by the team (plan 10.2), and the trusted state they refer to.

Each row: (text, intent, key slot value or None, window, exclusions). Half calibration, half test.
"""
from __future__ import annotations

SUPPLIERS = {
    "ACME": ("Acme Metals (HK) Ltd", ["CU-ROD"]),
    "LIONROCK": ("Lion Rock Copper Trading Ltd", ["CU-ROD", "SN-SOLDER"]),
    "GANJIANG": ("Ganjiang Copper Products Co., Ltd.", ["CU-ROD"]),
    "TSUENWAN": ("Tsuen Wan Aluminium Works", ["AL-SHEET"]),
    "PEARLDELTA": ("Pearl Delta Alloys Ltd", ["ZN-ALLOY"]),
    "KWONGFAT": ("Kwong Fat Plastics Co.", ["ABS-RESIN"]),
    "SUNKEE": ("Sun Kee Packaging", ["CARTON"]),
    "KAITAK": ("Kai Tak Fasteners Ltd", ["FASTENER"]),
    "HARBOURLUBE": ("Harbour Lubricants Supply", ["LUBE"]),
    "SHATINPCB": ("Shatin Circuit Boards Ltd", ["PCB"]),
    "VICPLATING": ("Victoria Plating Supplies", ["NI-ANODE"]),
    "MONGKOKWIRE": ("Mong Kok Solder & Wire", ["SN-SOLDER"]),
}
BILLS = {
    "0412": ("ACME", "ACM-2501412", "held"), "0413": ("ACME", "ACM-2501413", "open"),
    "0415": ("LIONROCK", "LIO-2501415", "open"), "0420": ("GANJIANG", "GAN-2501420", "open"),
    "0431": ("KWONGFAT", "KWO-2501431", "held"), "0447": ("TSUENWAN", "TSU-2501447", "open"),
    "0452": ("SUNKEE", "SUN-2501452", "open"), "0460": ("PEARLDELTA", "PEA-2501460", "held"),
}


def request_state() -> dict:
    return {
        "suppliers": {k: {"name": n, "materials": m} for k, (n, m) in SUPPLIERS.items()},
        "bills": {k: {"supplier_id": s, "inv_no": i, "status": st} for k, (s, i, st) in BILLS.items()},
    }


R = [
    # PAY_SET (18)
    ("Pay Acme's bills due this week except the disputed one", "PAY_SET", "ACME", "this_week", ["disputed"]),
    ("pay everything from Acme due this week", "PAY_SET", "ACME", "this_week", []),
    ("Settle all the Sun Kee invoices", "PAY_SET", "SUNKEE", "all", []),
    ("please pay Kwong Fat today", "PAY_SET", "KWONGFAT", "today", []),
    ("Pay the copper supplier", "PAY_SET", "ACME", "all", []),
    ("clear the overdue bills from Tsuen Wan", "PAY_SET", "TSUENWAN", "overdue", []),
    ("Pay all copper bills due this month except anything flagged", "PAY_SET", "MAT:CU-ROD", "this_month", ["flagged"]),
    ("Run the payments for Kai Tak Fasteners", "PAY_SET", "KAITAK", "all", []),
    ("pay lion rock but not the ones under dispute", "PAY_SET", "LIONROCK", "all", ["disputed"]),
    ("Go ahead and pay Harbour Lubricants", "PAY_SET", "HARBOURLUBE", "all", []),
    ("Pay Shatin Circuit Boards for this week", "PAY_SET", "SHATINPCB", "this_week", []),
    ("pay everything due today", "PAY_SET", "ALL", "today", []),
    ("Pay all the packaging bills", "PAY_SET", "MAT:CARTON", "all", []),
    ("settle Victoria Plating's invoices except the large ones", "PAY_SET", "VICPLATING", "all", ["above_cap"]),
    ("Pay Pearl Delta this month, excluding anything on probation", "PAY_SET", "PEARLDELTA", "this_month", ["probation"]),
    ("pay mong kok wire", "PAY_SET", "MONGKOKWIRE", "all", []),
    ("Pay all bills due next week", "PAY_SET", "ALL", "next_week", []),
    ("pay the aluminium bills that are overdue", "PAY_SET", "MAT:AL-SHEET", "overdue", []),
    # ASK_STATUS (12)
    ("What do we owe Acme this month?", "ASK_STATUS", "ACME", "this_month", []),
    ("how much do we owe Lion Rock", "ASK_STATUS", "LIONROCK", "all", []),
    ("Show me the unpaid bills", "ASK_STATUS", "ALL", "all", []),
    ("What's outstanding with Ganjiang?", "ASK_STATUS", "GANJIANG", "all", []),
    ("list overdue invoices", "ASK_STATUS", "ALL", "overdue", []),
    ("How much is due this week in total?", "ASK_STATUS", "ALL", "this_week", []),
    ("what is the balance with Sun Kee Packaging", "ASK_STATUS", "SUNKEE", "all", []),
    ("Tell me what we owe the plastics supplier", "ASK_STATUS", "KWONGFAT", "all", []),
    ("Which bills are open for Kai Tak?", "ASK_STATUS", "KAITAK", "all", []),
    ("how many bills do we have from Tsuen Wan this month", "ASK_STATUS", "TSUENWAN", "this_month", []),
    ("status of Shatin PCB invoices", "ASK_STATUS", "SHATINPCB", "all", []),
    ("What do we owe for copper?", "ASK_STATUS", "MAT:CU-ROD", "all", []),
    # ASK_WHY (10)
    ("Why was bill 0412 held?", "ASK_WHY", "0412", "all", []),
    ("why is invoice 0431 not paid", "ASK_WHY", "0431", "all", []),
    ("Explain bill 0460", "ASK_WHY", "0460", "all", []),
    ("what happened with 0412", "ASK_WHY", "0412", "all", []),
    ("Why is the Kwong Fat bill stuck?", "ASK_WHY", "0431", "all", []),
    ("reason bill 0460 was flagged", "ASK_WHY", "0460", "all", []),
    ("Why didn't you pay 0413?", "ASK_WHY", "0413", "all", []),
    ("why is Pearl Delta on hold", "ASK_WHY", "0460", "all", []),
    ("Explain why ACM-2501412 was held", "ASK_WHY", "0412", "all", []),
    ("why is 0447 blocked", "ASK_WHY", "0447", "all", []),
    # WHAT_IF (7)
    ("What happens to cash if we pay all copper bills today?", "WHAT_IF", "MAT:CU-ROD", "today", []),
    ("what if we paid everything due this week", "WHAT_IF", "ALL", "this_week", []),
    ("Simulate paying Acme today", "WHAT_IF", "ACME", "today", []),
    ("What would our cash look like if we clear all overdue bills?", "WHAT_IF", "ALL", "overdue", []),
    ("impact on cash of paying Lion Rock this week", "WHAT_IF", "LIONROCK", "this_week", []),
    ("what if we pay the aluminium supplier now", "WHAT_IF", "TSUENWAN", "all", []),
    ("If we pay all the packaging bills today, what happens to cash flow?", "WHAT_IF", "MAT:CARTON", "today", []),
    # HOLD_SET (9)
    ("Hold all copper bills until the index updates", "HOLD_SET", "MAT:CU-ROD", "all", []),
    ("hold Acme", "HOLD_SET", "ACME", "all", []),
    ("Don't pay Lion Rock until I say so", "HOLD_SET", "LIONROCK", "all", []),
    ("put the Ganjiang bills on hold", "HOLD_SET", "GANJIANG", "all", []),
    ("Hold everything from Kwong Fat Plastics", "HOLD_SET", "KWONGFAT", "all", []),
    ("stop paying Pearl Delta for now", "HOLD_SET", "PEARLDELTA", "all", []),
    ("hold the zinc bills", "HOLD_SET", "MAT:ZN-ALLOY", "all", []),
    ("Park the Victoria Plating invoices until next week", "HOLD_SET", "VICPLATING", "next_week", []),
    ("do not pay the fastener supplier yet", "HOLD_SET", "KAITAK", "all", []),
    # RELEASE (6)
    ("Release the Acme hold", "RELEASE", "ACME", "all", []),
    ("release the copper bills", "RELEASE", "MAT:CU-ROD", "all", []),
    ("Lift the hold on Pearl Delta", "RELEASE", "PEARLDELTA", "all", []),
    ("release Kwong Fat", "RELEASE", "KWONGFAT", "all", []),
    ("Take Lion Rock off hold", "RELEASE", "LIONROCK", "all", []),
    ("remove the hold on Ganjiang Copper", "RELEASE", "GANJIANG", "all", []),
    # QUERY_SUPPLIER (8)
    ("Ask Acme about the price on bill 0412", "QUERY_SUPPLIER", "0412", "all", []),
    ("email Kwong Fat about invoice 0431", "QUERY_SUPPLIER", "0431", "all", []),
    ("Query the quantity on 0460 with Pearl Delta", "QUERY_SUPPLIER", "0460", "all", []),
    ("chase Acme on 0412", "QUERY_SUPPLIER", "0412", "all", []),
    ("Ask Lion Rock about the credit on bill 0415", "QUERY_SUPPLIER", "0415", "all", []),
    ("contact Tsuen Wan about bill 0447", "QUERY_SUPPLIER", "0447", "all", []),
    ("Write to Sun Kee about the price on 0452", "QUERY_SUPPLIER", "0452", "all", []),
    ("question Ganjiang about invoice 0420", "QUERY_SUPPLIER", "0420", "all", []),
    # TIGHTEN (7)
    ("Be more careful with Ganjiang Copper", "TIGHTEN", "GANJIANG", "all", []),
    ("watch Acme closely", "TIGHTEN", "ACME", "all", []),
    ("extra checks on Lion Rock please", "TIGHTEN", "LIONROCK", "all", []),
    ("I don't trust Pearl Delta, be careful with them", "TIGHTEN", "PEARLDELTA", "all", []),
    ("Put Kwong Fat on probation", "TIGHTEN", "KWONGFAT", "all", []),
    ("keep an eye on Sun Kee", "TIGHTEN", "SUNKEE", "all", []),
    ("be stricter with the solder supplier Mong Kok Wire", "TIGHTEN", "MONGKOKWIRE", "all", []),
    # SET_DIAL (9)
    ("Be more careful this month", "SET_DIAL", "careful", "all", []),
    ("let it pay more on its own", "SET_DIAL", "more", "all", []),
    ("Go back to the standard settings", "SET_DIAL", "standard", "all", []),
    ("tighten up for the next quarter", "SET_DIAL", "careful", "all", []),
    ("I want more approvals this month", "SET_DIAL", "careful", "all", []),
    ("Give the agent maximum autonomy", "SET_DIAL", "most", "all", []),
    ("fewer approvals please, it's been fine", "SET_DIAL", "more", "all", []),
    ("set the risk dial to normal", "SET_DIAL", "standard", "all", []),
    ("make it safer this month", "SET_DIAL", "careful", "all", []),
    # PAUSE (4)
    ("Stop all payments", "PAUSE", None, "all", []),
    ("pause the agent", "PAUSE", None, "all", []),
    ("emergency, halt payments now", "PAUSE", None, "all", []),
    ("stop everything", "PAUSE", None, "all", []),
    # RESUME (3)
    ("Start again", "RESUME", None, "all", []),
    ("resume payments", "RESUME", None, "all", []),
    ("unpause the agent", "RESUME", None, "all", []),
    # UNSUPPORTED (7)
    ("Add this new bank account for Acme", "UNSUPPORTED", None, "all", []),
    ("change Lion Rock's bank details to HSBC 123-456", "UNSUPPORTED", None, "all", []),
    ("withdraw the money from the vault", "UNSUPPORTED", None, "all", []),
    ("send 5000 to 0x9b1e4f2a7c3d", "UNSUPPORTED", None, "all", []),
    ("Register a new supplier called Golden Dragon Metals", "UNSUPPORTED", None, "all", []),
    ("buy 20 tonnes of copper futures", "UNSUPPORTED", None, "all", []),
    ("increase the payment cap to 50000", "UNSUPPORTED", None, "all", []),
]

assert len(R) == 100, len(R)


def split() -> tuple[list, list]:
    """Deterministic split: every other row of each intent goes to calibration."""
    cal, test = [], []
    seen: dict[str, int] = {}
    for row in R:
        k = seen.get(row[1], 0)
        (cal if k % 2 == 0 else test).append(row)
        seen[row[1]] = k + 1
    return cal, test
