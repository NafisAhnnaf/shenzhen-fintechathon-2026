import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type PreparedTx } from "../lib/api";
import { date, money, money0, pct } from "../lib/format";
import { useAction, useCan } from "../lib/hooks";
import { Empty, ErrorLine, PageHead, Tag, useSendPrepared } from "../components/ui";

const CLAIM: Record<string, string> = { locked: "Reserve locked", released: "Released", filed: "Claim filed", disputed: "Disputed", resolved: "Decided", paid: "Paid out" };

export default function Bank() {
  const { data: b, error } = useQuery({ queryKey: ["bank"], queryFn: () => api.get<any>("/bank"), refetchInterval: 5000 });
  const can = useCan();
  const send = useSendPrepared();
  const [amount, setAmount] = useState("");
  const [decide, setDecide] = useState<Record<string, string>>({});
  const act = useAction(async (x: { action: string; bill?: string; usd?: number; settings?: string }) => {
    const qs = new URLSearchParams({ ...(x.bill ? { bill: x.bill } : {}), ...(x.usd != null ? { amount: String(x.usd) } : {}), ...(x.settings ? { settings: x.settings } : {}) });
    const action = x.action === "approve_settings" ? "approve_settings" : x.action;
    const r = await api.get<{ tx?: PreparedTx; txs?: PreparedTx[] }>(`/bank/tx/${action}?${qs}`);
    let hash = "";
    for (const t of r.txs ?? [r.tx!]) hash = await send(t);
    if (x.action === "approve_settings") {
      const out = await api.post<any>(`/settings/${x.settings}/underwriter`, { tx_hash: hash });
      if (out.error) throw new Error(out.error);
      return out;
    }
    const out = await api.post<any>(`/bank/${x.action}`, { tx_hash: hash, bill: x.bill, amount: x.usd });
    if (out.error) throw new Error(out.error);
    return out;
  });
  if (error) return <ErrorLine error={error} />;
  if (!b) return <p className="muted">Loading</p>;
  const p = b.pool;
  const disputed = b.locks.filter((l: any) => l.status === "disputed");
  const pending = Object.entries(b.pending_settings ?? {}) as [string, string][];
  return (
    <>
      <PageHead title="Bank" sub="The bank funds the reserve that repays the agent's mistakes, earns a premium for it, and may dispute a claim. An independent arbiter settles disputes." />
      <div className="card tiles">
        <div><div className="k">Reserve</div><div className="v">{money0(p.pool_balance_usd)}</div><div className="muted small">{p.pool_paused ? "Paused" : "Open"}</div></div>
        <div><div className="k">Locked against payments</div><div className="v">{money0(p.pool_locked_usd)}</div><div className="muted small">{money0(p.r_usd)} per payment by the agent</div></div>
        <div><div className="k">Free</div><div className="v">{money0(p.pool_free_usd)}</div><div className="muted small">needed for this setting: {money0(b.setting.K_usd)}</div></div>
        <div><div className="k">Premiums due</div><div className="v">{money(b.premiums_due_usd)}</div><div className="muted small">on {b.locks.length} covered payment(s)</div></div>
      </div>
      <p className="note">
        Setting "{b.setting.name}": loss budget {pct(b.setting.beta)}, about {pct(b.setting.t1_share, 0)} of bills paid by the agent, worst month capped at {money0(b.setting.max_exposure_usd)}.
        {p.pool_owed_usd ? ` ${money0(p.pool_owed_usd)} of claims could not be paid in full and is owed.` : ""}
      </p>

      {pending.length > 0 && (
        <div className="card pad stack">
          <h2>Settings waiting for the bank</h2>
          {pending.map(([sid, name]) => (
            <div key={sid} className="between">
              <span>The owner proposed the "{name}" setting (settings {sid}).</span>
              {can.bank ? <button className="btn primary" disabled={act.isPending} onClick={() => act.mutate({ action: "approve_settings", settings: sid })}>Approve from my wallet</button> : <span className="note">The bank approves this.</span>}
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div style={{ padding: "12px 14px" }}><h2>Covered payments and claims</h2></div>
        {b.locks.length === 0 ? <Empty title="No payments covered yet" /> : (
          <div className="tablebox">
            <table>
              <thead><tr><th>Bill</th><th>Paid</th><th className="r">Amount</th><th className="r">Reserve</th><th className="r">Premium</th><th>Status</th><th className="r">Claimed</th><th /></tr></thead>
              <tbody>
                {b.locks.map((l: any) => (
                  <tr key={l.bill}>
                    <td>{l.supplier}<span className="s2 mono">{l.bill}</span></td>
                    <td>{date(l.paid_on)}</td>
                    <td className="r amt">{money(l.amount)}</td>
                    <td className="r amt">{money(l.reserve_usd)}</td>
                    <td className="r amt">{money(l.premium)}</td>
                    <td><Tag tone={l.status === "filed" || l.status === "disputed" ? "review" : l.status === "paid" ? "bad" : "idle"}>{CLAIM[l.status] ?? l.status}</Tag></td>
                    <td className="r amt">{l.loss_usd ? money(l.loss_usd) : "–"}</td>
                    <td>
                      {l.status === "filed" && can.bank && <button className="btn small" disabled={act.isPending} onClick={() => act.mutate({ action: "dispute", bill: l.bill })}>Dispute</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {disputed.length > 0 && (
        <div className="card pad stack">
          <h2>Disputed claims (the arbiter decides)</h2>
          {disputed.map((l: any) => (
            <div key={l.bill} className="between">
              <span>{l.supplier}, {l.bill}: claimed {money(l.loss_usd)}</span>
              {can.arbiter ? (
                <span className="row">
                  <input className="field" type="number" min="0" max={l.loss_usd} step="0.01" placeholder="Amount to pay" value={decide[l.bill] ?? ""} onChange={(e) => setDecide({ ...decide, [l.bill]: e.target.value })} />
                  <button className="btn primary" disabled={!decide[l.bill] || act.isPending} onClick={() => act.mutate({ action: "resolve", bill: l.bill, usd: Number(decide[l.bill]) })}>Decide</button>
                </span>
              ) : <span className="note">The arbiter decides from their own wallet.</span>}
            </div>
          ))}
        </div>
      )}

      {can.bank && (
        <div className="card pad stack">
          <h2>Top up the reserve</h2>
          <div className="row">
            <input className="field" type="number" min="0" step="1000" placeholder="Amount in USD" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <button className="btn" disabled={!amount || act.isPending} onClick={() => act.mutate({ action: "fund", usd: Number(amount) })}>Add from my wallet</button>
            {p.pool_paused && <button className="btn" disabled={act.isPending} onClick={() => act.mutate({ action: "unpause" })}>Reopen the reserve</button>}
          </div>
          <p className="note">Your wallet signs two transactions: allowing the reserve to take the tokens, then the deposit.</p>
        </div>
      )}
      <ErrorLine error={act.error} />
    </>
  );
}
