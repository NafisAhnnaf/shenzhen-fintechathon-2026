"""Bank payment files and bank statements (spec M1, M2): the way money really leaves a company's bank account.

Bills to suppliers on the bank rail are approved and recorded on chain like any other; the money itself goes by
bank transfer. The desk writes the approved transfers into an ISO 20022 credit-transfer file (pain.001.001.09),
which the company uploads to its bank's corporate portal or sends over host-to-host. The bank's end-of-day
statement (camt.053.001.08) comes back; the desk matches every debit to a payment it approved:

  matched      the statement line carries our end-to-end reference (the bill id) or the same amount to the same
               creditor; the payment is confirmed as booked by the bank
  outside      a debit to a supplier that matches nothing we approved: money left the account outside the system.
               It is a security event and an alert for the owner
  outstanding  a payment in a file we produced that no statement has shown yet

The file and statement formats follow the published ISO 20022 schemas; the account and bank identifiers are
"Othr" identifiers (a Hong Kong account number), which is what HK corporate portals accept for domestic files.
"""
from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

PAIN_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
MAX_STATEMENT_BYTES = 5_000_000


class BadStatement(ValueError):
    pass


def _sub(parent, tag: str, text: Optional[str] = None, **attrs) -> ET.Element:
    e = ET.SubElement(parent, tag, attrs)
    if text is not None:
        e.text = text
    return e


def _amt(x: float) -> str:
    return f"{x:.2f}"


def pain001(company: str, debtor_account: str, payments: list[dict], msg_id: str, execute_on: str,
            currency: str = "USD") -> str:
    """A pain.001.001.09 credit-transfer file. Each payment: {bill, amount, creditor, account, reference}."""
    root = ET.Element("Document", {"xmlns": PAIN_NS})
    init = _sub(root, "CstmrCdtTrfInitn")
    total = round(sum(p["amount"] for p in payments), 2)
    hdr = _sub(init, "GrpHdr")
    _sub(hdr, "MsgId", msg_id)
    _sub(hdr, "CreDtTm", time.strftime("%Y-%m-%dT%H:%M:%S"))
    _sub(hdr, "NbOfTxs", str(len(payments)))
    _sub(hdr, "CtrlSum", _amt(total))
    _sub(_sub(hdr, "InitgPty"), "Nm", company[:140])
    inf = _sub(init, "PmtInf")
    _sub(inf, "PmtInfId", f"{msg_id}-1")
    _sub(inf, "PmtMtd", "TRF")
    _sub(inf, "NbOfTxs", str(len(payments)))
    _sub(inf, "CtrlSum", _amt(total))
    _sub(_sub(inf, "ReqdExctnDt"), "Dt", execute_on)
    _sub(_sub(inf, "Dbtr"), "Nm", company[:140])
    _sub(_sub(_sub(_sub(inf, "DbtrAcct"), "Id"), "Othr"), "Id", debtor_account)
    _sub(_sub(_sub(_sub(inf, "DbtrAgt"), "FinInstnId"), "Othr"), "Id", "NOTPROVIDED")
    _sub(inf, "ChrgBr", "SLEV")
    for p in payments:
        tx = _sub(inf, "CdtTrfTxInf")
        pid = _sub(tx, "PmtId")
        _sub(pid, "InstrId", p["bill"][:35])
        _sub(pid, "EndToEndId", p["bill"][:35])
        _sub(_sub(tx, "Amt"), "InstdAmt", _amt(p["amount"]), Ccy=currency)
        _sub(_sub(tx, "Cdtr"), "Nm", p["creditor"][:140])
        _sub(_sub(_sub(_sub(tx, "CdtrAcct"), "Id"), "Othr"), "Id", p["account"][:34])
        _sub(_sub(tx, "RmtInf"), "Ustrd", p["reference"][:140])
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


CAMT_NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"


def camt053(account: str, entries: list[dict], stmt_id: str, on: str) -> str:
    """A camt.053.001.08 statement with the given entries ({amount, direction, booked, end_to_end, counterparty,
    account, remittance, bank_ref}). Used by the tests and by the demo bank, which books a payment file the way a
    bank's end-of-day statement would."""
    root = ET.Element("Document", {"xmlns": CAMT_NS})
    st = _sub(_sub(root, "BkToCstmrStmt"), "Stmt")
    _sub(st, "Id", stmt_id)
    _sub(st, "CreDtTm", f"{on}T23:59:00")
    _sub(_sub(_sub(_sub(st, "Acct"), "Id"), "Othr"), "Id", account)
    for e in entries:
        n = _sub(st, "Ntry")
        _sub(n, "Amt", _amt(e["amount"]), Ccy=e.get("currency", "USD"))
        _sub(n, "CdtDbtInd", "DBIT" if e["direction"] == "debit" else "CRDT")
        _sub(_sub(n, "Sts"), "Cd", "BOOK")
        _sub(_sub(n, "BookgDt"), "Dt", e["booked"])
        _sub(n, "AcctSvcrRef", e["bank_ref"])
        tx = _sub(_sub(n, "NtryDtls"), "TxDtls")
        if e.get("end_to_end"):
            _sub(_sub(tx, "Refs"), "EndToEndId", e["end_to_end"])
        parties = _sub(tx, "RltdPties")
        who, acct = ("Cdtr", "CdtrAcct") if e["direction"] == "debit" else ("Dbtr", "DbtrAcct")
        _sub(_sub(parties, who), "Nm", e.get("counterparty", ""))
        _sub(_sub(_sub(_sub(parties, acct), "Id"), "Othr"), "Id", e.get("account", ""))
        if e.get("remittance"):
            _sub(_sub(tx, "RmtInf"), "Ustrd", e["remittance"])
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(e: ET.Element, *path: str) -> Optional[ET.Element]:
    """The first descendant along `path` (local names, any namespace)."""
    cur = [e]
    for name in path:
        nxt = []
        for c in cur:
            nxt += [x for x in c.iter() if x is not c and _local(x.tag) == name]
        if not nxt:
            return None
        cur = nxt[:1]
    return cur[0]


def _text(e: ET.Element, *path: str) -> str:
    x = _find(e, *path)
    return (x.text or "").strip() if x is not None else ""


def parse_camt053(data: bytes) -> list[dict]:
    """Entries of a camt.053 statement: {amount, currency, direction (debit/credit), booked, end_to_end,
    counterparty, account, remittance}. Refuses DTDs and entity declarations (no entity expansion)."""
    if len(data) > MAX_STATEMENT_BYTES:
        raise BadStatement("the statement is larger than 5 MB")
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise BadStatement("statements with a DTD or entity declarations are refused")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise BadStatement(f"not a readable XML statement: {e}")
    if not any(_local(x.tag) == "BkToCstmrStmt" for x in root.iter()):
        raise BadStatement("not a camt.053 bank-to-customer statement")
    out = []
    for n in (x for x in root.iter() if _local(x.tag) == "Ntry"):
        amt = _find(n, "Amt")
        if amt is None:
            continue
        debit = _text(n, "CdtDbtInd") == "DBIT"
        party = ("Cdtr", "CdtrAcct") if debit else ("Dbtr", "DbtrAcct")
        out.append({
            "amount": round(float(amt.text or 0), 2), "currency": amt.get("Ccy", ""),
            "direction": "debit" if debit else "credit",
            "booked": _text(n, "BookgDt", "Dt") or _text(n, "BookgDt", "DtTm")[:10],
            "end_to_end": _text(n, "EndToEndId"),
            "counterparty": _text(n, party[0], "Nm"),
            "account": _text(n, party[1], "Id"),
            "remittance": _text(n, "Ustrd")[:140],
            "bank_ref": _text(n, "AcctSvcrRef"),
        })
    return out


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class BankDesk:
    """The company's bank side, kept on the agent so it is saved with the rest of the working memory."""

    def __init__(self, agent):
        self.ag = agent
        d = agent.__dict__
        self.batches: list[dict] = d.setdefault("bank_batches", [])
        self.confirmed: dict[str, dict] = d.setdefault("bank_confirmed", {})
        self.outside: list[dict] = d.setdefault("bank_outside", [])
        self.seen_refs: list[str] = d.setdefault("bank_seen_refs", [])

    def batched(self) -> set:
        return {p["bill"] for b in self.batches for p in b["payments"]}

    def ready(self) -> list[dict]:
        """Bank-rail bills paid (approved and recorded on chain) and not yet in a payment file."""
        led, done = self.ag.led, self.batched()
        out = []
        for bid, b in led.bills.items():
            sup = led.suppliers.get(b.supplier_id or "")
            if bid.startswith("H") or bid in done or b.status != "paid" or not sup or sup.rail != "bank":
                continue
            out.append({"bill": bid, "amount": round(b.amount_usd, 2), "creditor": sup.name,
                        "account": sup.bank_account or "", "supplier": sup.id,
                        "reference": f"Invoice {b.read.inv_no}"[:140], "tx_hash": b.tx_hash, "paid_on": b.paid_on})
        return out

    def make_file(self, actor: str, debtor_account: str) -> dict:
        pay = self.ready()
        missing = [p["supplier"] for p in pay if not p["account"]]
        if missing:
            raise ValueError(f"no bank account on file for {', '.join(sorted(set(missing)))}")
        if not pay:
            raise ValueError("no approved bank transfers waiting for a payment file")
        n = len(self.batches) + 1
        msg_id = f"{self.ag.led.today.replace('-', '')}-{n:03d}"
        xml = pain001(self.ag.led.company.replace(" (fictional)", ""), debtor_account, pay, msg_id, self.ag.led.today)
        digest = "0x" + hashlib.sha256(xml.encode()).hexdigest()
        batch = {"id": msg_id, "created": self.ag.led.today, "by": actor, "payments": pay, "count": len(pay),
                 "total": round(sum(p["amount"] for p in pay), 2), "sha256": digest}
        self.batches.append(batch)
        self.ag.log.add(actor, "bank_file", {"file": msg_id, "count": len(pay), "total": batch["total"], "sha256": digest})
        return {**batch, "xml": xml}

    def file_xml(self, msg_id: str, debtor_account: str) -> str:
        b = next((b for b in self.batches if b["id"] == msg_id), None)
        if b is None:
            raise KeyError(msg_id)
        return pain001(self.ag.led.company.replace(" (fictional)", ""), debtor_account, b["payments"], b["id"], b["created"])

    def import_statement(self, actor: str, data: bytes) -> dict:
        entries = parse_camt053(data)
        led = self.ag.led
        waiting = {p["bill"]: p for b in self.batches for p in b["payments"] if p["bill"] not in self.confirmed}
        by_party = {_norm(s.name): s.id for s in led.suppliers.values()}
        matched, outside, other, repeat = [], [], [], 0
        for e in entries:
            key = e["bank_ref"] or f"{e['booked']}|{e['amount']}|{e['end_to_end']}|{e['counterparty']}"
            if key in self.seen_refs:
                repeat += 1
                continue
            self.seen_refs.append(key)
            if e["direction"] != "debit":
                other.append(e)
                continue
            hit = waiting.get(e["end_to_end"])
            if hit is None:  # no reference: the same amount to the same creditor
                hit = next((p for p in waiting.values() if abs(p["amount"] - e["amount"]) < 0.005
                            and _norm(p["creditor"]) == _norm(e["counterparty"])), None)
            if hit is not None and abs(hit["amount"] - e["amount"]) < 0.005:
                waiting.pop(hit["bill"], None)
                self.confirmed[hit["bill"]] = {"booked": e["booked"], "bank_ref": e["bank_ref"], "amount": e["amount"]}
                self.ag.log.add("agent", "bank_booked", {"amount": e["amount"], "booked": e["booked"]}, bill_id=hit["bill"])
                matched.append({**e, "bill": hit["bill"]})
                continue
            sup = by_party.get(_norm(e["counterparty"]))
            rec = {**e, "supplier": sup, "found": led.today}
            self.outside.append(rec)
            outside.append(rec)
            self.ag.log.add("agent", "paid_outside_system",
                            {"amount": e["amount"], "booked": e["booked"], "supplier": sup or "unknown",
                             "reason": "a bank debit matches no payment the desk approved"}, security=True)
        outstanding = [p for p in waiting.values()]
        self.ag.log.add(actor, "bank_statement", {"entries": len(entries), "matched": len(matched),
                                                  "outside": len(outside), "outstanding": len(outstanding)})
        return {"entries": len(entries), "matched": matched, "outside": outside, "credits": other,
                "outstanding": outstanding, "repeated": repeat}

    def summary(self) -> dict:
        waiting = [p for b in self.batches for p in b["payments"] if p["bill"] not in self.confirmed]
        return {"ready": self.ready(), "files": [{k: v for k, v in b.items() if k != "payments"} | {
                    "bills": [p["bill"] for p in b["payments"]]} for b in self.batches],
                "confirmed": self.confirmed, "outstanding": waiting, "outside": self.outside}
