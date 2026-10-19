import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { useState } from "react";
import { api } from "../lib/api";
import { date, money, money0, pct } from "../lib/format";
import { useAction, useCan } from "../lib/hooks";
import { ErrorLine, PageHead, Tag } from "../components/ui";
import { cssVar } from "./Risk";

interface Card {
  item: string;
  material: string;
  series: string;
  source: string;
  month: string;
  price: number;
  range_90: [number, number];
  backtest_coverage: number;
  backtest_months: number;
  need_t_per_month: number;
  unit: string;
  volatility_top10: boolean;
  cusum_fired: boolean;
  wide_range: boolean;
  signals: number;
  alert: boolean;
  buy_ahead?: any;
}

export default function Market() {
  const { data } = useQuery({ queryKey: ["market-watch"], queryFn: () => api.get<{ cards: Card[]; drafts: any[] }>("/market-watch") });
  const [sel, setSel] = useState<string | null>(null);
  const card = data?.cards.find((c) => c.item === sel) ?? data?.cards[0];
  return (
    <>
      <PageHead title="Market prices" sub="Public prices for the metals the company buys: a range for next month, an alert when a big move has become more likely, and whether to buy ahead. The agent suggests and drafts; it never buys." />
      <div className="card tablebox">
        <table>
          <thead><tr><th>Material</th><th className="r">Price now ($/t)</th><th className="r">Next month, 90% range</th><th>Signals</th><th className="r">You buy a month</th></tr></thead>
          <tbody>
            {data?.cards.map((c) => (
              <tr key={c.item} className="click" aria-selected={card?.item === c.item} onClick={() => setSel(c.item)}>
                <td>{c.material}<span className="s2">{c.series}, {c.month}</span></td>
                <td className="r amt">{money0(c.price)}</td>
                <td className="r amt">{money0(c.range_90[0])} – {money0(c.range_90[1])}</td>
                <td>{c.alert ? <Tag tone="review">Alert: {c.signals} of 3</Tag> : <Tag tone="idle">{c.signals} of 3</Tag>}</td>
                <td className="r amt">{c.need_t_per_month} t</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {card && <Detail c={card} />}
      {data?.drafts.length ? (
        <div className="card">
          <div style={{ padding: "12px 14px" }}><h2>Draft purchase orders</h2><p className="note">Drafts for a person to place in the ERP.</p></div>
          <table>
            <thead><tr><th>Draft</th><th>Material</th><th className="r">Quantity</th><th>Supplier</th><th>Option</th><th>Created</th></tr></thead>
            <tbody>{data.drafts.map((d) => (
              <tr key={d.id}><td className="mono">{d.id}</td><td>{d.material}</td><td className="r amt">{d.qty} {d.unit}</td><td>{d.supplier}</td><td>{d.option.replace("_", " ")}</td><td>{date(d.created)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      ) : null}
    </>
  );
}

function Detail({ c }: { c: Card }) {
  const { data: hist } = useQuery({ queryKey: ["series", c.series], queryFn: () => api.get<{ points: [string, number][] }>(`/market/${c.series}?start=2023-01&end=${c.month}`) });
  const [cmp, setCmp] = useState<any>(c.buy_ahead ?? null);
  const can = useCan();
  const compare = useAction(async () => setCmp(await api.get<any>(`/market-watch/${c.item}/buy-ahead`)));
  const draft = useAction((option: string) => api.post<any>("/market-watch/drafts", { item: c.item, option }));
  const ink = cssVar("--ink"), muted = cssVar("--muted"), line = cssVar("--line"), amber = cssVar("--amber");
  const pts = hist?.points ?? [];
  const next = (() => { const [y, m] = c.month.split("-").map(Number); return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`; })();
  return (
    <div className="split">
      <div className="card pad stack">
        <h2>{c.material}: {c.series} price and next month's range</h2>
        <ReactECharts style={{ height: 280 }} option={{
          grid: { left: 64, right: 16, top: 16, bottom: 28 },
          tooltip: { trigger: "axis", valueFormatter: (v: number) => (v == null ? "–" : money0(v)) },
          xAxis: { type: "category", data: [...pts.map((p) => p[0]), next], axisLabel: { color: muted }, axisLine: { lineStyle: { color: line } } },
          yAxis: { type: "value", scale: true, axisLabel: { color: muted, formatter: (v: number) => `$${(v / 1000).toFixed(1)}k` }, splitLine: { lineStyle: { color: line } } },
          series: [
            { name: "Price", type: "line", showSymbol: false, data: [...pts.map((p) => p[1]), null], lineStyle: { color: ink, width: 2 }, itemStyle: { color: ink } },
            { name: "Range low", type: "line", data: [...pts.map(() => null).slice(0, -1), c.price, c.range_90[0]], lineStyle: { color: amber, type: "dashed" }, itemStyle: { color: amber }, symbol: "circle" },
            { name: "Range high", type: "line", data: [...pts.map(() => null).slice(0, -1), c.price, c.range_90[1]], lineStyle: { color: amber, type: "dashed" }, itemStyle: { color: amber }, symbol: "circle" },
          ],
        }} />
        <p className="note">
          Range by adaptive conformal inference around "no change". Over {c.backtest_months} past months it covered the real price {pct(c.backtest_coverage)} of the time (target 90%). Source: {c.source}.
        </p>
      </div>
      <div className="card pad stack">
        <h2>Signals</h2>
        <ul className="checks">
          <li><span className={`ck ${c.volatility_top10 ? "wa" : "ok"}`}>{c.volatility_top10 ? "!" : "✓"}</span><span>Volatility {c.volatility_top10 ? "is" : "is not"} in the top 10% of its history</span></li>
          <li><span className={`ck ${c.cusum_fired ? "wa" : "ok"}`}>{c.cusum_fired ? "!" : "✓"}</span><span>{c.cusum_fired ? "A change point in returns in the last 3 months" : "No recent change point in returns"}</span></li>
          <li><span className={`ck ${c.wide_range ? "wa" : "ok"}`}>{c.wide_range ? "!" : "✓"}</span><span>The range is {c.wide_range ? "wider than 90% of" : "within"} its past widths</span></li>
        </ul>
        <p>{c.alert ? "Alert: two or more signals agree, so a large move has become more likely." : "No alert. You can still compare buying ahead."}</p>
        <div className="row"><button className="btn" disabled={compare.isPending} onClick={() => compare.mutate(undefined)}>Compare buying the next 2 months now</button></div>
        {cmp && (
          <>
            <table>
              <thead><tr><th>Option</th><th className="r">Expected cost</th><th className="r">Bad case (worst 10%)</th><th className="r">Cash now</th></tr></thead>
              <tbody>
                {Object.entries(cmp.options as Record<string, any>).map(([k, o]) => (
                  <tr key={k} aria-selected={cmp.suggestion === k}>
                    <td>{{ buy_all: "Buy all now", buy_half: "Buy half now", wait: "Wait" }[k]} {cmp.suggestion === k && <Tag tone="info">Suggested</Tag>}</td>
                    <td className="r amt">{money0(o.expected)}</td>
                    <td className="r amt">{money0(o.cvar_10)}</td>
                    <td className="r amt">{money0(o.cash_now)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="note">
              {cmp.need_t} t over {cmp.months} months, {cmp.scenarios} scenarios from past monthly moves. The suggestion has the lowest bad-case cost, keeps the expected extra cost within 1% and cash above the floor.
              {cmp.suggestion !== "wait" && ` In a bad case it saves ${money(cmp.worst_case_saving)}.`}
            </p>
            {can.staff && cmp.suggestion !== "wait" && (
              <div className="row"><button className="btn primary" disabled={draft.isPending} onClick={() => draft.mutate(cmp.suggestion)}>Draft a purchase order</button></div>
            )}
            {draft.data?.draft && <p className="ok small">Drafted {draft.data.draft.id}: {draft.data.draft.qty} {draft.data.draft.unit} from {draft.data.draft.supplier}.</p>}
          </>
        )}
        <ErrorLine error={compare.error || draft.error} />
      </div>
    </div>
  );
}

