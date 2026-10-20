import { useQuery } from "@tanstack/react-query";
import { api, type LogLine, type PreparedTx } from "../lib/api";
import { ACTOR, describe, money, time } from "../lib/format";
import { useAction, useAppState, useCan, useSupplierName } from "../lib/hooks";
import { ErrorLine, Hash, PageHead, Tag, useSendPrepared } from "../components/ui";

// The rules every action passes before it has an effect (apagent/policies.py), and the contract's own limits.
const RULES: [string, string][] = [
  ["S1", "A payee, and the recipient of any email, comes only from the supplier registry, never from a document or an email."],
  ["S2", "A payment amount must be computed from the company's records (order and receipt), never taken from supplier text."],
  ["S3", "Values from documents, emails or the market can only add scrutiny; they cannot change settings or loosen a check."],
  ["S4", "The agent cannot add a payee or change bank details. A request to do so only opens a call-back task for the owner."],
  ["S5", "Every number shown on a bill card is tagged with its source and must equal that tagged value."],
  ["S6", "Supplier text never goes into an email the agent sends; only identifiers and amounts from the document may be quoted."],
  ["S7", "Market prices can raise a flag or appear on a card, never set a payee, an amount or a quantity."],
  ["S8", "Raw supplier text never reaches the request router or the planner."],
  ["S9", "A step from a typed request that has an effect needs the person to confirm the plan preview first."],
  ["S10", "A protective action (freeze, hold, pause) triggered by supplier data may target only that supplier."],
  ["S11", "Emails come only from fixed templates; those that change what the company pays wait for the finance manager."],
];

const DECISION: Record<string, string> = { T1: "Paid alone", T2: "To a person", hold: "Held", reject: "Rejected", frozen: "Frozen", paused: "Paused" };

export default function Controls() {
  const { data: st } = useAppState();
  const can = useCan();
  const name = useSupplierName();
  const send = useSendPrepared();
  const events = useQuery({ queryKey: ["log", "security"], queryFn: () => api.get<LogLine[]>("/log?security=true&limit=200"), refetchInterval: 5000 });
  const pause = useAction(() => api.post("/pause"));
  const resume = useAction(async () => {
    const r = await api.get<{ tx: PreparedTx }>("/owner-tx/unpause");
    const hash = await send(r.tx);
    const out = await api.post<any>("/resume", { tx_hash: hash });
    if (out.error) throw new Error(out.error);
    return out;
  });
  const frozen = Object.entries(st?.suppliers ?? {}).filter(([, s]) => s.frozen);
  const paused = st?.chain.agent_paused;
  const c = st?.chain;
  const rows = [...(events.data ?? [])].reverse();
  return (
    <>
      <PageHead title="Controls" sub="The rules every payment passes, the limits on chain, refused attempts, and the switch that stops the agent." />
      <div className="split even">
        <div className="card pad stack">
          <div className="between">
            <h2>Agent</h2>
            {paused ? <Tag tone="bad">Paused</Tag> : <Tag tone="ok">Running</Tag>}
          </div>
          <p className="note">Anyone on the desk can pause the agent at once; then every bill goes to a person. Only the owner can resume it, from their wallet. The agent also pauses itself after three refused attempts in ten minutes.</p>
          <div className="row">
            {!paused && can.protect && <button className="btn danger" disabled={pause.isPending} onClick={() => pause.mutate(undefined)}>Pause the agent</button>}
            {paused && can.owner && <button className="btn primary" disabled={resume.isPending} onClick={() => resume.mutate(undefined)}>{resume.isPending ? "Waiting for your wallet" : "Resume"}</button>}
          </div>
          <ErrorLine error={pause.error || resume.error} />
        </div>
        <div className="card pad stack">
          <h2>Limits on chain</h2>
          {c && (
            <dl className="dl">
              <dt>Per bill, agent alone</dt><dd>{money(c.p_cap_usd)}</dd>
              <dt>Per day, agent alone</dt><dd>{money(c.p_day_usd)} in at most {c.p_nday} payments</dd>
              <dt>Per supplier, per week</dt><dd>{money(c.p_supweek_usd)}</dd>
              <dt>Bank reserve</dt><dd>{money(c.pool_balance_usd)} ({money(c.pool_free_usd)} free)</dd>
            </dl>
          )}
          <p className="note">The payment contract enforces these whatever the agent's software does; a hacked agent key cannot pay past them.</p>
        </div>
      </div>

      <div className="split even">
        <div className="card pad stack">
          <h2>Rules before every action</h2>
          <ul className="checks">
            {RULES.map(([k, t]) => <li key={k}><span className="ck ok">{k}</span><span>{t}</span></li>)}
          </ul>
        </div>
        <div className="card pad stack">
          <h2>Frozen payees ({frozen.length})</h2>
          {frozen.length === 0 ? <p className="muted">None.</p> : (
            <ul className="checks">{frozen.map(([id, s]) => <li key={id}><span className="ck no">✕</span><span>{s.name} <span className="muted">· unfreeze in Suppliers after a call-back</span></span></li>)}</ul>
          )}
        </div>
      </div>

      <div className="card">
        <div className="between" style={{ padding: "12px 14px" }}>
          <div>
            <h2>Security events</h2>
            <p className="note">Every refused or flagged attempt: instructions found in a document, a payee or amount from the wrong source, a bank-detail change, mail from an unknown sender, a pause.</p>
          </div>
          <span className="muted small">{rows.length} event(s)</span>
        </div>
        <div className="tablebox">
          <table>
            <thead><tr><th>When</th><th>By</th><th>What happened</th><th>Rule</th><th>Transaction</th></tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={5} className="muted">Nothing refused yet.</td></tr>}
              {rows.map((l, i) => (
                <tr key={l.index ?? i}>
                  <td className="small">{time(l.ts)}</td>
                  <td>{ACTOR[l.actor] ?? l.actor}</td>
                  <td>{describe(l, name)}{l.bill_id && <span className="muted small"> · {l.bill_id}</span>}</td>
                  <td>{l.policy ? <Tag tone="bad">{l.policy}</Tag> : l.decision ? <Tag tone="review">{DECISION[l.decision] ?? l.decision}</Tag> : null}</td>
                  <td><Hash h={l.tx_hash} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
