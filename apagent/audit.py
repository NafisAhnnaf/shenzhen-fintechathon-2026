"""Decision log: one line per step, {ts, actor, kind, planId, inputHash, policy, decision, txHash}.

Each day's lines are hashed into a Merkle root that goes on-chain through EvidenceAnchor.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from web3 import Web3


@dataclass
class LogLine:
    ts: float
    actor: str  # agent, governor, contract, finance_manager, owner, underwriter, system
    kind: str
    detail: dict
    plan_id: Optional[str] = None
    bill_id: Optional[str] = None
    input_hash: Optional[str] = None
    policy: Optional[str] = None
    decision: Optional[str] = None
    tx_hash: Optional[str] = None
    security: bool = False

    def leaf(self) -> bytes:
        return Web3.keccak(text=json.dumps(asdict(self), sort_keys=True, default=str))


def merkle_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        return b"\0" * 32
    layer = list(leaves)
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [Web3.keccak(min(a, b) + max(a, b)) for a, b in zip(layer[::2], layer[1::2])]
    return layer[0]


def merkle_proof(leaves: list[bytes], index: int) -> list[bytes]:
    """Sibling hashes from leaf `index` up to the root, built exactly like merkle_root (sorted pairs, last node
    repeated on odd layers). With sorted pairs a proof needs no left/right flags."""
    if not 0 <= index < len(leaves):
        raise IndexError(index)
    proof, layer, i = [], list(leaves), index
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        proof.append(layer[i ^ 1])
        layer = [Web3.keccak(min(a, b) + max(a, b)) for a, b in zip(layer[::2], layer[1::2])]
        i //= 2
    return proof


def verify_proof(leaf: bytes, proof: list[bytes], root: bytes) -> bool:
    h = leaf
    for s in proof:
        h = Web3.keccak(min(h, s) + max(h, s))
    return h == root


@dataclass
class AuditLog:
    path: Optional[Path] = None
    lines: list[LogLine] = field(default_factory=list)

    def add(self, actor: str, kind: str, detail: Optional[dict] = None, **kw) -> LogLine:
        line = LogLine(time.time(), actor, kind, detail or {}, **kw)
        self.lines.append(line)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(asdict(line), default=str) + "\n")
        return line

    def security(self) -> list[LogLine]:
        return [l for l in self.lines if l.security]

    def root(self, since: float = 0.0) -> bytes:
        return merkle_root([l.leaf() for l in self.lines if l.ts >= since])

    def to_json(self, limit: int = 200) -> list[dict]:
        return [asdict(l) for l in self.lines[-limit:]]


def input_hash(obj) -> bytes:
    """Hash of the bill's inputs: what the governor signed over."""
    return Web3.keccak(text=json.dumps(obj, sort_keys=True, default=str))
