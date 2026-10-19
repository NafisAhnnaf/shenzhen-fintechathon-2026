import { createConfig, http } from "wagmi";
import { injected, mock, walletConnect } from "wagmi/connectors";
import { baseSepolia } from "viem/chains";
import { defineChain, type Chain } from "viem";
import type { PreparedTx, TypedData } from "./api";
import { localKey } from "./localKey";

// Hardhat's public dev accounts for the people on the desk: #0 owner, #3 finance manager, #4 bank, #6 arbiter.
// The local node holds their keys and signs for them, so these give real signatures on a local chain only.
export const DEV_ACCOUNTS: [string, string][] = [
  ["owner", "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"],
  ["approver", "0x90F79bf6EB2c4f870365E785982E1f101E93b906"],
  ["underwriter", "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65"],
  ["arbiter", "0x976EA74026E726554dB657fA54763abd0C3a0aa9"],
];

// The same well-known Hardhat test keys (public; local chains only), for FISCO BCOS whose nodes hold no keys.
const DEV_KEYS: Record<string, `0x${string}`> = {
  owner: "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
  approver: "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
  underwriter: "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
  arbiter: "0x92db14e403b83dfe3df233f83dfa3a0d7096f21ca9b0d6d6b8d88b2b4ec1564e",
};
const LABEL: Record<string, string> = { owner: "owner", approver: "finance manager", underwriter: "bank", arbiter: "arbiter" };

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
    for (const [, a] of DEV_ACCOUNTS) connectors.push(mock({ accounts: [a as `0x${string}`], features: { reconnect: true } }) as any);
  }
  if (chainId === 20200) {
    // Local FISCO BCOS chain: its nodes hold no user keys, so the browser signs with the same public test keys.
    for (const [r] of DEV_ACCOUNTS) connectors.push(localKey(DEV_KEYS[r], `Local test key: ${LABEL[r]}`, chain) as any);
  }
  return createConfig({ chains: [chain], connectors, transports: { [chain.id]: http(rpc) } as any });
}

/** A connector as people should read it. mockIndex: its position among the local test accounts. */
export function connectorLabel(c: { type: string; name: string }, mockIndex = -1): string {
  if (c.type === "localKey") return c.name;
  if (c.type === "mock") return `Local test account: ${LABEL[DEV_ACCOUNTS[mockIndex]?.[0]] ?? "account"}`;
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
