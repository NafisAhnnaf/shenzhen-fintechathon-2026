import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api } from "../lib/api";
import { ROLE, date, shortAddr } from "../lib/format";
import { useAction, useAppState, useCan } from "../lib/hooks";
import { ErrorLine, PageHead, Tag } from "../components/ui";

export default function Settings() {
  const { data: st } = useAppState();
  const can = useCan();
  const { data: mail } = useQuery({ queryKey: ["mail"], queryFn: () => api.get<any>("/mail") });
  const { data: sched } = useQuery({ queryKey: ["schedule"], queryFn: () => api.get<{ pay_timing: string }>("/schedule") });
  const [msg, setMsg] = useState("");
  const sync = useAction(async () => { const r = await api.post<any>("/erp/sync"); setMsg(r.note ?? `Read ${r.orders ?? "the"} orders from the ERP.`); return r; });
  const poll = useAction(async () => { const r = await api.post<any[]>("/mailbox/poll"); setMsg(r.length ? `Read ${r.length} item(s) from the mailbox.` : "No new mail."); return r; });
  const timing = useAction((mode: string) => api.post("/settings/pay-timing", { mode }));
  const nextDay = useAction(async () => { const r = await api.post<any>("/demo/next-day"); setMsg(`The demo date is now ${date(r.today)}. Yesterday's journal was anchored on-chain.`); return r; });
  const skip = useAction(async () => { await api.post("/demo/advance?seconds=301"); setMsg("Moved the chain clock 5 minutes: new payees are past their cool-down."); });
  const reset = useAction(async () => { await api.post("/admin/reset"); setMsg("Fresh contracts and the demo company's records are loaded."); });
  const [confirmReset, setConfirmReset] = useState(false);
  if (!st) return null;
  const local = st.network === "localhost" || st.network === "fisco";
  return (
    <>
      <PageHead title="Settings" sub="Connections, how bills are paid, who holds which key, and the demo controls." />
      {msg && <div className="card pad between"><span>{msg}</span><button className="btn small" onClick={() => setMsg("")}>OK</button></div>}
      <ErrorLine error={sync.error || poll.error || timing.error || nextDay.error || skip.error || reset.error} />
      <div className="split even">
        <div className="card pad stack">
          <h2>ERP</h2>
          <dl className="dl">
            <dt>Source</dt><dd>{st.erp.adapter === "odoo" ? `Odoo at ${st.erp.url} (${st.erp.database})` : st.erp.adapter === "csv" ? `Export files: ${st.erp.mapping}` : "Demo company file"}</dd>
            <dt>Orders</dt><dd>{st.erp.orders}</dd>
            <dt>Suppliers</dt><dd>{st.erp.suppliers}</dd>
          </dl>
          <p className="note">The agent reads the ERP before checking each bill and writes each payment back. Other ERPs: export the lists and run the mapping assistant (docs/erp-adapters.md).</p>
          {can.staff && <div className="row"><button className="btn" disabled={sync.isPending} onClick={() => sync.mutate(undefined)}>Read the ERP now</button></div>}
        </div>
        <div className="card pad stack">
          <h2>Email</h2>
          {mail && (
            <dl className="dl">
              <dt>Incoming</dt><dd>{mail.incoming.kind === "imap" ? `${mail.incoming.user} on ${mail.incoming.host}` : `Drop folder ${mail.incoming.folder}`}</dd>
              <dt>Outgoing</dt><dd>{mail.outgoing.kind === "smtp" ? `${mail.outgoing.user || "SMTP"} via ${mail.outgoing.host}` : `Saved as files in ${mail.outgoing.folder}`}</dd>
              <dt>Agent emails on its own</dt><dd>{mail.auto ? "Yes: payment notices, price questions, duplicate notices, bank-change warnings" : "No"}</dd>
            </dl>
          )}
          <p className="note">Set SMTP_* and IMAP_* in .env to use a real mailbox, and NOTIFY_WEBHOOK_URL to get alerts in WeCom, Slack or Teams.</p>
          {can.staff && <div className="row"><button className="btn" disabled={poll.isPending} onClick={() => poll.mutate(undefined)}>Check mail now</button></div>}
        </div>
      </div>

      <div className="split even">
        <div className="card pad stack">
          <h2>When cleared bills are paid</h2>
          <div className="stack">
            {[["now", "As soon as the agent clears them"], ["best_date", "On the best date: early when a discount pays off, otherwise the day before they are due"]].map(([k, l]) => (
              <label key={k} className="radio">
                <input type="radio" name="timing" checked={sched?.pay_timing === k} disabled={!can.owner || timing.isPending} onChange={() => timing.mutate(k)} /> {l}
              </label>
            ))}
          </div>
          {!can.owner && <p className="note">The owner changes this.</p>}
        </div>
        <div className="card pad stack">
          <h2>Who holds which key</h2>
          <table>
            <tbody>
              {Object.entries(st.roles).filter(([r]) => r !== "attacker").map(([r, a]) => (
                <tr key={r}>
                  <td>{ROLE[r] ?? r}</td>
                  <td className="mono">{shortAddr(a)}</td>
                  <td>{st.server_holds.includes(r) ? <Tag tone="info">Agent server</Tag> : r === "governor" ? <Tag tone="ok">Governor service</Tag> : <Tag tone="ok">Own wallet</Tag>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note">The agent key can pay only inside the contract's rules and cannot change settings, payees or the reserve.</p>
        </div>
      </div>

      <div className="card pad stack">
        <h2>Records and chain</h2>
        <p className={st.consistency.ok ? "ok" : "bad"}>
          {st.consistency.ok ? `Records and chain agree (${st.consistency.checked} items checked).` : "These items disagree with the chain:"}
        </p>
        {!st.consistency.ok && <pre className="pre">{JSON.stringify(st.consistency.mismatches, null, 1)}</pre>}
        <dl className="dl">
          {Object.entries(st.contracts).map(([k, a]) => <Fragment key={k}><dt>{k}</dt><dd className="mono">{a}</dd></Fragment>)}
        </dl>
      </div>

      {local && can.owner && (
        <div className="card pad stack">
          <h2>Demo controls</h2>
          <p className="note">Only on a local chain. The demo date is {date(st.today)}.</p>
          <div className="row">
            <button className="btn" disabled={nextDay.isPending} onClick={() => nextDay.mutate(undefined)}>Next day</button>
            <button className="btn" disabled={skip.isPending} onClick={() => skip.mutate(undefined)}>Skip the payee cool-down</button>
            {!confirmReset ? (
              <button className="btn danger" onClick={() => setConfirmReset(true)}>Start the demo again</button>
            ) : (
              <span className="row">
                <span className="bad">Redeploy the contracts and reload the demo records?</span>
                <button className="btn danger" disabled={reset.isPending} onClick={() => { reset.mutate(undefined); setConfirmReset(false); }}>Yes, start again</button>
                <button className="btn" onClick={() => setConfirmReset(false)}>Cancel</button>
              </span>
            )}
          </div>
        </div>
      )}
    </>
  );
}
