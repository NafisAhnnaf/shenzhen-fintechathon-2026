import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAccount, useConnect, useDisconnect, useSwitchChain } from "wagmi";
import { useAppState, useBills, useRole } from "../lib/hooks";
import { ROLE, shortAddr } from "../lib/format";
import { connectorLabel } from "../lib/wallet";

const PAGES = [
  { to: "/", label: "Desk", icon: DeskIcon },
  { to: "/activity", label: "Activity", icon: ActivityIcon },
  { to: "/risk", label: "Risk & Reserves", icon: RiskIcon },
  { to: "/security", label: "Threat Defense", icon: SecurityIcon },
] as const;

export function Shell({ children }: { children: ReactNode }) {
  const { data: st } = useAppState();
  const { data: bills } = useBills();
  const company = st?.company.replace(/\s*\(fictional\)\s*/, "") || "Harbour Precision";
  const needsCount = (bills ?? []).filter(
    (b) => b.status === "held" || (b.status === "approved" && b.tier === "T2")
  ).length;

  return (
    <div className="flex min-h-screen flex-col bg-paper text-ink pb-20 md:pb-0">
      {/* Mobile Dynamic Island Top Bar */}
      <div className="md:hidden sticky top-0 z-30 flex flex-col items-center bg-surface/90 backdrop-blur-md border-b border-rule px-4 py-2">
        <div className="flex items-center gap-2 rounded-full bg-ink px-3 py-1 text-[11px] font-medium text-white shadow-sm">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full rounded-full bg-ledger-mint animate-ping opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-ledger-mint" />
          </span>
          <span>Agent v4.2 Active</span>
          <span className="text-muted/80">•</span>
          <span className="text-slate-300">Arbitrum Nova</span>
          <span className="text-muted/80">•</span>
          <span className="font-mono text-ledger-mint">11 Gwei</span>
        </div>
        <div className="mt-1.5 flex w-full items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-ledger text-white font-bold text-xs">
              ⚡
            </div>
            <span className="text-xs font-semibold">{company}</span>
          </div>
          <Wallet compact />
        </div>
      </div>

      {/* Desktop Header */}
      <header className="hidden md:block rule-b bg-surface sticky top-0 z-30 shadow-xs">
        <div className="mx-auto flex max-w-[1440px] items-center gap-x-8 px-6 py-3.5">
          {/* Logo & Company */}
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ledger text-white shadow-sm">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <div className="font-bold text-sm tracking-tight text-ink flex items-center gap-1.5">
                <span>Bonded AP Agent</span>
                <span className="rounded bg-ledger-soft px-1.5 py-0.2 text-[10px] font-semibold text-ledger border border-ledger/20">
                  Topic F
                </span>
              </div>
              <div className="text-xs text-muted truncate max-w-[200px]">{company}</div>
            </div>
          </div>

          {/* Desktop Nav Tabs */}
          <nav className="flex gap-1.5 text-sm" aria-label="Pages">
            {PAGES.map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium transition-all ${
                    isActive
                      ? "bg-ledger-soft text-ledger border border-ledger/20 shadow-xs"
                      : "text-muted hover:bg-paper hover:text-ink"
                  }`
                }
              >
                <span>{label}</span>
                {to === "/" && needsCount > 0 && (
                  <span className="rounded-full bg-ochre px-1.5 py-0.2 text-[10px] font-bold text-white leading-tight">
                    {needsCount}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>

          {/* Right Status & Wallet */}
          <div className="ml-auto flex items-center gap-4 text-sm">
            {st && <ChainStatus />}
            <Wallet />
          </div>
        </div>
      </header>

      {/* Main Content Stage */}
      <main className="flex-1">{children}</main>

      {/* Mobile Docked Bottom Navigation Bar */}
      <nav
        className="md:hidden fixed bottom-0 left-0 right-0 z-40 border-t border-rule bg-surface/95 backdrop-blur-md px-3 py-2 shadow-lg"
        aria-label="Mobile Bottom Navigation"
      >
        <div className="flex items-center justify-around">
          {PAGES.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex flex-col items-center gap-1 px-3 py-1 text-[11px] font-medium transition-colors relative ${
                  isActive ? "text-ledger" : "text-muted hover:text-ink"
                }`
              }
            >
              <div className="relative">
                <Icon className="h-5 w-5" />
                {to === "/" && needsCount > 0 && (
                  <span className="absolute -top-1 -right-2 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-ochre px-1 text-[9px] font-bold text-white">
                    {needsCount}
                  </span>
                )}
              </div>
              <span>{label.split(" ")[0]}</span>
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

function ChainStatus() {
  const { data: st } = useAppState();
  if (!st) return null;
  const net = st.network === "localhost" ? "Arbitrum Nova (Simulated)" : st.network === "fisco" ? "FISCO BCOS" : "Base Sepolia";
  const paused = st.chain.agent_paused;
  return (
    <div className="hidden lg:flex items-center gap-2">
      <span
        className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border ${
          paused
            ? "border-oxblood/30 bg-oxblood-soft text-oxblood"
            : "border-ledger/20 bg-ledger-soft text-ledger"
        }`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${paused ? "bg-oxblood" : "bg-ledger"}`} />
        {paused ? "Agent Paused" : net}
      </span>
    </div>
  );
}

function Wallet({ compact }: { compact?: boolean }) {
  const { address, isConnected, chainId } = useAccount();
  const { role } = useRole();
  const { data: st } = useAppState();
  const { connectors, connect, error } = useConnect();
  const { disconnect } = useDisconnect();
  const { switchChain } = useSwitchChain();
  const [open, setOpen] = useState(false);

  if (isConnected && address) {
    const wrong = st && chainId !== st.chain_id;
    const roleLabel = role ? ROLE[role] : "Viewer";
    const isCFO = role === "approver";

    if (compact) {
      return (
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1.5 rounded-full border border-ledger/20 bg-ledger-soft px-2.5 py-1 text-xs font-semibold text-ledger"
        >
          <span>{isCFO ? "Marcus Vance (CFO)" : roleLabel}</span>
          <span className="h-1.5 w-1.5 rounded-full bg-ledger" />
        </button>
      );
    }

    return (
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 rounded-lg border border-rule bg-paper px-3 py-1.5 text-xs" title={address}>
          <div className="flex h-5 w-5 items-center justify-center rounded-full bg-ledger text-white font-bold text-[10px]">
            {isCFO ? "MV" : "OW"}
          </div>
          <div>
            <div className="font-semibold text-ink leading-tight flex items-center gap-1">
              <span>{isCFO ? "Marcus Vance (CFO)" : roleLabel}</span>
              {isCFO && (
                <span className="rounded bg-ledger-soft text-ledger px-1 text-[9px] font-mono">
                  EIP-712
                </span>
              )}
            </div>
            <div className="font-mono text-[11px] text-muted">{shortAddr(address)}</div>
          </div>
        </div>

        {wrong ? (
          <button className="btn-quiet text-xs py-1.5" onClick={() => switchChain({ chainId: st!.chain_id })}>
            Switch network
          </button>
        ) : (
          <button
            className="text-xs text-muted hover:text-ink font-medium"
            onClick={() => disconnect()}
          >
            Disconnect
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="relative">
      <button
        className="btn-primary text-xs py-1.5 px-3 shadow-xs"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        Connect Wallet
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-72 rounded-xl border border-rule bg-surface p-2 shadow-xl">
          <div className="px-3 py-2 border-b border-rule">
            <div className="font-semibold text-xs text-ink">Choose Signer Account</div>
            <div className="text-[11px] text-muted">Dual-key multi-sig authorization</div>
          </div>
          <div className="py-1">
            {connectors.map((c) => (
              <button
                key={c.uid}
                className="block w-full rounded-lg px-3 py-2 text-left text-xs font-medium hover:bg-paper transition-colors"
                onClick={() => {
                  connect({ connector: c });
                  setOpen(false);
                }}
              >
                {connectorLabel(c, connectors.filter((x) => x.type === "mock").indexOf(c))}
              </button>
            ))}
          </div>
          <p className="px-3 pb-1 pt-2 text-[11px] text-muted border-t border-rule">
            Finance manager and owner co-sign with EIP-712 typed data payloads.
          </p>
          {error && <p className="px-3 pb-1 text-xs text-oxblood">{error.message}</p>}
        </div>
      )}
    </div>
  );
}

// SVG Icons
function DeskIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
    </svg>
  );
}

function ActivityIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function RiskIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M13 10V3L4 14h7v7l9-11h-7z" />
    </svg>
  );
}

function SecurityIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    </svg>
  );
}
