import { useState } from "react";
import { useSendTransaction } from "wagmi";
import { api, type PreparedTx } from "../lib/api";
import { money, time } from "../lib/format";
import { useAction, useAppState, useRole } from "../lib/hooks";
import { txFor } from "../lib/wallet";
import { ErrorLine } from "../components/bits";

const MODE: Record<string, [string, string]> = {
  standard: ["Standard", "No reserve behind autonomous payments; every one is capped by the contract limits."],
  self_reserve: ["Self reserve", "The company sets aside its own reserve against the clerk's mistakes."],
  bonded: ["Bonded", "An underwriter's bond pool stands behind every payment the clerk makes alone."],
};

/** Owner settings: payees, reserve mode, the ERP link, and the demo controls. */
export default function Settings() {
  const { data: st } = useAppState();
  const { role } = useRole();
  const { sendTransactionAsync } = useSendTransaction();
  const owner = role === "owner";
  const unfreeze = useAction(async (sid: string) => {
    const r = await api.get<{ tx: PreparedTx }>(`/owner-tx/unfreeze?supplier=${sid}`);
    const hash = await sendTransactionAsync(txFor(r.tx));
    return api.post(`/payees/${sid}/unfreeze`, { tx_hash: hash });
  });
  const sync = useAction(() => api.post("/erp/sync"));
  const nextDay = useAction(() => api.post<{ today: string }>("/demo/next-day"));
  const advance = useAction(() => api.post("/demo/advance?seconds=301"));
  const reset = useAction(() => api.post("/admin/reset"));
  const [confirmReset, setConfirmReset] = useState(false);
  if (!st) return null;
  const [modeName, modeText] = MODE[st.chain.mode] ?? [st.chain.mode, ""];
  const local = st.network === "localhost";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl">Settings</h1>
        <p className="mt-2 text-muted">{owner ? "You are the owner: changes here are signed by your wallet." : "Only the owner can change these. You can read them."}</p>
      </div>

      <section className="card p-6">
        <h2 className="text-xl">Payees</h2>
        <p className="mt-1 text-sm text-muted">The contract pays only these registered suppliers. A frozen payee gets nothing until the owner unfreezes it on-chain.</p>
        <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="text-left text-muted">
            <tr className="rule-b">
              <th className="py-2 font-normal">Supplier</th>
              <th className="py-2 font-normal">Contact</th>
              <th className="py-2 font-normal">Rail</th>
              <th className="py-2 text-right font-normal">State</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(st.suppliers).map(([sid, s]) => (
              <tr key={sid} className="rule-b">
                <td className="py-2.5 pr-3 font-semibold">{s.name}</td>
                <td className="py-2.5 pr-3 text-muted">{s.contact}</td>
                <td className="py-2.5 pr-3">{s.rail === "token" ? "tUSDC" : "Bank"}</td>
                <td className="py-2.5 text-right">
                  {s.frozen ? (
                    owner ? (
                      <button className="btn-quiet" disabled={unfreeze.isPending} onClick={() => unfreeze.mutate(sid)} aria-label={`Unfreeze ${s.name}`}>
                        {unfreeze.isPending && unfreeze.variables === sid ? "Waiting for your wallet" : "Unfreeze"}
                      </button>
                    ) : (
                      <span className="badge b-stop">Frozen</span>
                    )
                  ) : s.probation_left > 0 ? (
                    <span className="badge b-attn">Next {s.probation_left} bills go to a person</span>
                  ) : (
                    <span className="badge b-done">Active</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        <ErrorLine error={unfreeze.error} />
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <section className="card p-6">
          <h2 className="text-xl">Reserve mode</h2>
          <p className="mt-3">
            <span className="badge b-attn">{modeName}</span>
          </p>
          <p className="mt-2 text-sm text-muted">{modeText}</p>
          <dl className="kv mt-4">
            <dt>Reserve r</dt>
            <dd>{money(st.chain.r_usd)}</dd>
            <dt>Bond pool free</dt>
            <dd>{money(st.chain.pool_free_usd)}</dd>
            <dt>Per-day limit</dt>
            <dd>{money(st.chain.p_day_usd)}</dd>
          </dl>
          <p className="mt-3 text-sm text-muted">Change how much the clerk does alone on the Risk page.</p>
        </section>
        <section className="card p-6">
          <h2 className="text-xl">Accounting system</h2>
          <dl className="kv mt-3">
            <dt>Source</dt>
            <dd>{(st as any).erp?.adapter === "odoo" ? "Odoo" : "Ledger file"}</dd>
            <dt>Orders</dt>
            <dd>{(st as any).erp?.orders ?? "–"}</dd>
            <dt>Suppliers</dt>
            <dd>{(st as any).erp?.suppliers ?? "–"}</dd>
            <dt>Last read</dt>
            <dd>{(st as any).erp?.last_sync ? time((st as any).erp.last_sync) : "–"}</dd>
          </dl>
          <button className="btn-quiet mt-4" disabled={sync.isPending} onClick={() => sync.mutate(undefined)}>
            {sync.isPending ? "Reading" : "Read orders again"}
          </button>
          <ErrorLine error={sync.error} />
        </section>
      </div>

      {local && (
        <section className="card p-6">
          <h2 className="text-xl">Demo controls</h2>
          <p className="mt-1 text-sm text-muted">Local chain only. Today is {st.today}.</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <button className="btn-quiet" disabled={nextDay.isPending} onClick={() => nextDay.mutate(undefined)}>
              Move to the next day
            </button>
            <button className="btn-quiet" disabled={advance.isPending} onClick={() => advance.mutate(undefined)}>
              Skip 5 minutes
            </button>
            {!confirmReset ? (
              <button className="btn-danger" onClick={() => setConfirmReset(true)}>
                Reset the demo
              </button>
            ) : (
              <span className="flex flex-wrap items-center gap-3">
                <span className="err">Redeploys the contracts and clears every bill. Sure?</span>
                <button
                  className="btn-danger"
                  disabled={reset.isPending}
                  onClick={() => reset.mutate(undefined, { onSettled: () => setConfirmReset(false) })}
                >
                  {reset.isPending ? "Resetting" : "Yes, reset"}
                </button>
                <button className="btn-quiet" onClick={() => setConfirmReset(false)}>
                  Cancel
                </button>
              </span>
            )}
          </div>
          {nextDay.data && <p className="ok mt-3">Now {nextDay.data.today}; yesterday's log is anchored on-chain.</p>}
          {reset.isSuccess && <p className="ok mt-3">Fresh contracts deployed. The desk is empty again.</p>}
          <ErrorLine error={nextDay.error || advance.error || reset.error} />
        </section>
      )}
    </div>
  );
}
