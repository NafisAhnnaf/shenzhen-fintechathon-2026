import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { money0 } from "../lib/format";
import { useAppState } from "../lib/hooks";
import { Journal } from "../components/Journal";
import { Hash } from "../components/bits";

/** What the agent did, in order, and the on-chain record behind it. */
export default function Activity() {
  const [tab, setTab] = useState<"journal" | "evidence">("journal");
  return (
    <div className="space-y-6">
      <Summary />
      <div className="mt-8 flex gap-5 border-b border-rule text-sm" role="tablist">
        {(
          [
            ["journal", "Everything the agent did"],
            ["evidence", "Tasks and contracts"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={`-mb-px border-b-2 pb-2 ${tab === k ? "border-ink font-medium" : "border-transparent text-muted hover:text-ink"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="mt-2">{tab === "journal" ? <Journal /> : <Evidence />}</div>
    </div>
  );
}

function Summary() {
  const { data } = useAppState();
  const m = data?.money;
  if (!m) return null;
  const parts = [
    `paid ${money0(m.t1_paid)} on its own`,
    m.t2_paid ? `${money0(m.t2_paid)} after a signature` : "",
    m.overcharges_held ? `held back ${money0(m.overcharges_held)} of overcharges` : "",
    m.recovered ? `recovered ${money0(m.recovered)}` : "",
    m.attacks_blocked ? `refused ${m.attacks_blocked} ${m.attacks_blocked === 1 ? "attack" : "attacks"}` : "",
  ].filter(Boolean);
  return <p className="max-w-[60ch] text-xl leading-snug">So far the agent has {parts.join(", ")}.</p>;
}

function Evidence() {
  const { data: st } = useAppState();
  const { data: ev } = useQuery({ queryKey: ["evidence"], queryFn: () => api.get<any>("/evidence") });
  return (
    <div className="space-y-8 pt-4">
      {st && (
        <div className="text-sm">
          <p className={st.consistency.ok ? "text-ledger" : "text-oxblood"}>
            {st.consistency.ok
              ? `Our records and the chain agree on all ${st.consistency.checked} bills.`
              : `${st.consistency.mismatches.length} bills differ between our records and the chain.`}
          </p>
          <dl className="mt-3 grid grid-cols-[9rem_minmax(0,1fr)] gap-y-1">
            {Object.entries(st.contracts).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted">{{ token: "Test dollar", vault: "Payment vault", pool: "Reserve pool", anchor: "Log anchor", naive: "No-rules wallet" }[k] ?? k}</dt>
                <dd className="truncate font-mono text-xs leading-5">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {!ev?.tasks && <p className="text-sm text-muted">No scripted run recorded on this network yet.</p>}
      {ev?.tasks && (
        <div>
          <p className="text-sm text-muted">
            Scripted run on {ev.network}: {ev.summary.passed} of {ev.summary.total} tasks passed.
          </p>
          <ul className="mt-2 divide-y divide-rule">
            {ev.tasks.map((t: any) => (
              <li key={t.task} className="py-2.5">
                <details>
                  <summary className="flex cursor-pointer items-baseline justify-between gap-4">
                    <span>{t.title}</span>
                    <span className={`shrink-0 text-sm ${t.ok ? "text-ledger" : "text-oxblood"}`}>{t.ok ? "Passed" : "Failed"}</span>
                  </summary>
                  <ul className="mt-2 space-y-1 text-sm text-muted">
                    {t.steps
                      .filter((s: any) => s.action)
                      .map((s: any, i: number) => (
                        <li key={i} className="flex flex-wrap justify-between gap-x-4">
                          <span>{s.action}</span>
                          {s.tx_hash && <Hash h={s.tx_hash} />}
                        </li>
                      ))}
                  </ul>
                </details>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
