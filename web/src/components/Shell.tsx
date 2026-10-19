import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAccount, useDisconnect, useSwitchChain } from "wagmi";
import { useAppState, useRole } from "../lib/hooks";
import { ROLE, shortAddr, time } from "../lib/format";
import { Art, C, ICON } from "./Characters";

const PAGES = [
  ["/desk", "Desk", ICON.desk],
  ["/activity", "Activity", ICON.activity],
  ["/risk", "Risk", ICON.risk],
  ["/security", "Security", ICON.shield],
  ["/settings", "Settings", ICON.settings],
] as const;

export function Shell({ children }: { children: ReactNode }) {
  const { data: st } = useAppState();
  const company = (st?.company.replace(/\s*\(fictional\)\s*/, "") ?? "").split(" ").slice(0, 2).join(" ");
  return (
    <div className="flex min-h-screen flex-col">
      <header className="app-h">
        <div className="wrap">
          <Link className="logo" to="/">
            <Art html={C.mark(30)} />
            <span style={{ fontSize: 18 }}>{company}</span>
          </Link>
          <nav className="app-nav" aria-label="Main">
            {PAGES.map(([to, label, icon]) => (
              <NavLink key={to} to={to}>
                <Art html={icon} />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="who">
            <ChainStatus />
            <RoleChip />
          </div>
        </div>
      </header>
      <main className="app wrap flex-1">
        <Banners />
        {children}
      </main>
    </div>
  );
}

function ChainStatus() {
  const { data: st } = useAppState();
  if (!st) return null;
  const net = st.network === "localhost" ? "Local chain · testnet" : st.network === "fisco" ? "FISCO BCOS" : "Base Sepolia";
  const paused = st.chain.agent_paused;
  return (
    <span className={`net ${paused ? "paused" : ""}`}>
      <i />
      {paused ? "Agent paused" : net}
    </span>
  );
}

/** Who you are: the role your wallet holds in the vault. Viewers have no wallet or an unknown one. */
function RoleChip() {
  const { address, isConnected } = useAccount();
  const { role } = useRole();
  const { disconnect } = useDisconnect();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const face = role === "owner" ? C.person("owner", 30) : role === "approver" ? C.person("manager", 30) : C.clerk("idle", 30);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="rolechip" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="menu">
        <Art html={face} />
        <span style={{ fontSize: 14.5 }}>
          <b>{role ? ROLE[role] : "Viewer"}</b> {address && <span className="mono">{shortAddr(address)}</span>}
        </span>
      </button>
      {open && (
        <div className="menu" role="menu">
          {isConnected ? (
            <>
              <p className="muted" style={{ fontSize: 13, padding: "6px 12px" }} title={address}>
                Signed in as {role ? ROLE[role] : "a viewer"}. Your wallet's address decides what you can do.
              </p>
              <button role="menuitem" onClick={() => nav("/login")}>
                Switch wallet
              </button>
              <button
                role="menuitem"
                onClick={() => {
                  disconnect();
                  setOpen(false);
                  nav("/");
                }}
              >
                Disconnect wallet
              </button>
            </>
          ) : (
            <button role="menuitem" onClick={() => nav("/login")}>
              Connect a wallet
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** System-wide states: server unreachable, ledger and chain disagree, wrong network, agent paused. */
function Banners() {
  const { data: st, error, dataUpdatedAt } = useAppState();
  const { isConnected, chainId } = useAccount();
  const { switchChain, error: switchErr } = useSwitchChain();
  const out: ReactNode[] = [];
  if (error)
    out.push(
      <div key="off" className="banner night" role="status">
        <span className="spin" />
        <b>Can't reach the desk's server.</b>
        <span style={{ color: "#D6D2FF" }}>
          Showing what we had at {time(dataUpdatedAt / 1000)}. Retrying every 3 seconds; anything that changes money may fail.
        </span>
      </div>,
    );
  if (st && !st.consistency.ok)
    out.push(
      <div key="mm" className="banner stop" role="alert">
        <b style={{ color: "var(--stop)" }}>
          The ledger and the chain disagree on {st.consistency.mismatches.length} payment{st.consistency.mismatches.length === 1 ? "" : "s"}.
        </b>
        <span>Nothing new is paid until someone checks.</span>
        <Link to="/activity">See details</Link>
      </div>,
    );
  if (st && isConnected && chainId !== st.chain_id)
    out.push(
      <div key="net" className="banner attn" role="status">
        <b style={{ color: "#3C2EB8" }}>Your wallet is on another network.</b>
        <span>Switch to chain {st.chain_id} to sign.</span>
        <button className="btn-primary" onClick={() => switchChain({ chainId: st.chain_id })}>
          Switch network
        </button>
        {switchErr && <span className="err">{switchErr.message}</span>}
      </div>,
    );
  if (st?.chain.agent_paused)
    out.push(
      <div key="p" className="banner stop" role="status">
        <b style={{ color: "var(--stop)" }}>The agent is paused.</b>
        <span>Every bill goes to a person. Only the owner can resume.</span>
        <Link to="/security">Security</Link>
      </div>,
    );
  return <>{out}</>;
}
