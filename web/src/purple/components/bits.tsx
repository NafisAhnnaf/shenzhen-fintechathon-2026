import type { ReactNode } from "react";
import type { Tier } from "../lib/api";
import { useAppState } from "../lib/hooks";
import { money, shortHash } from "../lib/format";

/** Tier as a quiet coloured word with a matching rule on its left, not a pill. */
export function TierMark({ tier, status }: { tier: Tier; status?: string }) {
  const k = status === "paid" ? (tier === "T1" ? "alone" : "signed") : status === "rejected" ? "rejected" : tier;
  const map: Record<string, [string, string]> = {
    alone: ["Paid on its own", "b-done"],
    signed: ["Paid with signature", "b-done"],
    T1: ["Clear to pay", "b-done"],
    T2: ["Needs signature", "b-attn"],
    hold: ["Held", "b-stop"],
    reject: ["Rejected", "b-stop"],
    rejected: ["Rejected", "b-stop"],
  };
  const [label, cls] = map[k ?? ""] ?? ["Not checked", "b-idle"];
  return <span className={`badge ${cls}`}>{label}</span>;
}

/** A transaction hash: monospace, shortened, linked to the explorer when there is a public one. */
export function Hash({ h }: { h?: string | null }) {
  const { data } = useAppState();
  if (!h) return null;
  const text = <span className="font-mono text-xs">{shortHash(h)}</span>;
  // A public explorer when there is one (Base Sepolia); otherwise our own receipt lookup on the connected chain (FISCO, local).
  const href = data?.explorer ? `${data.explorer}/tx/${h}` : `/api/tx/${h}`;
  return (
    <a className="hash" href={href} target="_blank" rel="noreferrer" title={h}>
      {text}
    </a>
  );
}

/** A figure with the place it came from written under it (policy S5 on screen). */
export function Figure({ value, source, size = "lg", tone = "ink" }: { value: number | null | undefined; source: string; size?: "lg" | "xl" | "3xl"; tone?: "ink" | "ledger" | "ochre" | "muted" }) {
  const sz = { lg: "text-lg", xl: "text-xl", "3xl": "text-3xl font-medium tracking-tight" }[size];
  const tc = { ink: "text-ink", ledger: "text-ledger", ochre: "text-ochre", muted: "text-muted" }[tone];
  return (
    <div>
      <div className={`${sz} ${tc}`}>{money(value)}</div>
      <div className="mt-0.5 text-sm text-muted">{source}</div>
    </div>
  );
}

export function Section({ title, aside, children, className = "" }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-6 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-xl text-ink">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="err mt-2" role="alert">{error instanceof Error ? error.message : String(error)}</p>;
}

export function Dl({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 gap-y-1.5 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="text-right">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
