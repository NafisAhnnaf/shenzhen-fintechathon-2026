import { useEffect, useState, type ReactNode } from "react";
import { useAccount, useConnect, useConnections, useDisconnect, useSendTransaction, useSignTypedData, useSwitchAccount } from "wagmi";
import { api, type PreparedTx, type Stage, type TypedData } from "../lib/api";
import { PAYER, STAGE, money, shortHash } from "../lib/format";
import { useAppState, useMe } from "../lib/hooks";
import { DEV_ACCOUNTS, forViem, txFor } from "../lib/wallet";

export function StatusTag({ stage }: { stage: Stage | string }) {
  const [label, cls] = STAGE[stage] ?? [stage, "st-idle"];
  return <span className={`status ${cls}`}>{label}</span>;
}

export function Tag({ tone, children }: { tone: "review" | "ok" | "bad" | "idle" | "info"; children: ReactNode }) {
  return <span className={`status st-${tone}`}>{children}</span>;
}

export function PaidBy({ by }: { by: string | null }) {
  if (!by) return null;
  const short = by === "agent" ? "A" : by === "finance_manager" ? "FM" : "ERP";
  return (
    <span className={`by ${by === "agent" ? "agent" : ""}`}>
      <i>{short}</i>
      {PAYER[by] ?? by}
    </span>
  );
}

/** A transaction hash, shortened, linked to the explorer or to our own receipt lookup. */
export function Hash({ h }: { h?: string | null }) {
  const { data } = useAppState();
  if (!h) return <span className="muted">–</span>;
  const href = data?.explorer ? `${data.explorer}/tx/${h}` : `/api/tx/${h}`;
  return (
    <a className="mono" href={href} target="_blank" rel="noreferrer" title={h}>
      {shortHash(h)}
    </a>
  );
}

export function Money({ v, className = "" }: { v: number | null | undefined; className?: string }) {
  return <span className={`amt ${className}`}>{money(v)}</span>;
}

export function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <p className="err">{msg.replace(/^User rejected.*$/s, "You cancelled the request in your wallet.")}</p>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {children && <span>{children}</span>}
    </div>
  );
}

export function PageHead({ title, sub, actions }: { title: string; sub?: string; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: [T, string, number?][] }) {
  return (
    <div className="tabs" role="tablist">
      {items.map(([k, label, n]) => (
        <button key={k} role="tab" aria-selected={value === k} onClick={() => onChange(k)}>
          {label}
          {n != null && <span className="c">{n}</span>}
        </button>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="between">
          <h2>{title}</h2>
          <button className="btn small" onClick={onClose}>
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Toast({ text, onDone }: { text: string; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 3200);
    return () => clearTimeout(t);
  }, [text, onDone]);
  return <div className="toast" role="status">{text}</div>;
}

// ------------------------------------------------------------------ period selector (payments, bills, activity)
const iso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (s: string, n: number) => {
  const d = new Date(`${s}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return iso(d);
};

export const PERIODS: [string, string][] = [
  ["today", "Today"],
  ["7d", "Last 7 days"],
  ["month", "This month"],
  ["lastmonth", "Last month"],
  ["90d", "Last 90 days"],
  ["year", "This year"],
  ["all", "All time"],
  ["custom", "Custom range"],
];

export interface Period {
  key: string;
  from: string;
  to: string;
}

export function periodBounds(key: string, today: string, custom?: { from: string; to: string }): [string | null, string | null] {
  const [y, m] = today.split("-").map(Number);
  switch (key) {
    case "today":
      return [today, today];
    case "7d":
      return [addDays(today, -6), today];
    case "month":
      return [`${y}-${String(m).padStart(2, "0")}-01`, today];
    case "lastmonth":
      return [iso(new Date(Date.UTC(y, m - 2, 1))), iso(new Date(Date.UTC(y, m - 1, 0)))];
    case "90d":
      return [addDays(today, -89), today];
    case "year":
      return [`${y}-01-01`, today];
    case "custom":
      return [custom?.from || null, custom?.to || null];
    default:
      return [null, null];
  }
}

export function PeriodPicker({ value, onChange, today }: { value: Period; onChange: (p: Period) => void; today: string }) {
  const [from, to] = periodBounds(value.key, today, value);
  return (
    <div className="row">
      <label className="row" htmlFor="period">
        <b>Period</b>
      </label>
      <select id="period" className="field" value={value.key} onChange={(e) => onChange({ ...value, key: e.target.value })}>
        {PERIODS.map(([k, l]) => (
          <option key={k} value={k}>
            {l}
          </option>
        ))}
      </select>
      {value.key === "custom" ? (
        <>
          <input type="date" className="field" aria-label="From" value={value.from} max={today} onChange={(e) => onChange({ ...value, from: e.target.value })} />
          <span className="muted">to</span>
          <input type="date" className="field" aria-label="To" value={value.to} max={today} onChange={(e) => onChange({ ...value, to: e.target.value })} />
        </>
      ) : (
        <span className="muted">{from && to ? `${fmt(from)} – ${fmt(to)}` : "Everything"}</span>
      )}
    </div>
  );
}

const fmt = (s: string) =>
  new Date(`${s}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** Remember a choice for this browser (tab, period). Storage can be unavailable; the default is used then. */
export function useRemembered<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const s = localStorage.getItem(`desk:${key}`);
      return s ? (JSON.parse(s) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = (x: T) => {
    setV(x);
    try {
      localStorage.setItem(`desk:${key}`, JSON.stringify(x));
    } catch {
      /* private window */
    }
  };
  return [v, set];
}

// ------------------------------------------------------------------ wallet steps
/** Make sure the wallet that signs is the one the person signed in with. After a page reload the session cookie
 * survives but the wallet connection may not: reconnect the matching wallet, and never sign with another one. */
export function useEnsureWallet() {
  const { address, isConnected } = useAccount();
  const { connectors, connectAsync } = useConnect();
  const connections = useConnections();
  const { disconnectAsync } = useDisconnect();
  const { switchAccountAsync } = useSwitchAccount();
  const { data: me } = useMe();
  return async () => {
    const want = me?.address?.toLowerCase();
    if (!want || (isConnected && address?.toLowerCase() === want)) return;
    // Several wallets can be connected at once; if the right one is among them, make it the active one.
    const have = connections.find((c) => c.accounts.some((x) => x.toLowerCase() === want));
    if (have) {
      await switchAccountAsync({ connector: have.connector });
      return;
    }
    // Local test wallets: we know which address each one holds. Otherwise try the wallets in turn.
    const mocks = connectors.filter((c) => c.type === "mock");
    const devIdx = DEV_ACCOUNTS.findIndex(([, a]) => a.toLowerCase() === want);
    const known = devIdx >= 0 && mocks[devIdx] ? [mocks[devIdx]] : [];
    const local = connectors.filter((c) => c.type === "localKey" && c.id.toLowerCase().endsWith(want));
    const errs: string[] = [];
    for (const c of [...known, ...local, ...connectors.filter((c) => c.type !== "mock" && c.type !== "localKey")]) {
      try {
        const r = await connectAsync({ connector: c });
        if (r.accounts.some((x) => x.toLowerCase() === want)) return;
        errs.push(`${c.name}: holds ${r.accounts[0]}`);
        await disconnectAsync({ connector: c });
      } catch (e) {
        errs.push(`${c.name}: ${e instanceof Error ? e.message.split("\n")[0] : e}`);
      }
    }
    throw new Error(`Connect the wallet you signed in with (${want.slice(0, 6)}…${want.slice(-4)}).`);
  };
}

/** The local test wallet for the signed-in address, if it is one: its provider signs directly (the Hardhat node,
 * or the test key in the browser on FISCO), whatever the wallet library's connection state after a reload. */
function useTestWallet() {
  const { connectors } = useConnect();
  const { data: me } = useMe();
  return async (): Promise<{ provider: any; address: string } | null> => {
    const want = me?.address?.toLowerCase();
    if (!want) return null;
    const mocks = connectors.filter((c) => c.type === "mock");
    const i = DEV_ACCOUNTS.findIndex(([, a]) => a.toLowerCase() === want);
    const c = (i >= 0 ? mocks[i] : undefined) ?? connectors.find((x) => x.type === "localKey" && x.id.toLowerCase().endsWith(want));
    return c ? { provider: await c.getProvider(), address: me!.address } : null;
  };
}

/** Sign EIP-712 typed data the API prepared. */
export function useSignData() {
  const { signTypedDataAsync } = useSignTypedData();
  const ensure = useEnsureWallet();
  const test = useTestWallet();
  return async (td: TypedData): Promise<`0x${string}`> => {
    const t = await test();
    if (t) return t.provider.request({ method: "eth_signTypedData_v4", params: [t.address, JSON.stringify(td)] });
    await ensure();
    return signTypedDataAsync(forViem(td));
  };
}

/** Send a transaction the API prepared from the person's wallet and return its hash. */
export function useSendPrepared() {
  const { sendTransactionAsync } = useSendTransaction();
  const ensure = useEnsureWallet();
  const test = useTestWallet();
  return async (tx: PreparedTx): Promise<`0x${string}`> => {
    const t = await test();
    if (t) return t.provider.request({ method: "eth_sendTransaction", params: [{ from: t.address, to: tx.to, data: tx.data, gas: tx.gas }] });
    await ensure();
    return sendTransactionAsync(txFor(tx));
  };
}

/** CSV download built in the browser. */
export function downloadCsv(name: string, rows: (string | number | null)[][]) {
  const text = rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export const verifyLine = (index: number) => api.get<any>(`/journal/${index}/verify`);
