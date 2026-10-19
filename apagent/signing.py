"""Supplier-signed e-invoices (spec C9).

A supplier that registers a signing key signs each e-invoice: the signature is an Ethereum personal_sign over the
Keccak hash of the invoice JSON (keys sorted, no spaces, without the "signature" field). From then on an unsigned
or altered invoice from that supplier goes to a person, whatever the email around it looks like.

    python -m apagent.signing sign invoice.json <private key>     # what the supplier's system does
    python -m apagent.signing verify invoice.json <address>
"""
from __future__ import annotations

import json
import sys
from typing import Optional

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3


def doc_hash(d: dict) -> str:
    body = {k: v for k, v in d.items() if k != "signature"}
    return "0x" + Web3.keccak(text=json.dumps(body, sort_keys=True, separators=(",", ":"))).hex().removeprefix("0x")


def sign(d: dict, key: str) -> dict:
    h = doc_hash(d)
    sig = Account.sign_message(encode_defunct(hexstr=h), key).signature.hex()
    return {**d, "signature": "0x" + sig.removeprefix("0x")}


def signer(h: str, signature: str) -> Optional[str]:
    try:
        return Account.recover_message(encode_defunct(hexstr=h), signature=signature)
    except Exception:  # noqa: BLE001 - malformed signature
        return None


if __name__ == "__main__":
    cmd, path, arg = sys.argv[1], sys.argv[2], sys.argv[3]
    d = json.loads(open(path).read())
    if cmd == "sign":
        open(path, "w").write(json.dumps(sign(d, arg), indent=1))
        print("signed", doc_hash(d))
    else:
        s = signer(doc_hash(d), d.get("signature", ""))
        print("valid" if s and s.lower() == arg.lower() else f"not valid (signer {s})")
