import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAccount, useConnect, useDisconnect, useSignMessage, type Connector } from "wagmi";
import { api } from "../lib/api";
import { usePublic } from "../../lib/hooks";
import { DEV_ACCOUNTS } from "../lib/wallet";
import { Art, C, ICON } from "../components/Characters";

type Who = "owner" | "approver" | "underwriter" | "arbiter";
const ROLES: [Who, string, string][] = [
  ["owner", "Owner", "Sets the limits and the risk dial, unpauses, unfreezes payees."],
  ["approver", "Finance manager", "Signs held bills, confirms cases, sends supplier queries."],
  ["underwriter", "Bank", "Funds the reserve, approves risk settings, disputes claims."],
  ["arbiter", "Arbiter", "Settles disputed reserve claims between the company and the bank."],
];

/** Wallet login: connect, then sign a one-time message (Sign-In with Ethereum). The address decides the role. */
export default function Login() {
  const [who, setWho] = useState<Who>("approver");
  const { data: pub } = usePublic();
  const { connectors, connectAsync } = useConnect();
  const { disconnectAsync } = useDisconnect();
  const { isConnected } = useAccount();
  const { signMessageAsync } = useSignMessage();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const want = params.get("next") ?? "";
  const next = want.startsWith("/") && !want.startsWith("//") && !want.startsWith("/login") ? want : "/desk";
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");

  // The local test accounts are wagmi mock connectors in DEV_ACCOUNTS order (owner, finance manager, bank, arbiter).
  const mocks = connectors.filter((c) => c.type === "mock" || c.type === "localKey");
  const localFor = mocks[DEV_ACCOUNTS.findIndex(([r]) => r === who)];
  const browser = connectors.find((c) => c.type === "injected");
  const phone = connectors.find((c) => c.type === "walletConnect");

  const go = async (c: Connector) => {
    setErr("");
    setBusy(c.name);
    try {
      if (isConnected) await disconnectAsync();
      const { accounts } = await connectAsync({ connector: c });
      const ch = await api.post<{ nonce: string; message: string }>("/wallet/challenge", { address: accounts[0] });
      const signature = await signMessageAsync({ account: accounts[0], message: ch.message });
      await api.post("/wallet/login", { nonce: ch.nonce, signature });
      await qc.invalidateQueries();
      nav(next, { replace: true });
    } catch (e: any) {
      setErr(e?.shortMessage || e?.message || String(e));
    } finally {
      setBusy(null);
    }
  };
  const company = (pub?.company ?? "").replace(" (fictional)", "");

  return (
    <div className="login" style={{ minHeight: "100vh" }}>
      <section className="art">
        <Link className="logo" to="/" style={{ color: "#F6F5FF" }}>
          <Art html={C.mark()} />
          <span>Bonded Payables</span>
        </Link>
        <div style={{ display: "flex", gap: 20, alignItems: "flex-end", flexWrap: "wrap" }}>
          <Art html={C.clerk(busy ? "think" : "wave", 190)} />
          <div style={{ flex: "1 1 220px" }}>
            <h2>{busy ? "Checking your wallet…" : "Every number shows its ID. So do you."}</h2>
            <p style={{ marginTop: 12 }}>People sign in with their own wallet. The address decides what you can do; nobody types a password.</p>
          </div>
        </div>
        <p style={{ fontSize: 14 }}>{pub ? `${company} · chain ${pub.chain_id} · sample data` : "Connecting to the agent"}</p>
      </section>
      <section className="panel">
        <div>
          <h1 style={{ fontSize: 34 }}>Open the desk</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            Choose who you are, then connect and sign the sign-in message. Signing costs nothing and moves no money.
          </p>
        </div>
        <div className="roles" role="radiogroup" aria-label="Who are you">
          {ROLES.map(([k, n, d]) => (
            <button key={k} className="role" role="radio" aria-checked={who === k} onClick={() => setWho(k)}>
              <span className="dot" />
              <span>
                <b>{n}</b>
                <br />
                <span className="muted" style={{ fontSize: 14 }}>
                  {d}
                </span>
              </span>
            </button>
          ))}
        </div>
        <div className="wallets">
          <button className="btn btn-quiet" disabled={!browser || !!busy} onClick={() => browser && go(browser)}>
            <Art html={ICON.wallet} />
            Browser wallet
          </button>
          <button className="btn btn-quiet" disabled={!phone || !!busy} onClick={() => phone && go(phone)} title={phone ? "" : "Set VITE_WC_PROJECT_ID to enable"}>
            <Art html={ICON.phone} />
            Phone wallet
          </button>
          <button className="btn btn-quiet" disabled={!localFor || !!busy} onClick={() => localFor && go(localFor)} title={localFor ? "" : "Only on a local chain"}>
            <Art html={ICON.key} />
            Local test key
          </button>
        </div>
        {busy && (
          <p style={{ display: "flex", gap: 10, alignItems: "center", fontWeight: 700 }}>
            <span className="spin dark" />
            Waiting for {busy}…
          </p>
        )}
        {err && (
          <p className="err" role="alert">
            {err}
          </p>
        )}
        <p className="muted" style={{ fontSize: 14 }}>
          A browser wallet that holds none of these roles signs in as a viewer: it can read everything and sign nothing.
        </p>
      </section>
    </div>
  );
}
