import { createConnector } from "wagmi";
import { createWalletClient, http, numberToHex, type Chain } from "viem";
import { privateKeyToAccount } from "viem/accounts";

/**
 * A wallet that signs in the browser with a public test key. Only for local test chains (the FISCO BCOS
 * consortium chain on this machine): FISCO nodes hold no user keys, so they cannot sign like a Hardhat node.
 * Signatures and transactions are real; the key is the well-known Hardhat test key, never used with real funds.
 */
export function localKey(privateKey: `0x${string}`, label: string, chain: Chain) {
  const account = privateKeyToAccount(privateKey);
  const rpc = chain.rpcUrls.default.http[0];
  const wallet = createWalletClient({ account, chain, transport: http(rpc) });

  const request = async ({ method, params }: { method: string; params?: any }): Promise<any> => {
    switch (method) {
      case "eth_requestAccounts":
      case "eth_accounts":
        return [account.address];
      case "eth_chainId":
        return numberToHex(chain.id);
      case "eth_signTypedData_v4": {
        const td = typeof params[1] === "string" ? JSON.parse(params[1]) : params[1];
        const { EIP712Domain: _drop, ...types } = td.types;
        return account.signTypedData({ domain: td.domain, types, primaryType: td.primaryType, message: td.message });
      }
      case "eth_sendTransaction": {
        const tx = params[0];
        return wallet.sendTransaction({
          to: tx.to,
          data: tx.data,
          gas: tx.gas ? BigInt(tx.gas) : undefined,
          gasPrice: 0n, // FISCO BCOS charges no gas
          type: "legacy",
        } as any);
      }
      default: {
        const r = await fetch(rpc, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params: params ?? [] }) });
        const j = await r.json();
        if (j.error) throw new Error(j.error.message);
        return j.result;
      }
    }
  };

  return createConnector((config) => ({
    id: `localKey-${account.address}`,
    name: label,
    type: "localKey",
    async connect() {
      config.emitter.emit("connect", { accounts: [account.address], chainId: chain.id });
      return { accounts: [account.address], chainId: chain.id } as any;
    },
    async disconnect() {},
    async getAccounts() {
      return [account.address];
    },
    async getChainId() {
      return chain.id;
    },
    async getProvider() {
      return { request } as any;
    },
    async isAuthorized() {
      return false;
    },
    onAccountsChanged() {},
    onChainChanged() {},
    onDisconnect() {},
  }));
}
