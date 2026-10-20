import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type LogLine } from "../lib/api";
import { ACTOR, QUIET, date, describe, money, time } from "../lib/format";
import { useAction, useAppState, useCan, useSupplierName } from "../lib/hooks";
import { VerifyButton } from "../components/Verify";
import { Empty, ErrorLine, Hash, PageHead, Tabs, Tag, useRemembered } from "../components/ui";

const PEOPLE = new Set(["owner", "finance_manager", "underwriter", "arbiter"]);

export default function Activity() {
  const [tab, setTab] = useRemembered<"journal" | "close">("activity-tab", "journal");
  return (
    <>
      <PageHead title="Activity" sub="Everything the agent and people did, who did it, and the on-chain record behind it." />
      <Tabs value={tab} onChange={setTab} items={[["journal", "Journal"], ["close", "Month-end"]]} />
      {tab === "journal" ? <><PublicAnchor /><Journal /></> : <ClosePack />}
    </>
  );
}

/** The latest hourly anchor of every company's journal on the public chain, and whether ours still matches it. */
function PublicAnchor() {
  const { data } = useQuery({ queryKey: ["public-anchor"], queryFn: () => api.get<any>("/public-anchor"), refetchInterval: 60_000 });
  if (!data?.enabled) return null;
  const a = data.anchor;
  return (
    <div className="card pad between">
      <div className="stack" style={{ gap: 4 }}>
        <b>Public anchor</b>
        {!a ? (
          <span className="muted small">The first hourly anchor on {data.network} has not been written yet.</span>
        ) : !data.included ? (
          <span className="muted small">Anchor {a.period} on {a.network} was written before this company's first journal line.</span>
        ) : (
          <span className="small">
            The journal's first {data.rows} lines are sealed in anchor {a.period} on {a.network}: root <span className="mono">{a.root.slice(0, 14)}…</span>.{" "}
            {data.rows_match && data.proof_ok ? <span className="ok">The rows still produce the anchored head.</span> : <span className="bad">The rows no longer match the anchor.</span>}
          </span>
        )}
      </div>
      {data.explorer && <a className="btn small" href={data.explorer} target="_blank" rel="noreferrer">View on Basescan</a>}
    </div>
  );
}

function Journal() {
  const name = useSupplierName();
  const nav = useNavigate();
  const can = useCan();
  const [who, setWho] = useState<"all" | "agent" | "people" | "security">("all");
  const { data } = useQuery({
    queryKey: ["journal", "all", who],
    queryFn: () => api.get<LogLine[]>(`/journal?limit=400${who === "security" ? "&security=true" : ""}`),
    refetchInterval: 4000,
  });
  const anchor = useAction(() => api.post<any>("/anchor"));
  const rows = (data ?? [])
    .filter((l) => !QUIET.has(l.kind) && l.kind !== "route")
    .filter((l) => who === "all" || who === "security" || (who === "people" ? PEOPLE.has(l.actor) : !PEOPLE.has(l.actor)))
    .reverse();
  return (
    <>
      <div className="between">
        <div className="row">
          {[["all", "Everyone"], ["agent", "Agent and services"], ["people", "People"], ["security", "Security events"]].map(([k, l]) => (
            <button key={k} className="chip" aria-pressed={who === k} onClick={() => setWho(k as any)}>{l}</button>
          ))}
        </div>
        {can.staff && <button className="btn" disabled={anchor.isPending} onClick={() => anchor.mutate(undefined)}>Anchor the journal now</button>}
      </div>
      {anchor.data && <p className="ok small">Anchored {anchor.data.lines} records on-chain. <Hash h={anchor.data.tx?.tx_hash} /></p>}
      <ErrorLine error={anchor.error} />
      <div className="card tablebox">
        {rows.length === 0 ? <Empty title="Nothing yet" /> : (
          <table>
            <thead><tr><th>Time</th><th>Who</th><th>What</th><th>Bill</th><th>Transaction</th><th>Proof</th></tr></thead>
            <tbody>
              {rows.map((l) => (
                <tr key={l.index}>
                  <td className="mono muted">{time(l.ts)}</td>
                  <td>{l.security ? <Tag tone="bad">{ACTOR[l.actor] ?? l.actor}</Tag> : PEOPLE.has(l.actor) ? <b>{ACTOR[l.actor] ?? l.actor}</b> : ACTOR[l.actor] ?? l.actor}</td>
                  <td>{describe(l, name)}</td>
                  <td>{l.bill_id && !l.bill_id.startsWith("TRY") ? <button className="link mono" onClick={() => nav(`/bills?bill=${l.bill_id}`)}>{l.bill_id}</button> : null}</td>
                  <td>{l.tx_hash && <Hash h={l.tx_hash} />}</td>
                  <td>{l.anchored ? <VerifyButton index={l.index!} /> : <span className="muted small">Not anchored yet</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function ClosePack() {
  const { data: st } = useAppState();
  const [month, setMonth] = useState<string>("");
  const m = month || st?.today.slice(0, 7) || "";
  const { data: p, error } = useQuery({ queryKey: ["close", m], queryFn: () => api.get<any>(`/close?month=${m}`), enabled: !!m });
  const t = p?.payments ?? {};
  return (
    <>
      <div className="row">
        <label htmlFor="month"><b>Month</b></label>
        <input id="month" type="month" className="field" value={m} onChange={(e) => setMonth(e.target.value)} />
      </div>
      <ErrorLine error={error} />
      {p && (
        <>
          <div className="card tiles">
            <div><div className="k">Paid</div><div className="v">{money(t.all?.amount ?? 0)}</div><div className="muted small">{t.all?.count ?? 0} payments</div></div>
            <div><div className="k">By the agent</div><div className="v">{money(t.agent?.amount ?? 0)}</div><div className="muted small">{t.agent?.count ?? 0} payments</div></div>
            <div><div className="k">By the finance manager</div><div className="v">{money(t.finance_manager?.amount ?? 0)}</div><div className="muted small">{t.finance_manager?.count ?? 0} payments</div></div>
            <div><div className="k">Before the agent (ERP)</div><div className="v">{money(t.history?.amount ?? 0)}</div><div className="muted small">{t.history?.count ?? 0} payments</div></div>
          </div>
          <div className="card tiles">
            <div><div className="k">Overcharges held back</div><div className="v">{money(p.overcharges_held_usd)}</div></div>
            <div><div className="k">Duplicates rejected</div><div className="v">{money(p.duplicates_rejected_usd)}</div></div>
            <div><div className="k">Recovered from suppliers</div><div className="v">{money(p.recovered_usd)}</div></div>
            <div><div className="k">Security events</div><div className="v">{p.security_events}</div></div>
          </div>
          <div className="split even">
            <div className="card pad stack">
              <h2>Bills received ({p.bills_received})</h2>
              <dl className="dl">
                {Object.entries(p.bills as Record<string, number>).map(([k, v]) => <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{v}</dd></Fragment>)}
                <dt>Cases opened</dt><dd>{p.cases.opened} ({p.cases.open} still open)</dd>
                <dt>Emails sent by the agent</dt><dd>{p.emails_sent}</dd>
              </dl>
            </div>
            <div className="card pad stack">
              <h2>Records on-chain</h2>
              <p className={p.consistency.ok ? "ok" : "bad"}>
                {p.consistency.ok ? `Records and chain agree (${p.consistency.checked} items checked).` : `${p.consistency.mismatches.length} item(s) disagree with the chain.`}
              </p>
              {p.anchors.length ? (
                <ul className="checks">
                  {p.anchors.map((a: any) => <li key={a.day}><span className="ck ok">✓</span><span>{date(a.date)}: {a.lines} records anchored <Hash h={a.tx} /></span></li>)}
                </ul>
              ) : <p className="note">No anchors this month yet. The journal is anchored at each day's end.</p>}
            </div>
          </div>
        </>
      )}
    </>
  );
}
