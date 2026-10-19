"""On-chain executor and signers (web3.py). Talks to PaymentVault, BondPool, EvidenceAnchor, NaiveWallet.

Keys: on Base Sepolia from chain/.env. On a local Hardhat node, the node's well-known dev keys.
In the demo the governor service, the finance manager and the owner sign server-side; in production
each would sign on their own device.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractCustomError, ContractLogicError

from .config import CHAIN_DIR, units_to_usd, usd_to_units

# Hardhat node dev accounts come from its public test mnemonic (never use with real funds).
HARDHAT_MNEMONIC = "test test test test test test test test test test test junk"
ROLES = ["owner", "agent", "governor", "approver", "underwriter"]


def hardhat_keys(n: int = 6) -> list[str]:
    Account.enable_unaudited_hdwallet_features()
    return ["0x" + Account.from_mnemonic(HARDHAT_MNEMONIC, account_path=f"m/44'/60'/0'/0/{i}").key.hex().removeprefix("0x")
            for i in range(n)]


def b32(s: str) -> bytes:
    raw = s.encode()
    if len(raw) > 31:
        raw = Web3.keccak(text=s)[:31]
    return raw.ljust(32, b"\0")


def load_keys(network: str) -> dict[str, str]:
    """Role keys. 'attacker' is an unrelated key used only by the red-team tasks."""
    if network in ("localhost", "hardhat", "fisco"):
        # Local chains (Hardhat, and the local FISCO BCOS consortium chain) use the public test mnemonic.
        return dict(zip(ROLES + ["attacker"], hardhat_keys(6)))
    env = {}
    p = CHAIN_DIR / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.endswith("_KEY")})
    keys = {r: env[f"{r.upper()}_KEY"] for r in ROLES if env.get(f"{r.upper()}_KEY")}
    if env.get("ATTACKER_KEY"):
        keys["attacker"] = env["ATTACKER_KEY"]
    return keys


def _abi(name: str) -> list:
    p = CHAIN_DIR / "artifacts" / "contracts" / f"{name}.sol" / f"{name}.json"
    return json.loads(p.read_text())["abi"]


@dataclass
class TxResult:
    ok: bool
    tx_hash: Optional[str]
    error: Optional[str] = None
    block: Optional[int] = None


class Chain:
    def __init__(self, network: str = "localhost", rpc: Optional[str] = None, held_roles: Optional[set] = None):
        """held_roles: the keys this process may use. In SIGNING=client mode the owner and the finance manager
        (approver) sign in their own wallets, so the server does not load their keys."""
        dep_file = CHAIN_DIR / "deployments" / f"{network}.json"
        self.dep = json.loads(dep_file.read_text())
        rpc = rpc or {"localhost": "http://127.0.0.1:8545",
                      "fisco": os.environ.get("FISCO_RPC", "http://127.0.0.1:8546")}.get(
            network, os.environ.get("BASE_SEPOLIA_RPC", "https://sepolia.base.org"))
        self.w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 60}))
        self.network = network
        self.keys = load_keys(network)
        if held_roles is not None:
            self.keys = {r: k for r, k in self.keys.items() if r in held_roles}
        self.acct = {r: Account.from_key(k) for r, k in self.keys.items()}
        c = self.dep["contracts"]
        self.vault = self.w3.eth.contract(address=Web3.to_checksum_address(c["vault"]), abi=_abi("PaymentVault"))
        self.pool = self.w3.eth.contract(address=Web3.to_checksum_address(c["pool"]), abi=_abi("BondPool"))
        self.token = self.w3.eth.contract(address=Web3.to_checksum_address(c["token"]), abi=_abi("MockUSDC"))
        self.anchor = self.w3.eth.contract(address=Web3.to_checksum_address(c["anchor"]), abi=_abi("EvidenceAnchor"))
        self.naive = self.w3.eth.contract(address=Web3.to_checksum_address(c["naive"]), abi=_abi("NaiveWallet"))
        self.chain_id = self.w3.eth.chain_id
        self._errors = self._error_selectors()

    # ------------------------------------------------------------------ plumbing
    def _error_selectors(self) -> dict[str, str]:
        out = {}
        for abi in (self.vault.abi, self.pool.abi):
            for e in abi:
                if e.get("type") == "error":
                    sig = f"{e['name']}({','.join(i['type'] for i in e['inputs'])})"
                    out["0x" + Web3.keccak(text=sig)[:4].hex().removeprefix("0x")] = e["name"]
        return out

    def _decode(self, err: Exception) -> str:
        msg = str(err)
        data = getattr(err, "data", None) or (err.args[1] if len(getattr(err, "args", ())) > 1 else None)
        for cand in (data, msg):
            if isinstance(cand, str):
                for sel, name in self._errors.items():
                    if sel in cand:
                        return name
        return msg[:200]

    def send(self, role: str, fn, allow_revert_tx: bool = False) -> TxResult:
        """Sign and send a transaction as `role`. Reverts are caught at simulation time unless
        allow_revert_tx is set, in which case a failing transaction is mined to produce a public revert hash."""
        acct = self.acct[role]
        try:
            gas = fn.estimate_gas({"from": acct.address})
        except (ContractCustomError, ContractLogicError, ValueError) as e:
            reason = self._decode(e)
            if not allow_revert_tx:
                return TxResult(False, None, reason)
            gas = 400_000
            tx = fn.build_transaction({"from": acct.address, "nonce": self.w3.eth.get_transaction_count(acct.address),
                                       "gas": gas, "chainId": self.chain_id, **self._fees()})
            raw = acct.sign_transaction(tx)
            try:
                h = self.w3.eth.send_raw_transaction(raw.raw_transaction)
            except Exception as e:  # a local node mines the failing tx but reports the revert as an RPC error
                data = getattr(e, "args", [{}])[0]
                txh = (data.get("data") or {}).get("txHash") if isinstance(data, dict) else None
                return TxResult(False, txh or "0x" + raw.hash.hex().removeprefix("0x"), reason)
            rc = self.w3.eth.wait_for_transaction_receipt(h, timeout=180)
            return TxResult(False, "0x" + h.hex().removeprefix("0x"), reason, rc.blockNumber)
        tx = fn.build_transaction({"from": acct.address, "nonce": self.w3.eth.get_transaction_count(acct.address),
                                   "gas": int(gas * 1.3) + 20_000, "chainId": self.chain_id, **self._fees()})
        h = self.w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
        rc = self.w3.eth.wait_for_transaction_receipt(h, timeout=180)
        hx = "0x" + h.hex().removeprefix("0x")
        return TxResult(rc.status == 1, hx, None if rc.status == 1 else "reverted", rc.blockNumber)

    def _fees(self) -> dict:
        if self.network == "localhost":
            return {}
        if self.network == "fisco":
            return {"gasPrice": 0}  # FISCO BCOS charges no gas by default
        base = self.w3.eth.get_block("latest").get("baseFeePerGas", 10**8)
        tip = self.w3.to_wei(0.001, "gwei")
        return {"maxFeePerGas": base * 2 + tip, "maxPriorityFeePerGas": tip}

    def now(self) -> int:
        if self.network == "fisco":
            # The latest FISCO block can be minutes old (blocks only on transactions); the next one gets wall-clock time.
            import time as _t
            return int(_t.time())
        return self.w3.eth.get_block("latest").timestamp

    def advance(self, seconds: int) -> None:
        """Move time forward: instantly on a Hardhat node; on FISCO BCOS time is real, so this waits."""
        if self.network == "fisco":
            import time as _t
            _t.sleep(seconds)
            self.tick()
            return
        if self.network != "localhost":
            raise RuntimeError("time can only move on a local chain")
        self.w3.provider.make_request("evm_increaseTime", [seconds])
        self.w3.provider.make_request("evm_mine", [])

    def tick(self) -> None:
        """FISCO BCOS makes a block only when there is a transaction, so after a wait the latest block still carries
        the old time and simulations see the past. A harmless transaction (a zero approval) seals a fresh block."""
        self.send("agent", self.token.functions.approve(self.vault.address, 0))

    @property
    def day_seconds(self) -> int:
        return int(self.dep.get("params", {}).get("dayLength", 86400))

    @property
    def cool_down(self) -> int:
        return int(self.dep.get("params", {}).get("coolDown", 300))

    def explorer(self, tx_hash: Optional[str]) -> Optional[str]:
        if not tx_hash:
            return None
        if self.network == "baseSepolia":
            return f"https://sepolia.basescan.org/tx/{tx_hash}"
        return None

    # ------------------------------------------------------------------ EIP-712
    def _domain(self, contract) -> dict:
        name = "PaymentVault" if contract is self.vault else "BondPool"
        return {"name": name, "version": "1", "chainId": self.chain_id, "verifyingContract": contract.address}

    # One builder per signed message: (contract, primaryType, fields, message).
    def _gov_msg(self, bill, supplier, usd, settings_id, expiry, input_hash):
        return (self.vault, "GovApproval",
                [("billId", "bytes32"), ("supplierId", "bytes32"), ("amount", "uint256"),
                 ("settingsId", "uint256"), ("expiry", "uint256"), ("inputHash", "bytes32")],
                {"billId": b32(bill), "supplierId": b32(supplier), "amount": usd_to_units(usd),
                 "settingsId": settings_id, "expiry": expiry, "inputHash": input_hash})

    def _pay_msg(self, bill, supplier, usd, expiry):
        payee = self.vault.functions.payees(b32(supplier)).call()[0]
        return (self.vault, "PaymentApproval",
                [("billId", "bytes32"), ("payee", "address"), ("amount", "uint256"), ("expiry", "uint256")],
                {"billId": b32(bill), "payee": payee, "amount": usd_to_units(usd), "expiry": expiry})

    def _recv_msg(self, bill, usd, expiry):
        return (self.vault, "ReceivableApproval", [("billId", "bytes32"), ("amount", "uint256"), ("expiry", "uint256")],
                {"billId": b32(bill), "amount": usd_to_units(usd), "expiry": expiry})

    def _claim_msg(self, bill, usd, cause, evidence, expiry):
        return (self.pool, "Claim",
                [("billId", "bytes32"), ("loss", "uint256"), ("cause", "uint8"), ("evidence", "bytes32"), ("expiry", "uint256")],
                {"billId": b32(bill), "loss": usd_to_units(usd), "cause": cause, "evidence": evidence, "expiry": expiry})

    def _sign(self, role: str, built) -> bytes:
        contract, primary, fields, message = built
        types = {primary: [{"name": n, "type": t} for n, t in fields]}
        return Account.sign_typed_data(self.keys[role], self._domain(contract), types, message).signature

    def typed_data(self, built) -> dict:
        """Full EIP-712 payload for a browser wallet (eth_signTypedData_v4)."""
        contract, primary, fields, message = built
        def enc(v):
            return "0x" + v.hex() if isinstance(v, (bytes, bytearray)) else (str(v) if isinstance(v, int) else v)
        return {
            "domain": self._domain(contract),
            "types": {"EIP712Domain": [{"name": "name", "type": "string"}, {"name": "version", "type": "string"},
                                       {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
                      primary: [{"name": n, "type": t} for n, t in fields]},
            "primaryType": primary,
            "message": {k: enc(v) for k, v in message.items()},
        }

    def recover(self, built, signature: bytes) -> str:
        contract, primary, fields, message = built
        types = {primary: [{"name": n, "type": t} for n, t in fields]}
        from eth_account.messages import encode_typed_data
        msg = encode_typed_data(self._domain(contract), types, message)
        try:
            return Account.recover_message(msg, signature=signature)
        except Exception:  # malformed signature: treat as signed by nobody, so callers refuse it cleanly
            return ""

    def role_address(self, role: str) -> str:
        """On-chain address for a role (from the deployment), whether or not this process holds its key."""
        return Web3.to_checksum_address(self.dep["roles"][role])

    def gov_signature(self, bill: str, supplier: str, usd: float, settings_id: int, expiry: int, input_hash: bytes,
                      role: str = "governor") -> bytes:
        return self._sign(role, self._gov_msg(bill, supplier, usd, settings_id, expiry, input_hash))

    def approval_signature(self, bill: str, supplier: str, usd: float, expiry: int, role: str = "approver") -> bytes:
        return self._sign(role, self._pay_msg(bill, supplier, usd, expiry))

    def receivable_signature(self, bill: str, usd: float, expiry: int, role: str = "approver") -> bytes:
        return self._sign(role, self._recv_msg(bill, usd, expiry))

    def claim_signature(self, bill: str, usd: float, cause: int, evidence: bytes, expiry: int, role: str = "approver") -> bytes:
        return self._sign(role, self._claim_msg(bill, usd, cause, evidence, expiry))

    # ------------------------------------------------------------------ transactions a person sends from their wallet
    def prepare(self, role: str, fn) -> dict:
        """An unsigned transaction for the role's own wallet (owner, underwriter). The wallet signs and sends it."""
        frm = self.role_address(role)
        tx = fn.build_transaction({"from": frm, "nonce": self.w3.eth.get_transaction_count(frm), "chainId": self.chain_id,
                                   "gas": 300_000, **self._fees()})
        return {"from": frm, "to": tx["to"], "data": tx["data"], "chainId": self.chain_id, "gas": hex(tx["gas"])}

    def verify_sent(self, tx_hash: str, role: str, contract) -> TxResult:
        """Check a transaction a person sent from their wallet: mined, successful, from the right role, to our contract."""
        rc = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        tx = self.w3.eth.get_transaction(tx_hash)
        if Web3.to_checksum_address(tx["from"]) != self.role_address(role):
            return TxResult(False, tx_hash, f"sent from {tx['from']}, expected the {role} key")
        if Web3.to_checksum_address(tx["to"]) != contract.address:
            return TxResult(False, tx_hash, "not a transaction to this contract")
        return TxResult(rc.status == 1, tx_hash, None if rc.status == 1 else "reverted", rc.blockNumber)

    def has_key(self, role: str) -> bool:
        return role in self.keys

    # ------------------------------------------------------------------ vault calls
    def pay_autonomous(self, bill: str, supplier: str, usd: float, settings_id: int, expiry: int, input_hash: bytes,
                       gov_sig: bytes, caller: str = "agent", mine_revert: bool = False) -> TxResult:
        fn = self.vault.functions.payAutonomous(b32(bill), b32(supplier), usd_to_units(usd), settings_id, expiry, input_hash, gov_sig)
        return self.send(caller, fn, mine_revert)

    def pay_approved(self, bill: str, supplier: str, usd: float, expiry: int, sig: bytes, mine_revert: bool = False) -> TxResult:
        fn = self.vault.functions.payApproved(b32(bill), b32(supplier), usd_to_units(usd), expiry, sig)
        return self.send("agent", fn, mine_revert)

    def freeze(self, supplier: str, role: str = "agent") -> TxResult:
        return self.send(role, self.vault.functions.freezePayee(b32(supplier)))

    def unfreeze(self, supplier: str) -> TxResult:
        return self.send("owner", self.vault.functions.unfreezePayee(b32(supplier)))

    def pause_agent(self, role: str = "agent") -> TxResult:
        return self.send(role, self.vault.functions.pauseAgent())

    def unpause_agent(self) -> TxResult:
        return self.send("owner", self.vault.functions.unpauseAgent())

    def add_payee(self, supplier: str, wallet: str, rail: int) -> TxResult:
        return self.send("owner", self.vault.functions.addPayee(b32(supplier), Web3.to_checksum_address(wallet), rail))

    def propose_settings(self, mode: int, p_day_usd: float, p_nday: int, p_supweek_usd: float, r_usd: float) -> TxResult:
        fn = self.vault.functions.proposeSettings(mode, usd_to_units(p_day_usd), p_nday, usd_to_units(p_supweek_usd), usd_to_units(r_usd))
        return self.send("owner", fn)

    def approve_settings(self, settings_id: int) -> TxResult:
        return self.send("underwriter", self.vault.functions.approveSettings(settings_id))

    def activate_settings(self, settings_id: int) -> TxResult:
        return self.send("owner", self.vault.functions.activateSettings(settings_id))

    def open_receivable(self, bill: str, usd: float, sig: Optional[bytes] = None, expiry: Optional[int] = None) -> TxResult:
        """sig/expiry: the finance manager's signature from their wallet. Without them the server signs (SIGNING=server)."""
        if sig is None:
            expiry = self.now() + 3600
            sig = self.receivable_signature(bill, usd, expiry)
        return self.send("agent", self.vault.functions.openReceivable(b32(bill), usd_to_units(usd), expiry, sig))

    def record_offset(self, bill: str, against: str, usd: float) -> TxResult:
        return self.send("agent", self.vault.functions.recordOffset(b32(bill), b32(against), usd_to_units(usd)))

    # ------------------------------------------------------------------ pool calls
    def file_claim(self, bill: str, usd: float, cause: int, evidence: bytes, sig: Optional[bytes] = None,
                   expiry: Optional[int] = None) -> TxResult:
        if sig is None:
            expiry = self.now() + 3600
            sig = self.claim_signature(bill, usd, cause, evidence, expiry)
        return self.send("agent", self.pool.functions.fileClaim(b32(bill), usd_to_units(usd), cause, evidence, expiry, sig))

    def execute_claim(self, bill: str) -> TxResult:
        if self.network == "fisco":
            self.tick()
        return self.send("agent", self.pool.functions.executeClaim(b32(bill)))

    def release(self, bill: str) -> TxResult:
        if self.network == "fisco":
            self.tick()
        return self.send("agent", self.pool.functions.release(b32(bill)))

    def pool_withdraw(self, usd: float, role: str = "underwriter") -> TxResult:
        return self.send(role, self.pool.functions.withdraw(usd_to_units(usd)))

    def pool_fund(self, usd: float, role: str = "underwriter") -> TxResult:
        return self.send(role, self.pool.functions.fund(usd_to_units(usd)))

    def pool_unpause(self, role: str = "underwriter") -> TxResult:
        return self.send(role, self.pool.functions.unpause())

    def anchor_root(self, day: int, root: bytes) -> TxResult:
        return self.send("agent", self.anchor.functions.anchor(day, root))

    def naive_send(self, to: str, usd: float, memo: str) -> TxResult:
        return self.send("agent", self.naive.functions.send(Web3.to_checksum_address(to), usd_to_units(usd), memo))

    # ------------------------------------------------------------------ views
    def state(self) -> dict:
        v, p, t = self.vault.functions, self.pool.functions, self.token.functions
        sid = v.activeSettings().call()
        b = v.bundle(sid).call()
        return {
            "network": self.network,
            "vault": self.vault.address,
            "vault_balance_usd": units_to_usd(t.balanceOf(self.vault.address).call()),
            "naive_balance_usd": units_to_usd(t.balanceOf(self.naive.address).call()),
            "pool_balance_usd": units_to_usd(p.balance().call()),
            "pool_locked_usd": units_to_usd(p.lockedTotal().call()),
            "pool_free_usd": units_to_usd(p.freeCapital().call()),
            "pool_paused": p.paused().call(),
            "pool_owed_usd": units_to_usd(p.owedTotal().call()),
            "agent_paused": v.agentPaused().call(),
            "settings_id": sid,
            "mode": ["standard", "self_reserve", "bonded"][b[0]],
            "p_day_usd": units_to_usd(b[1]), "p_nday": b[2], "p_supweek_usd": units_to_usd(b[3]), "r_usd": units_to_usd(b[4]),
            "p_cap_usd": units_to_usd(v.pCap().call()),
        }

    def payee(self, supplier: str) -> dict:
        w, rail, active_at, exists, frozen = self.vault.functions.payees(b32(supplier)).call()
        return {"wallet": w, "rail": rail, "active_at": active_at, "exists": exists, "frozen": frozen,
                "active": exists and not frozen and self.now() >= active_at}

    def bill_used(self, bill: str) -> bool:
        return self.vault.functions.billUsed(b32(bill)).call()
