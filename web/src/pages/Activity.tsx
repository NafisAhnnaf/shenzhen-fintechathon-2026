import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { money0 } from "../lib/format";
import { useAppState } from "../lib/hooks";
import { Journal, Tally } from "../components/Journal";
import { Hash } from "../components/bits";

/** What the agent did, in order, and the on-chain record behind it. */
export default function Activity() {
  const [tab, setTab] = useState<"journal" | "tally" | "evidence">("journal");
  const { data: st } = useAppState();
  const m = st?.money;

  return (
    <div className="mx-auto max-w-[1100px] px-4 pb-20 pt-8 sm:px-6 space-y-8">
      {/* Title & Overview */}
      <div>
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-ledger-soft px-2 py-0.5 text-xs font-semibold text-ledger border border-ledger/20">
            Immutable Audit Trail
          </span>
          <span className="text-xs text-muted">Arbitrum Nova On-Chain Journal</span>
        </div>
        <h1 className="mt-2 text-2xl sm:text-3xl font-bold tracking-tight text-ink">
          Activity & Cryptographic Audit Journal
        </h1>
        <p className="mt-2 max-w-[70ch] text-sm text-muted">
          Every autonomous disbursement, human co-signature, quarantine isolation, and contract state mutation is cryptographically logged with Merkle roots anchored on-chain.
        </p>
      </div>

      {/* Metric Cards Banner */}
      {m && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="surface-card p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted">
              Autonomous Disbursements
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-ledger">
              {money0(m.t1_paid)}
            </div>
            <div className="mt-0.5 text-xs text-muted">
              {m.t1_count} zero-click settlements
            </div>
          </div>
          <div className="surface-card p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted">
              Dual-Key Co-Signed
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-ochre">
              {money0(m.t2_paid)}
            </div>
            <div className="mt-0.5 text-xs text-muted">
              {m.t2_count} approved via EIP-712
            </div>
          </div>
          <div className="surface-card p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted">
              Overcharges Quarantined
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-ink">
              {money0(m.overcharges_held)}
            </div>
            <div className="mt-0.5 text-xs text-muted">
              Protected via LME index checks
            </div>
          </div>
          <div className="surface-card p-4">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted">
              Attacks Intercepted
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-ledger">
              {m.attacks_blocked}
            </div>
            <div className="mt-0.5 text-xs text-muted">
              Prompt injections neutralized
            </div>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="surface-card p-6">
        <div className="flex gap-4 border-b border-rule pb-3 text-sm" role="tablist">
          {[
            ["journal", "Live Activity Stream"],
            ["tally", "Financial Performance Tally"],
            ["evidence", "Contract Anchors & Test Runs"],
          ].map(([k, label]) => (
            <button
              key={k}
              role="tab"
              aria-selected={tab === k}
              onClick={() => setTab(k as any)}
              className={`rounded-lg px-3 py-1.5 font-medium transition-all ${
                tab === k
                  ? "bg-ledger-soft text-ledger border border-ledger/20 shadow-xs"
                  : "text-muted hover:bg-paper hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {tab === "journal" && <Journal />}
          {tab === "tally" && (
            <div className="max-w-md">
              <Tally />
            </div>
          )}
          {tab === "evidence" && <Evidence />}
        </div>
      </div>
    </div>
  );
}

function Evidence() {
  const { data: st } = useAppState();
  const { data: ev } = useQuery({
    queryKey: ["evidence"],
    queryFn: () => api.get<any>("/evidence"),
  });

  return (
    <div className="space-y-6">
      {st && (
        <div className="rounded-xl border border-rule bg-paper p-4 text-xs space-y-3">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${st.consistency.ok ? "bg-ledger" : "bg-oxblood"}`} />
            <span className={`font-semibold ${st.consistency.ok ? "text-ledger" : "text-oxblood"}`}>
              {st.consistency.ok
                ? `Cryptographic Merkle Consistency Verified across ${st.consistency.checked} ledger entries.`
                : `${st.consistency.mismatches.length} discrepancy items detected.`}
            </span>
          </div>

          <div className="border-t border-rule pt-3">
            <div className="text-[11px] font-semibold text-muted uppercase tracking-wider mb-2">
              Deployed Smart Contract Registries
            </div>
            <dl className="grid grid-cols-[10rem_minmax(0,1fr)] gap-y-1.5 font-mono text-[11px]">
              {Object.entries(st.contracts).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">
                    {{
                      token: "Test Dollar (USDC)",
                      vault: "Bonded Payment Vault",
                      pool: "Collective Reserve Pool",
                      anchor: "State Log Anchor",
                      naive: "Naive Wallet (Test)",
                    }[k] ?? k}
                  </dt>
                  <dd className="truncate text-ink font-semibold">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}

      {ev?.tasks && (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs font-semibold">
            <span className="text-ink">Automated Test Suites on {ev.network}</span>
            <span className="rounded-full bg-ledger-soft px-2.5 py-0.5 text-ledger border border-ledger/20">
              {ev.summary.passed} / {ev.summary.total} Suites Passed
            </span>
          </div>

          <ul className="divide-y divide-rule border border-rule rounded-xl overflow-hidden bg-surface text-xs">
            {ev.tasks.map((t: any) => (
              <li key={t.task} className="p-3.5 hover:bg-paper/50 transition-colors">
                <details>
                  <summary className="flex cursor-pointer items-center justify-between">
                    <span className="font-semibold text-ink">{t.title}</span>
                    <span className={`font-semibold ${t.ok ? "text-ledger" : "text-oxblood"}`}>
                      {t.ok ? "Passed ✓" : "Failed ✗"}
                    </span>
                  </summary>
                  <ul className="mt-2.5 space-y-1.5 pl-3 border-l-2 border-rule text-muted">
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
