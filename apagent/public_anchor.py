"""Hourly public anchors (spec E6): every company's journal head, sealed on a public chain.

Each company's journal is a hash chain in the database (store.py): its head commits to every line before it. Once
an hour this module takes each company's head, makes one leaf per company, keccak(company id, line count, head),
builds a Merkle root over the leaves and writes it to the EvidenceAnchor contract on PUBLIC_ANCHOR_NETWORK
(Base Sepolia). One transaction covers every company. Anyone can then check a company's journal: recompute the
head from the rows, rebuild the leaf, follow the Merkle proof to the root, and read the root on the explorer.

    PUBLIC_ANCHOR_NETWORK=baseSepolia   where to anchor (empty: off)
    PUBLIC_ANCHOR_SECONDS=3600          how often; an hour with no new journal lines sends nothing
"""
from __future__ import annotations

import time
from typing import Optional

from web3 import Web3

from .audit import merkle_proof, merkle_root, verify_proof

TABLE = """
create table if not exists public_anchors (
  period     bigint primary key,
  network    text not null,
  root       text not null,
  tx_hash    text,
  leaves     jsonb not null,
  created_at timestamptz not null default now()
)
"""


def leaf(company_id: str, rows: int, head: str) -> bytes:
    return Web3.keccak(text=f"{company_id}|{rows}|{head}")


def heads(st) -> list[dict]:
    """[{company, rows, head}] for every company with journal lines, in a fixed order."""
    with st.connect() as c:
        got = c.execute("select company_id, count(*), (array_agg(chain_hash order by seq desc))[1] from journal "
                        "group by company_id order by company_id").fetchall()
    return [{"company": r[0], "rows": int(r[1]), "head": r[2]} for r in got]


def latest(st) -> Optional[dict]:
    with st.connect() as c:
        c.execute(TABLE)
        r = c.execute("select period, network, root, tx_hash, leaves, created_at from public_anchors "
                      "order by period desc limit 1").fetchone()
    return dict(zip(("period", "network", "root", "tx_hash", "leaves", "created_at"), r)) if r else None


def anchor_once(st, chain, period: Optional[int] = None) -> Optional[dict]:
    """Anchor the current heads if anything changed since the last anchor. Returns the anchor record or None."""
    hs = heads(st)
    if not hs:
        return None
    leaves = [leaf(h["company"], h["rows"], h["head"]) for h in hs]
    root = "0x" + merkle_root(leaves).hex()
    last = latest(st)
    if last and last["root"] == root:
        return None
    period = period if period is not None else int(time.time() // 3600)
    if last and period <= last["period"]:
        period = last["period"] + 1  # the contract takes one root per period
    tx = chain.anchor_root(period, bytes.fromhex(root[2:]))
    if not tx.ok:
        raise RuntimeError(f"anchor transaction failed: {tx.error}")
    rec = {"period": period, "network": chain.network, "root": root, "tx_hash": tx.tx_hash, "leaves": hs}
    with st.connect() as c:
        c.execute(TABLE)
        c.execute("insert into public_anchors (period, network, root, tx_hash, leaves) values (%s,%s,%s,%s,%s)",
                  (period, chain.network, root, tx.tx_hash, st.Jsonb(hs)))
    return rec


def proof_for(st, company_id: str) -> Optional[dict]:
    """The latest anchor that includes this company, its leaf, the Merkle proof, and whether the journal rows
    still produce the anchored head."""
    a = latest(st)
    if not a:
        return None
    hs = a["leaves"]
    idx = next((i for i, h in enumerate(hs) if h["company"] == company_id), None)
    if idx is None:
        return {"anchor": {k: a[k] for k in ("period", "network", "root", "tx_hash")}, "included": False}
    leaves = [leaf(h["company"], h["rows"], h["head"]) for h in hs]
    prf = merkle_proof(leaves, idx)
    mine = hs[idx]
    with st.connect() as c:  # recompute the head the anchor committed to, from the rows as they are now
        rows = c.execute("select chain_hash from journal where company_id=%s and seq=%s",
                         (company_id, mine["rows"] - 1)).fetchone()
    return {"anchor": {k: a[k] for k in ("period", "network", "root", "tx_hash")}, "included": True,
            "company": company_id, "rows": mine["rows"], "head": mine["head"],
            "leaf": "0x" + leaves[idx].hex(), "proof": ["0x" + p.hex() for p in prf],
            "proof_ok": verify_proof(leaves[idx], prf, bytes.fromhex(a["root"][2:])),
            "rows_match": bool(rows and rows[0] == mine["head"]) and st.verify_journal(company_id)["ok"]}


def loop(every: float, network: str) -> None:
    """Background thread: anchor, then wait. Errors are printed and retried next period."""
    from .chain import Chain
    from .session import store

    while True:
        try:
            st = store()
            if st is not None:
                rec = anchor_once(st, Chain(network, held_roles={"agent"}, anchor_only=True))
                if rec:
                    print(f"public anchor {rec['period']} on {network}: {rec['root']} tx {rec['tx_hash']}", flush=True)
        except Exception as e:  # noqa: BLE001 - keep anchoring next period
            print(f"public anchor failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
        time.sleep(every)
