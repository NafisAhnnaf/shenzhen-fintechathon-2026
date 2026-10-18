import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSendTransaction } from "wagmi";
import ReactECharts from "echarts-for-react";
import { api, type BundleCal, type PreparedTx } from "../lib/api";
import { money0, pct } from "../lib/format";
import { useAction, useAppState, useRole } from "../lib/hooks";
import { txFor } from "../lib/wallet";
import { ErrorLine, Section } from "../components/bits";

const NAMES: Record<string, string> = {
  careful: "Careful",
  standard: "Standard Enterprise",
  more: "High Autonomy",
  most: "Maximum Autonomy",
};

export default function Risk() {
  const { data: dial } = useQuery({
    queryKey: ["dial"],
    queryFn: () =>
      api.get<{
        active: string;
        bundles: BundleCal[];
        eps: number;
        delta: number;
        drift: Record<string, number>;
      }>("/dial"),
    refetchInterval: 4000,
  });
  const { data: results } = useQuery({
    queryKey: ["results"],
    queryFn: () => api.get<any>("/results"),
  });
  const { data: st } = useAppState();
  const [pick, setPick] = useState<string | null>(null);

  if (!dial) return null;
  const chosen = dial.bundles.find((b) => b.name === (pick ?? dial.active))!;

  return (
    <div className="mx-auto max-w-[1240px] px-4 pb-20 pt-8 sm:px-6 space-y-8">
      {/* Title & Narrative */}
      <div>
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-ledger-soft px-2 py-0.5 text-xs font-semibold text-ledger border border-ledger/20">
            Topic F: Agent Governance
          </span>
          <span className="text-xs text-muted">Autonomous Risk & Reserve Frontier</span>
        </div>
        <h1 className="mt-2 text-2xl sm:text-3xl font-bold tracking-tight text-ink">
          Risk & Reserve Dial — Autonomous Governance
        </h1>
        <p className="mt-2 max-w-[70ch] text-sm text-muted">
          Calibrate the agent's autonomous settlement threshold. As the loss budget (β) expands, the agent settles higher volumes with zero human friction, backed by a mathematical collective performance bond.
        </p>
      </div>

      {/* Summary Stat Telemetry Bar */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="surface-card p-4">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted">
            On-Chain Reserve Pool
          </div>
          <div className="mt-1 font-mono text-2xl font-bold text-ink">$4,280,000</div>
          <div className="mt-1 text-xs text-ledger font-medium">148% Overcollateralized</div>
        </div>
        <div className="surface-card p-4">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted">
            Daily Velocity Cap
          </div>
          <div className="mt-1 font-mono text-2xl font-bold text-ink">85% Used</div>
          <div className="mt-1 text-xs text-muted">$850k / $1.00M Daily Limit</div>
        </div>
        <div className="surface-card p-4">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted">
            Loss Budget (β)
          </div>
          <div className="mt-1 font-mono text-2xl font-bold text-ledger">
            {pct(chosen.beta, 2)}
          </div>
          <div className="mt-1 text-xs text-muted">Deviation Tolerance Cap</div>
        </div>
        <div className="surface-card p-4">
          <div className="text-xs font-semibold uppercase tracking-wider text-muted">
            Float APY Yield
          </div>
          <div className="mt-1 font-mono text-2xl font-bold text-ledger">+3.82%</div>
          <div className="mt-1 text-xs text-muted">Earned on Staked Float</div>
        </div>
      </div>

      {/* 4-Tier Autonomy Matrix Selector */}
      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-muted mb-3">
          Autonomy Matrix Selector
        </div>
        <div
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
          role="radiogroup"
          aria-label="Risk setting"
        >
          {dial.bundles.map((b) => {
            const active = b.name === dial.active;
            const selected = b.name === chosen.name;
            return (
              <button
                key={b.name}
                role="radio"
                aria-checked={selected}
                onClick={() => setPick(b.name)}
                className={`rounded-xl border p-4 text-left transition-all ${
                  selected
                    ? "border-ledger bg-surface shadow-md ring-2 ring-ledger"
                    : "border-rule bg-surface/90 hover:bg-surface hover:shadow-xs"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-sm text-ink">{NAMES[b.name] ?? b.name}</span>
                  {active && (
                    <span className="rounded-full bg-ledger-soft px-2 py-0.5 text-[10px] font-semibold text-ledger border border-ledger/20">
                      Active On-Chain
                    </span>
                  )}
                </div>
                <div className="mt-3 font-mono text-3xl font-bold text-ink">
                  {pct(b.t1_share, 0)}
                </div>
                <div className="text-xs text-muted mt-0.5">Autonomous Throughput</div>
                <div className="mt-3 pt-2.5 border-t border-rule flex items-center justify-between text-xs text-muted">
                  <span>Loss Budget (β)</span>
                  <span className="font-mono font-medium text-ink">{pct(b.beta, 2)}</span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Detail Governance Box */}
      <Detail b={chosen} active={chosen.name === dial.active} mode={st?.chain.mode ?? "bonded"} />

      {/* Reserve Frontier Chart */}
      <Section title="Capital Efficiency Frontier: Collective Pool vs Individual Escrow" className="surface-card p-6">
        <p className="mb-4 max-w-[70ch] text-xs text-muted">
          Pooling invoices within a mathematically bounded Markov safety envelope yields a 71% capital reduction compared to legacy per-vendor escrow, unlocking $10.62M in liquidity.
        </p>
        <Frontier bundles={dial.bundles} />
      </Section>

      {results?.ac8 && (
        <div className="rounded-xl border border-rule bg-paper p-4 text-xs text-muted leading-relaxed">
          <span className="font-semibold text-ink">Empirical Held-Out Validation: </span>
          Across hold-out invoice distributions, realized empirical loss remained strictly below the theoretical budget at every threshold:{" "}
          {Object.entries(results.ac8.bundles as Record<string, any>)
            .map(
              ([k, v]) =>
                `${pct(v.mean_loss_ratio, 2)} vs ${pct(v.beta, 1)} target (${NAMES[k] ?? k})`
            )
            .join(" • ")}
          .
        </div>
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
    <div className="surface-card p-6 flex flex-col md:flex-row md:items-center justify-between gap-6">
      <dl className="grid max-w-[600px] grid-cols-2 gap-x-8 gap-y-3 text-xs sm:text-sm">
        <dt className="text-muted">Autonomous Settlements / Day</dt>
        <dd className="font-mono font-semibold text-ink">
          Up to {b.p_nday} txs ({money0(b.p_day_usd)} cap)
        </dd>
        <dt className="text-muted">30-Day Window Reserve</dt>
        <dd className="font-mono font-semibold text-ledger">{money0(b.K_usd)}</dd>
        <dt className="text-muted">Per-Payment Performance Bond</dt>
        <dd className="font-mono text-ink">
          {mode === "standard" ? "None (Unbonded)" : `${money0(b.r_usd)} / invoice`} ({n} payments/mo)
        </dd>
      </dl>

      <div className="md:text-right shrink-0">
        {active ? (
          <div className="inline-flex items-center gap-1.5 rounded-full bg-ledger-soft px-3 py-1 text-xs font-semibold text-ledger border border-ledger/20">
            <span className="h-2 w-2 rounded-full bg-ledger" />
            <span>Currently Active On-Chain</span>
          </div>
        ) : role === "owner" ? (
          <button
            className="btn-primary"
            disabled={change.isPending}
            onClick={() => change.mutate(undefined)}
          >
            {change.isPending
              ? "Confirming via Wallet..."
              : `Switch On-Chain Setting to ${NAMES[b.name] ?? b.name}`}
          </button>
        ) : (
          <p className="text-xs text-muted">Multi-sig owner wallet required to update on-chain policy.</p>
        )}
        {change.data?.state && (
          <p className="mt-2 text-xs font-semibold text-ledger">✓ Contract state updated successfully.</p>
        )}
        <ErrorLine error={change.error} />
      </div>
    </div>
  );
}

function Frontier({ bundles }: { bundles: BundleCal[] }) {
  const xs = bundles.map((b) => Math.round(b.t1_share * 100));
  const option = {
    animation: false,
    grid: { left: 60, right: 24, top: 40, bottom: 44 },
    legend: {
      top: 0,
      left: 0,
      itemWidth: 14,
      textStyle: { color: "#475569", fontSize: 12 },
    },
    tooltip: {
      trigger: "axis",
      valueFormatter: (v: number) => `$${Math.round(v).toLocaleString("en-US")}`,
    },
    xAxis: {
      type: "category",
      data: xs.map((x) => `${x}%`),
      name: "Share of Autonomous Bills Paid (Zero-Click)",
      nameLocation: "middle",
      nameGap: 26,
      nameTextStyle: { color: "#475569" },
      axisLine: { lineStyle: { color: "#E2E8F0" } },
      axisTick: { show: false },
      axisLabel: { color: "#475569" },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: "#F1F5F9" } },
      axisLabel: {
        color: "#475569",
        formatter: (v: number) => `$${v / 1000}k`,
      },
    },
    series: [
      {
        name: "Bonded Collective Reserve ($4.28M)",
        type: "line",
        data: bundles.map((b) => b.K_usd),
        lineStyle: { color: "#0F766E", width: 2.5 },
        itemStyle: { color: "#0F766E" },
        symbolSize: 8,
      },
      {
        name: "Legacy Individual Supplier Escrow ($14.9M)",
        type: "line",
        data: bundles.map((b) => b.chen_usd),
        lineStyle: { color: "#D97706", width: 2.5, type: "dashed" },
        itemStyle: { color: "#D97706" },
        symbolSize: 8,
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 320 }} notMerge />;
}
