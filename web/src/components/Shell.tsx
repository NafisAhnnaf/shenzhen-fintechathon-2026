import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAccount, useConnect, useDisconnect, useSwitchChain } from "wagmi";
import { useAppState, useRole } from "../lib/hooks";
import { ROLE, shortAddr } from "../lib/format";
import { connectorLabel } from "../lib/wallet";

const PAGES = [
  ["/", "Desk"],
  ["/activity", "Activity"],
  ["/risk", "Risk"],
  ["/security", "Security"],
] as const;

export function Shell({ children }: { children: ReactNode }) {
  const { data: st } = useAppState();
  const company = st?.company.replace(/\s*\(fictional\)\s*/, "") ?? "";
  return (
    <div className="flex min-h-screen flex-col">
      <header className="rule-b bg-surface">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6">
          <div className="font-semibold">{company}</div>
          <nav className="flex gap-1 text-sm" aria-label="Pages">
            {PAGES.map(([to, label]) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `rounded px-2.5 py-1.5 ${isActive ? "bg-paper font-medium text-ink" : "text-muted hover:text-ink"}`
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-5 text-sm">
            {st && <ChainStatus />}
            <Wallet />
          </div>
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}

function ChainStatus() {
  const { data: st } = useAppState();
  if (!st) return null;
  const net = st.network === "localhost" ? "Local chain" : st.network === "fisco" ? "FISCO BCOS" : "Base Sepolia";
  const paused = st.chain.agent_paused;
  return (
    <span className={`hidden md:inline ${paused ? "font-medium text-oxblood" : "text-muted"}`} title={net}>
      {paused ? "Agent paused" : net}
    </span>
  );
}

function Wallet() {
  const { address, isConnected, chainId } = useAccount();
  const { role } = useRole();
  const { data: st } = useAppState();
  const { connectors, connect, error } = useConnect();
  const { disconnect } = useDisconnect();
  const { switchChain } = useSwitchChain();
  const [open, setOpen] = useState(false);

  if (isConnected && address) {
    const wrong = st && chainId !== st.chain_id;
    return (
      <div className="flex items-center gap-3">
        <span title={address}>
          {role ? ROLE[role] : "Viewer"} <span className="text-muted">{shortAddr(address)}</span>
        </span>
        {wrong ? (
          <button className="btn-quiet" onClick={() => switchChain({ chainId: st!.chain_id })}>
            Switch network
          </button>
        ) : (
          <button className="text-sm text-muted hover:text-ink" onClick={() => disconnect()}>
            Disconnect
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="relative">
      <button className="btn-primary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        Connect wallet
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-2 w-72 rounded border border-rule bg-surface p-1.5 shadow-[0_8px_24px_rgba(29,36,33,0.08)]">
          {connectors.map((c) => (
            <button
              key={c.uid}
              className="block w-full rounded px-3 py-2 text-left text-sm hover:bg-paper"
              onClick={() => {
                connect({ connector: c });
                setOpen(false);
              }}
            >
              {connectorLabel(c, connectors.filter((x) => x.type === "mock").indexOf(c))}
            </button>
          ))}
          <p className="px-3 pb-1 pt-2 text-xs text-muted">The owner and the finance manager sign in their own wallets. Anyone else can read.</p>
          {error && <p className="px-3 pb-1 text-xs text-oxblood">{error.message}</p>}
        </div>
      )}
    </div>
  );
}
