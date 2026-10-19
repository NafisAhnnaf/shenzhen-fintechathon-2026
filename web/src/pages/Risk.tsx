import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { useState } from "react";
import { api, type BundleCal, type PreparedTx } from "../lib/api";
import { money, money0, pct } from "../lib/format";
import { useAction, useAppState, useCan } from "../lib/hooks";
import { ErrorLine, PageHead, Tag, useSendPrepared } from "../components/ui";

const NAME: Record<string, string> = { careful: "Careful", standard: "Standard", more: "More", most: "Most" };

export function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

export default function Risk() {
  const { data: st } = useAppState();
  const { data: dial } = useQuery({ queryKey: ["dial"], queryFn: () => api.get<{ active: string; bundles: BundleCal[]; p_cap_usd: number; eps: number; delta: number }>("/dial") });
  const { data: res } = useQuery({ queryKey: ["results"], queryFn: () => api.get<any>("/results") });
  const can = useCan();
  const send = useSendPrepared();
  const [chosen, setChosen] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const pick = chosen ?? dial?.active ?? "standard";
  const b = dial?.bundles.find((x) => x.name === pick);
  const change = useAction(async () => {
    const r = await api.get<{ tx: PreparedTx }>(`/dial/tx?bundle=${pick}`);
    const hash = await send(r.tx);
    const out = await api.post<any>("/dial", { bundle: pick, tx_hash: hash });
    if (out.error) throw new Error(out.error);
    setMsg(out.awaiting_underwriter ? "Proposed on-chain. It takes effect when the bank approves it from its wallet." : "This setting is now active on-chain.");
    return out;
  });
  const ch = st?.chain;
  return (
    <>
      <PageHead title="Risk and reserve" sub="How much the agent may pay on its own, and the money that stands behind its mistakes." />
      {ch && (
        <div className="card tiles">
          <div><div className="k">Active setting</div><div className="v">{NAME[st!.bundle] ?? st!.bundle}</div><div className="muted small">{{ standard: "No reserve", self_reserve: "Company's own reserve", bonded: "Bank-funded reserve" }[ch.mode]}</div></div>
          <div><div className="k">Agent may pay alone</div><div className="v">{money0(ch.p_cap_usd)}</div><div className="muted small">per bill, at most {ch.p_nday} bills and {money0(ch.p_day_usd)} a day</div></div>
          <div><div className="k">Per supplier</div><div className="v">{money0(ch.p_supweek_usd)}</div><div className="muted small">in any 7 days</div></div>
          <div><div className="k">Reserve</div><div className="v">{money0(ch.pool_balance_usd)}</div><div className="muted small">{money0(ch.pool_locked_usd)} locked · {money0(ch.pool_free_usd)} free{ch.pool_owed_usd ? ` · ${money0(ch.pool_owed_usd)} owed` : ""}</div></div>
        </div>
      )}

      <div className="card">
        <div style={{ padding: "12px 14px" }}>
          <h2>Risk setting</h2>
          <p className="note">The owner picks a loss budget. Conformal risk control turns it into the risk limit per kind of bill, so the expected share of value lost on bills the agent pays alone stays under the budget.</p>
        </div>
        <div className="tablebox">
          <table>
            <thead><tr><th>Setting</th><th className="r">Loss budget</th><th className="r">Bills paid alone</th><th className="r">Daily limit</th><th className="r">Reserve needed</th><th className="r">Per payment</th><th className="r">Worst month</th><th /></tr></thead>
            <tbody>
              {dial?.bundles.map((x) => (
                <tr key={x.name} className="click" aria-selected={pick === x.name} onClick={() => setChosen(x.name)}>
                  <td><b>{NAME[x.name] ?? x.name}</b> {x.name === dial.active && <Tag tone="ok">Active</Tag>}</td>
                  <td className="r amt">{pct(x.beta)}</td>
                  <td className="r amt">{pct(x.t1_share, 0)}</td>
                  <td className="r amt">{x.p_nday} · {money0(x.p_day_usd)}</td>
                  <td className="r amt">{money0(x.K_usd)}</td>
                  <td className="r amt">{money0(x.r_usd)}</td>
                  <td className="r amt">{money0(x.max_exposure_usd)}</td>
                  <td>{pick === x.name && x.name !== dial.active && can.owner && (
                    <button className="btn small primary" disabled={change.isPending} onClick={(e) => { e.stopPropagation(); change.mutate(undefined); }}>
                      {change.isPending ? "Waiting for your wallet" : "Switch on-chain"}
                    </button>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note" style={{ padding: "8px 14px 14px" }}>
          {b && `"${NAME[b.name]}": with 99% probability (95% confidence) the claims in one 30-day window stay under ${money0(b.K_usd)}, if errors on different bills are independent. `}
          {!can.owner && "Only the owner switches the setting; in bank-funded mode the bank approves it too."}
        </p>
        {msg && <p className="ok small" style={{ padding: "0 14px 14px" }}>{msg}</p>}
        <ErrorLine error={change.error} />
      </div>

      {res?.ac8 && res?.capital && (
        <div className="split even">
          <div className="card pad stack">
            <h2>Does the loss stay under the budget?</h2>
            <p className="note">100 calibration/test splits of the simulated company's year (real World Bank metal prices).</p>
            <LossChart ac8={res.ac8} />
          </div>
          <div className="card pad stack">
            <h2>Reserve needed vs per-payment reserves</h2>
            <p className="note">Our pooled bound (betting bounds + Bernstein) against reserving each payment on its own (Chen 2026 style).</p>
            <CapitalChart capital={res.capital} />
            <p className="small">To let the agent pay half the bills alone: {money0(res.capital.capital_at_50.ours)} vs {money0(res.capital.capital_at_50.chen_style)}.</p>
          </div>
        </div>
      )}
      <Budgets />
    </>
  );
}

function LossChart({ ac8 }: { ac8: any }) {
  const names = Object.keys(ac8.bundles);
  const ink = cssVar("--ink"), muted = cssVar("--muted"), line = cssVar("--line"), grey = cssVar("--line-strong");
  return (
    <ReactECharts style={{ height: 240 }} option={{
      grid: { left: 48, right: 12, top: 28, bottom: 28 },
      legend: { top: 0, textStyle: { color: muted }, data: ["Loss budget", "Measured loss"] },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => `${v.toFixed(2)}%` },
      xAxis: { type: "category", data: names.map((n) => NAME[n] ?? n), axisLabel: { color: muted }, axisLine: { lineStyle: { color: grey } } },
      yAxis: { type: "value", axisLabel: { color: muted, formatter: "{value}%" }, splitLine: { lineStyle: { color: line } } },
      series: [
        { name: "Loss budget", type: "bar", data: names.map((n) => +(ac8.bundles[n].beta * 100).toFixed(3)), itemStyle: { color: grey } },
        { name: "Measured loss", type: "bar", data: names.map((n) => +(ac8.bundles[n].mean_loss_ratio * 100).toFixed(3)), itemStyle: { color: ink } },
      ],
    }} />
  );
}

function CapitalChart({ capital }: { capital: any }) {
  const rows = capital.bundles as any[];
  const ink = cssVar("--ink"), muted = cssVar("--muted"), line = cssVar("--line"), grey = cssVar("--line-strong");
  return (
    <ReactECharts style={{ height: 240 }} option={{
      grid: { left: 64, right: 12, top: 28, bottom: 28 },
      legend: { top: 0, textStyle: { color: muted }, data: ["Our reserve", "Per-payment reserves"] },
      tooltip: { trigger: "axis", valueFormatter: (v: number) => money0(v) },
      xAxis: { type: "category", data: rows.map((r) => NAME[r.bundle] ?? r.bundle), axisLabel: { color: muted }, axisLine: { lineStyle: { color: grey } } },
      yAxis: { type: "value", axisLabel: { color: muted, formatter: (v: number) => `$${v / 1000}k` }, splitLine: { lineStyle: { color: line } } },
      series: [
        { name: "Our reserve", type: "bar", data: rows.map((r) => r.K_usd), itemStyle: { color: ink } },
        { name: "Per-payment reserves", type: "bar", data: rows.map((r) => r.chen_usd), itemStyle: { color: grey } },
      ],
    }} />
  );
}

function Budgets() {
  const can = useCan();
  const { data } = useQuery({ queryKey: ["budgets"], queryFn: () => api.get<{ month: string; rows: { centre: string; budget: number | null; spent: number; left: number | null }[] }>("/budgets") });
  const [edit, setEdit] = useState<Record<string, string>>({});
  const save = useAction((x: { centre: string; v: string }) => api.post("/budgets", { centre: x.centre, monthly_usd: x.v === "" ? null : Number(x.v) }));
  return (
    <div className="card">
      <div style={{ padding: "12px 14px" }}>
        <h2>Monthly budgets ({data?.month})</h2>
        <p className="note">A bill that would take its cost centre over budget is not paid by the agent alone; it goes to the finance manager. No budget means no limit.</p>
      </div>
      <div className="tablebox">
        <table>
          <thead><tr><th>Cost centre</th><th className="r">Spent this month</th><th className="r">Budget</th><th style={{ width: "30%" }}>Used</th>{can.owner && <th />}</tr></thead>
          <tbody>
            {data?.rows.map((r) => {
              const used = r.budget ? Math.min(1, r.spent / r.budget) : 0;
              return (
                <tr key={r.centre}>
                  <td>{r.centre}</td>
                  <td className="r amt">{money(r.spent)}</td>
                  <td className="r">
                    {can.owner ? (
                      <input className="field right" style={{ width: 120 }} type="number" min="0" placeholder="No limit" value={edit[r.centre] ?? (r.budget ?? "")}
                        onChange={(e) => setEdit({ ...edit, [r.centre]: e.target.value })} />
                    ) : r.budget != null ? money0(r.budget) : <span className="muted">No limit</span>}
                  </td>
                  <td>{r.budget ? <div className={`bar-meter ${r.spent > r.budget ? "over" : ""}`}><span style={{ width: `${used * 100}%` }} /></div> : null}</td>
                  {can.owner && <td>{edit[r.centre] != null && <button className="btn small" onClick={() => save.mutate({ centre: r.centre, v: edit[r.centre] })}>Save</button>}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ErrorLine error={save.error} />
    </div>
  );
}
