import { createConfig, http } from "wagmi";
import { injected, mock, walletConnect } from "wagmi/connectors";
import { baseSepolia } from "viem/chains";
import { defineChain, type Chain } from "viem";
import type { PreparedTx, TypedData } from "./api";
import { localKey } from "./localKey";

// Hardhat's public dev accounts #0 (owner) and #3 (finance manager). The local node holds their keys
// and signs for them, so these give real signatures on a local chain only.
const DEV_ACCOUNTS = {
  owner: "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
  approver: "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
} as const;

// The well-known Hardhat test keys #0 and #3 (public; local chains only).
const DEV_KEYS = {
  owner: "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
  approver: "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
} as const;

export function chainFor(chainId: number, rpc: string): Chain {
  if (chainId === baseSepolia.id) return { ...baseSepolia, rpcUrls: { default: { http: [rpc] } } };
  return defineChain({
    id: chainId,
    name: chainId === 31337 ? "Local chain" : chainId === 20200 ? "FISCO BCOS (local)" : `Chain ${chainId}`,
    nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
    rpcUrls: { default: { http: [rpc] } },
  });
}

export function makeConfig(chainId: number, rpcIn: string) {
  // A relative RPC (the API's relay, used for FISCO) becomes absolute for the wallet libraries.
  const rpc = rpcIn.startsWith("/") ? `${window.location.origin}${rpcIn}` : rpcIn;
  const chain = chainFor(chainId, rpc);
  const wcId = import.meta.env.VITE_WC_PROJECT_ID as string | undefined;
  const connectors = [injected({ shimDisconnect: true })];
  if (wcId) connectors.push(walletConnect({ projectId: wcId, showQrModal: true }) as any);
  if (chainId === 31337) {
    // Hardhat holds these test keys and signs for them.
    connectors.push(
      mock({ accounts: [DEV_ACCOUNTS.owner], features: { reconnect: true } }) as any,
      mock({ accounts: [DEV_ACCOUNTS.approver], features: { reconnect: true } }) as any,
    );
  }
  if (chainId === 20200) {
    // Local FISCO BCOS chain: its nodes hold no user keys, so the browser signs with the same public test keys.
    connectors.push(
      localKey(DEV_KEYS.owner, "Local test key: owner", chain) as any,
      localKey(DEV_KEYS.approver, "Local test key: finance manager", chain) as any,
    );
  }
  return createConfig({ chains: [chain], connectors, transports: { [chain.id]: http(rpc) } as any });
}

export function connectorLabel(c: { type: string; name: string }, index: number): string {
  if (c.type === "localKey") return c.name;
  if (c.type === "mock") return index === 0 ? "Local dev account: owner" : "Local dev account: finance manager";
  if (c.type === "walletConnect") return "Wallet on your phone (WalletConnect)";
  return c.name === "Injected" ? "Browser wallet" : c.name;
}

/** The role a connected address holds in the vault, from the deployment record. */
export function roleOf(address: string | undefined, roles: Record<string, string>): string | null {
  if (!address) return null;
  const a = address.toLowerCase();
  for (const [role, addr] of Object.entries(roles)) if (addr && addr.toLowerCase() === a) return role;
  return null;
}

/** EIP-712 payload from the API, shaped for viem: uint fields as bigint, no EIP712Domain entry. */
export function forViem(td: TypedData) {
  const { EIP712Domain: _omit, ...types } = td.types;
  const fields = types[td.primaryType];
  const message: Record<string, unknown> = {};
  for (const f of fields) {
    const v = td.message[f.name];
    message[f.name] = f.type.startsWith("uint") || f.type.startsWith("int") ? BigInt(v) : v;
  }
  const domain = { ...td.domain, chainId: Number(td.domain.chainId) };
  return { domain, types, primaryType: td.primaryType, message } as any;
}

export function txFor(tx: PreparedTx) {
  return { to: tx.to as `0x${string}`, data: tx.data as `0x${string}`, gas: BigInt(tx.gas) };
}
