import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAccount, useConnect, useDisconnect, type Connector } from "wagmi";
import { useAppState } from "../lib/hooks";
import { Art, C, ICON } from "../components/Characters";

type Who = "owner" | "approver" | "viewer";
const ROLES: [Who, string, string][] = [
  ["owner", "Owner", "Sets the limits and the risk dial, unpauses, unfreezes payees."],
  ["approver", "Finance manager", "Signs held bills, confirms cases, sends supplier queries."],
  ["viewer", "Look around", "Read everything and try requests. Can't run or sign."],
];

/** Wallet login: the address decides the role. Local test keys exist only on a local chain. */
export default function Login() {
  const [who, setWho] = useState<Who>("approver");
  const { data: st } = useAppState();
  const { connectors, connectAsync, isPending, variables, error, reset } = useConnect();
  const { disconnectAsync } = useDisconnect();
  const { isConnected } = useAccount();
  const nav = useNavigate();
  const [err, setErr] = useState("");
  useEffect(() => reset(), [who]); // eslint-disable-line react-hooks/exhaustive-deps

  const local = connectors.filter((c) => c.type === "mock" || c.type === "localKey");
  const localFor = who === "owner" ? local[0] : who === "approver" ? local[1] : undefined;
  const browser = connectors.find((c) => c.type === "injected");
  const phone = connectors.find((c) => c.type === "walletConnect");

  const go = async (c: Connector) => {
    setErr("");
    try {
      if (isConnected) await disconnectAsync();
      await connectAsync({ connector: c });
      nav("/desk");
    } catch (e: any) {
      setErr(e?.shortMessage || e?.message || String(e));
    }
  };
  const waiting = isPending ? (variables?.connector as Connector | undefined)?.name ?? "your wallet" : null;

  return (
    <div className="login" style={{ minHeight: "100vh" }}>
      <section className="art">
        <Link className="logo" to="/" style={{ color: "#F6F5FF" }}>
          <Art html={C.mark()} />
          <span>Bonded Payables</span>
        </Link>
        <div style={{ display: "flex", gap: 20, alignItems: "flex-end", flexWrap: "wrap" }}>
          <Art html={C.clerk(waiting ? "think" : "wave", 190)} />
          <div style={{ flex: "1 1 220px" }}>
            <h2>{waiting ? "Checking your wallet…" : "Every number shows its ID. So do you."}</h2>
            <p style={{ marginTop: 12 }}>People sign in with their own wallet. The address decides what you can do; nobody types a password.</p>
          </div>
        </div>
        <p style={{ fontSize: 14 }}>{st ? `${st.network === "localhost" ? "Local chain" : st.network} · chain ${st.chain_id} · sample data` : "Connecting to the agent"}</p>
      </section>
      <section className="panel">
        <div>
          <h1 style={{ fontSize: 34 }}>Open the desk</h1>
          <p className="muted" style={{ marginTop: 8 }}>
            Choose who you are, then connect.
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
        {who === "viewer" ? (
          <button className="btn btn-primary btn-lg" onClick={() => (isConnected ? disconnectAsync().then(() => nav("/desk")) : nav("/desk"))}>
            Look around without a wallet
          </button>
        ) : (
          <div className="wallets">
            <button className="btn btn-quiet" disabled={!browser || isPending} onClick={() => browser && go(browser)}>
              <Art html={ICON.wallet} />
              Browser wallet
            </button>
            <button className="btn btn-quiet" disabled={!phone || isPending} onClick={() => phone && go(phone)} title={phone ? "" : "Set VITE_WC_PROJECT_ID to enable"}>
              <Art html={ICON.phone} />
              Phone wallet
            </button>
            <button className="btn btn-quiet" disabled={!localFor || isPending} onClick={() => localFor && go(localFor)} title={localFor ? "" : "Only on a local chain"}>
              <Art html={ICON.key} />
              Local test key
            </button>
          </div>
        )}
        {waiting && (
          <p style={{ display: "flex", gap: 10, alignItems: "center", fontWeight: 700 }}>
            <span className="spin dark" />
            Waiting for {waiting}…
          </p>
        )}
        {(err || error) && (
          <p className="err" role="alert">
            {err || error?.message}
          </p>
        )}
        {st && (
          <p className="muted" style={{ fontSize: 14 }}>
            Owner {short(st.roles.owner)}, finance manager {short(st.roles.approver)}. A wallet that is neither is a viewer.
          </p>
        )}
      </section>
    </div>
  );
}

const short = (a?: string) => (a ? `${a.slice(0, 6)}…${a.slice(-4)}` : "–");
