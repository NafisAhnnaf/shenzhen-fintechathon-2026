import { useEffect, useRef } from "react";
import { useAppState, useLog, useSupplierName } from "../lib/hooks";
import { ACTOR, QUIET, describe, money0, time } from "../lib/format";
import { Hash } from "./bits";

const ACTOR_TONE: Record<string, string> = {
  agent: "text-ink",
  governor: "text-ink",
  contract: "text-ledger",
  finance_manager: "text-ochre",
  owner: "text-ochre",
  underwriter: "text-ochre",
  system: "text-oxblood",
};

/** The journal: every action, who took it, and its transaction. Newest first. */
export function Journal({ security = false, onBill }: { security?: boolean; onBill?: (id: string) => void }) {
  const { data } = useLog(security);
  const name = useSupplierName();
  const seen = useRef<Set<string>>(new Set());
  const first = useRef(true);
  const lines = (data ?? []).filter((l) => !QUIET.has(l.kind)).slice().reverse();
  useEffect(() => {
    first.current = false;
  });
  return (
    <ol className="divide-y divide-rule" aria-label="Journal">
      {lines.length === 0 && <li className="py-3 text-sm text-muted">Nothing has happened yet. Take a bill from the inbox to start.</li>}
      {lines.map((l) => {
        const key = `${l.ts}-${l.kind}-${l.bill_id ?? ""}`;
        const fresh = !first.current && !seen.current.has(key) && (l.kind === "pay_autonomous" || l.kind === "pay_approved");
        seen.current.add(key);
        return (
          <li key={key} className={`py-2.5 ${fresh ? "settle" : ""}`}>
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className={`font-medium ${l.security ? "text-oxblood" : ACTOR_TONE[l.actor] ?? "text-ink"}`}>{ACTOR[l.actor] ?? l.actor}</span>
              <span className="text-faint">{time(l.ts)}</span>
            </div>
            <p className="mt-0.5 text-sm leading-snug">
              {l.bill_id && onBill ? (
                <button className="text-left hover:underline" onClick={() => onBill(l.bill_id!)}>
                  {describe(l, name)}
                </button>
              ) : (
                describe(l, name)
              )}
            </p>
            {l.tx_hash && (
              <div className="mt-0.5">
                <Hash h={l.tx_hash} />
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** What the agent has done for the money, in a few plain lines. */
export function Tally() {
  const { data } = useAppState();
  const m = data?.money;
  if (!m) return null;
  const rows: [string, string][] = [
    ["Paid on its own", `${money0(m.t1_paid)} in ${m.t1_count} ${m.t1_count === 1 ? "bill" : "bills"}`],
    ["Paid with a signature", `${money0(m.t2_paid)} in ${m.t2_count} ${m.t2_count === 1 ? "bill" : "bills"}`],
    ["Overcharges held back", money0(m.overcharges_held)],
    ["Duplicates stopped", money0(m.duplicates_blocked)],
    ["Recovered from suppliers", money0(m.recovered)],
    ["Early-payment discounts", money0(m.discounts_taken)],
    ["Attacks refused", String(m.attacks_blocked)],
  ];
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="text-right">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
