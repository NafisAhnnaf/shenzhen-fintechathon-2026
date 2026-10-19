import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useDisconnect } from "wagmi";
import { api } from "../lib/api";
import { auth } from "../lib/auth";
import { ROLE, date, shortAddr, time } from "../lib/format";
import { useAppState, useBills, useCan, useMe, useNotifications } from "../lib/hooks";
import { AskAgent } from "./AskAgent";

const NETWORK: Record<string, string> = { localhost: "Local test chain", fisco: "FISCO BCOS", baseSepolia: "Base Sepolia" };

export function Shell({ children }: { children: ReactNode }) {
  const { data: st } = useAppState();
  const { data: bills } = useBills();
  const can = useCan();
  const count = (stage: string) => bills?.filter((b) => b.stage === stage).length ?? 0;
  const openCases = st?.open_cases.length ?? 0;
  const link = (to: string, label: string, n?: number, attn = false) => (
    <NavLink to={to} className={({ isActive }) => (isActive ? "active" : "")}>
      {label}
      {n != null && n > 0 && <span className={`count ${attn ? "attn" : ""}`}>{n}</span>}
    </NavLink>
  );
  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <div className="mark">{(st?.company ?? "H")[0]}</div>
          <div>
            <b>{st?.company.replace(" (fictional)", "").replace(" Components Ltd", "") ?? "Payables"}</b>
            <span>Accounts payable</span>
          </div>
        </div>
        <nav className="menu" aria-label="Main">
          {link("/inbox", "Inbox")}
          {link("/bills", "Bills", bills?.length)}
          {link("/approvals", "Approvals", count("needs_approval"), true)}
          {link("/payments", "Payments")}
          <span className="group">Records</span>
          {link("/suppliers", "Suppliers")}
          {link("/disputes", "Disputes", openCases, openCases > 0)}
          {link("/activity", "Activity")}
          <span className="group">Company</span>
          {link("/risk", "Risk and reserve")}
          {link("/market", "Market prices")}
          {link("/security", "Security")}
          {(can.bank || can.arbiter || can.owner) && link("/bank", "Bank")}
          {link("/settings", "Settings")}
        </nav>
        <div className="foot">
          <span>{st ? NETWORK[st.network] ?? st.network : ""}</span>
          <span>Demo date {st ? date(st.today) : ""}</span>
        </div>
      </aside>
      <div className="main">
        <header className="bar">
          <AskAgent />
          {st && (
            <span className="pill" title={st.chain.agent_paused ? "All bills go to a person until the owner resumes" : ""}>
              <span className={`dot ${st.chain.agent_paused ? "red" : ""}`} />
              {st.chain.agent_paused ? "Agent paused" : "Agent running"} · {st.bundle[0].toUpperCase() + st.bundle.slice(1)} risk
            </span>
          )}
          <Bell />
          <UserMenu />
        </header>
        <Banners />
        <main className="page">{children}</main>
      </div>
    </div>
  );
}

function Banners() {
  const { data: st, error } = useAppState();
  if (error && !st) return <div className="banner bad">The desk cannot reach the agent. Is the API running?</div>;
  if (!st) return null;
  return (
    <>
      {st.chain.agent_paused && <div className="banner bad">The agent is paused. Every bill goes to a person until the owner resumes it.</div>}
      {!st.consistency.ok && (
        <div className="banner warn">
          The records and the chain disagree on {st.consistency.mismatches.length} item(s). See Activity before paying more.
        </div>
      )}
      {st.chain.pool_paused && st.chain.mode !== "standard" && (
        <div className="banner warn">The reserve is paused. The agent cannot pay alone until the bank tops it up.</div>
      )}
    </>
  );
}

function Bell() {
  const { data } = useNotifications();
  const [open, setOpen] = useState(false);
  const nav = useNavigate();
  const n = data?.length ?? 0;
  return (
    <div style={{ position: "relative" }}>
      <button className="btn" aria-label={`Notifications (${n})`} onClick={() => setOpen(!open)}>
        Alerts {n > 0 && <b className="warn">{n}</b>}
      </button>
      {open && (
        <div className="popover right">
          <h3>Needs someone</h3>
          {n === 0 && <p className="muted" style={{ marginTop: 8 }}>Nothing waiting.</p>}
          <ul className="checks" style={{ marginTop: 8 }}>
            {data?.slice(0, 20).map((m, i) => (
              <li key={i}>
                <span className={`ck ${m.severity === "alert" ? "no" : "wa"}`}>{m.severity === "alert" ? "!" : "•"}</span>
                <button className="link" style={{ textAlign: "left", textDecoration: "none", color: "inherit" }}
                  onClick={() => { setOpen(false); nav(m.bill ? `/bills?bill=${m.bill}` : "/activity"); }}>
                  {m.text} <span className="muted small">· {ROLE[m.for === "finance_manager" ? "approver" : m.for] ?? m.for} · {time(m.ts)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const nav = useNavigate();
  const { disconnectAsync } = useDisconnect();
  const [open, setOpen] = useState(false);
  if (!me) return null;
  const signOut = async () => {
    if (me.kind === "account") await auth.signOut().catch(() => undefined);
    else await api.post("/wallet/logout").catch(() => undefined);
    await disconnectAsync().catch(() => undefined);
    qc.clear();
    nav("/login");
  };
  const switchTo = async (id: string) => {
    setOpen(false);
    await auth.setActive(id);
    qc.clear();
    nav("/bills");
  };
  const role = ROLE[me.role] ?? me.role;
  if (me.kind !== "account")
    return (
      <span className="row">
        <span className="small">
          <b>{role}</b> {me.address && <span className="mono muted">{shortAddr(me.address)}</span>}
        </span>
        <button className="btn small" onClick={signOut}>Sign out</button>
      </span>
    );
  const others = me.companies.filter((c) => c.id !== me.company);
  return (
    <div style={{ position: "relative" }}>
      <button className="btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="small"><b>{me.name}</b> <span className="muted">· {role}</span></span>
      </button>
      {open && (
        <div className="popover right stack" role="menu" style={{ width: 260 }}>
          <div className="small">
            <div>{me.email}</div>
            <div className="muted">{me.companies.find((c) => c.id === me.company)?.name}</div>
          </div>
          {others.length > 0 && (
            <>
              <h3>Switch company</h3>
              {others.map((c) => (
                <button key={c.id} className="btn small" style={{ justifyContent: "flex-start" }} onClick={() => switchTo(c.id)}>{c.name}</button>
              ))}
            </>
          )}
          <button className="btn small" style={{ justifyContent: "flex-start" }} onClick={() => { setOpen(false); nav("/settings?tab=account"); }}>My account</button>
          <button className="btn small" style={{ justifyContent: "flex-start" }} onClick={() => { setOpen(false); nav("/welcome"); }}>Create or join a company</button>
          <button className="btn small" style={{ justifyContent: "flex-start" }} onClick={signOut}>Sign out</button>
        </div>
      )}
    </div>
  );
}
