import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSendTransaction } from "wagmi";
import ReactECharts from "echarts-for-react";
import { api, type BundleCal, type PreparedTx } from "../lib/api";
import { money0, pct } from "../lib/format";
import { useAction, useAppState, useRole } from "../lib/hooks";
import { txFor } from "../lib/wallet";
import { ErrorLine, Section } from "../components/bits";

const NAMES: Record<string, string> = { careful: "Careful", standard: "Standard", more: "More on its own", most: "Most on its own" };

export default function Risk() {
  const { data: dial } = useQuery({ queryKey: ["dial"], queryFn: () => api.get<{ active: string; bundles: BundleCal[]; eps: number; delta: number; drift: Record<string, number> }>("/dial"), refetchInterval: 4000 });
  const { data: results } = useQuery({ queryKey: ["results"], queryFn: () => api.get<any>("/results") });
  const { data: st } = useAppState();
  const [pick, setPick] = useState<string | null>(null);
  if (!dial) return null;
  const chosen = dial.bundles.find((b) => b.name === (pick ?? dial.active))!;

  return (
    <div className="mx-auto max-w-[1100px] px-4 pb-16 pt-8 sm:px-6">
      <h1 className="text-2xl font-medium tracking-tight">How much the agent may pay on its own</h1>
      <p className="mt-2 max-w-[60ch] text-muted">
        Pick a loss budget. The agent pays more on its own as the budget grows, and a reserve covers its mistakes.
      </p>

      <div className="mt-8 grid gap-px overflow-hidden rounded border border-rule bg-rule sm:grid-cols-4" role="radiogroup" aria-label="Risk setting">
        {dial.bundles.map((b) => {
          const active = b.name === dial.active;
          const selected = b.name === chosen.name;
          return (
            <button
              key={b.name}
              role="radio"
              aria-checked={selected}
              onClick={() => setPick(b.name)}
              className={`bg-surface p-4 text-left ${selected ? "outline outline-2 -outline-offset-2 outline-ledger" : "hover:bg-paper"}`}
            >
              <div className="flex items-baseline justify-between">
                <span className="font-medium">{NAMES[b.name]}</span>
                {active && <span className="text-sm text-ledger">Active</span>}
              </div>
              <div className="mt-3 text-2xl font-medium tracking-tight">{pct(b.t1_share, 0)}</div>
              <div className="text-sm text-muted">of bills paid on its own</div>
              <div className="mt-3 text-sm">Loss budget {pct(b.beta, 1)}</div>
            </button>
          );
        })}
      </div>

      <Detail b={chosen} active={chosen.name === dial.active} mode={st?.chain.mode ?? "bonded"} />

      <Section title="Reserve needed for each setting" className="mt-12">
        <p className="mb-4 max-w-[60ch] text-sm text-muted">
          Pooling payments needs a fraction of what reserving each payment separately would.
        </p>
        <Frontier bundles={dial.bundles} />
      </Section>

      {results?.ac8 && (
        <p className="mt-6 max-w-[68ch] text-sm text-muted">
          On held-out bills the loss stayed under the budget at every setting: {Object.entries(results.ac8.bundles as Record<string, any>)
            .map(([k, v]) => `${pct(v.mean_loss_ratio, 2)} against ${pct(v.beta, 1)} (${NAMES[k].toLowerCase()})`)
            .join(", ")}
          .
        </p>
      )}
    </div>
  );
}

function Detail({ b, active, mode }: { b: BundleCal; active: boolean; mode: string }) {
  const { role } = useRole();
  const { sendTransactionAsync } = useSendTransaction();
  const change = useAction(async () => {
    const r = await api.get<{ tx: PreparedTx }>(`/dial/tx?bundle=${b.name}`);
    const hash = await sendTransactionAsync(txFor(r.tx));
    const out = await api.post<any>("/dial", { bundle: b.name, tx_hash: hash });
    if (out.error) throw new Error(out.error);
    return out;
  });
  const n = b.p_nday * 30;
  return (
    <div className="mt-6 grid gap-8 border-b border-rule pb-8 md:grid-cols-[minmax(0,1fr)_auto]">
      <dl className="grid max-w-[560px] grid-cols-2 gap-x-8 gap-y-3 text-sm">
        <dt className="text-muted">Payments on its own per day</dt>
        <dd>
          up to {b.p_nday}, {money0(b.p_day_usd)} in total
        </dd>
        <dt className="text-muted">Reserve for a 30-day window</dt>
        <dd>{money0(b.K_usd)}</dd>
        <dt className="text-muted">Locked per payment</dt>
        <dd>
          {mode === "standard" ? "none (no reserve)" : money0(b.r_usd)} ({n} payments a window)
        </dd>

      </dl>
      <div className="md:text-right">
        {active ? (
          <p className="text-sm text-ledger">This setting is active on-chain.</p>
        ) : role === "owner" ? (
          <button className="btn-primary" disabled={change.isPending} onClick={() => change.mutate(undefined)}>
            {change.isPending ? "Waiting for your wallet" : `Switch to ${NAMES[b.name].toLowerCase()}`}
          </button>
        ) : (
          <p className="text-sm text-muted">Only the owner can change this, in their wallet.</p>
        )}
        {change.data?.state && <p className="mt-2 text-sm text-ledger">Active on-chain now.</p>}
        <ErrorLine error={change.error} />
      </div>
    </div>
  );
}

function Frontier({ bundles }: { bundles: BundleCal[] }) {
  const xs = bundles.map((b) => Math.round(b.t1_share * 100));
  const option = {
    animation: false,
    grid: { left: 64, right: 24, top: 48, bottom: 44 },
    legend: { top: 0, left: 0, itemWidth: 14, textStyle: { color: "#5F6B66", fontSize: 12 } },
    tooltip: { trigger: "axis", valueFormatter: (v: number) => `$${Math.round(v).toLocaleString("en-US")}` },
    xAxis: {
      type: "category",
      data: xs.map((x) => `${x}%`),
      name: "Share of bills paid on its own",
      nameLocation: "middle",
      nameGap: 26,
      nameTextStyle: { color: "#5F6B66" },
      axisLine: { lineStyle: { color: "#DCE0DB" } },
      axisTick: { show: false },
      axisLabel: { color: "#5F6B66" },
    },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "#EEF0ED" } }, axisLabel: { color: "#5F6B66", formatter: (v: number) => `$${v / 1000}k` } },
    series: [
      { name: "Our pooled reserve", type: "line", data: bundles.map((b) => b.K_usd), lineStyle: { color: "#22573F", width: 2 }, itemStyle: { color: "#22573F" }, symbolSize: 7 },
      { name: "Reserving each payment on its own", type: "line", data: bundles.map((b) => b.chen_usd), lineStyle: { color: "#9A6A16", width: 2 }, itemStyle: { color: "#9A6A16" }, symbolSize: 7 },
    ],
  };
  return <ReactECharts option={option} style={{ height: 320 }} notMerge />;
}
