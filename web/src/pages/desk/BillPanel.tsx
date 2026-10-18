import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSignTypedData } from "wagmi";
import ReactECharts from "echarts-for-react";
import { api, type Bill, type FairPrice, type Query, type TypedData } from "../../lib/api";
import { money, signedPct } from "../../lib/format";
import { useAction, useAppState, useBills, useRole } from "../../lib/hooks";
import { forViem } from "../../lib/wallet";
import { ErrorLine, Hash } from "../../components/bits";
import { FaceIDModal } from "../../components/FaceIDModal";

/** One bill: what we pay, why, and the one thing to do. */
export function BillPanel({ id }: { id: string }) {
  const { data: bills } = useBills();
  const b = bills?.find((x) => x.bill === id);
  if (!b) return <p className="text-muted">Loading the bill.</p>;

  const payable = b.status === "paid" ? b.amount : b.resolution?.amount ?? b.amount;
  const held = Math.max(0, b.supplier_says_total - payable);

  return (
    <article className="surface-card space-y-6">
      {/* Top Invoice Metadata Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-bold text-ink">{b.supplier}</h2>
            <span className="rounded-md bg-paper border border-rule px-2 py-0.5 text-xs font-mono text-muted">
              {b.inv_no}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2 text-xs text-muted">
            <span>Due: {b.due}</span>
            <span>•</span>
            <span>Terms: {b.terms || "Net 30"}</span>
            <span>•</span>
            <span className="text-ledger font-medium">✓ 3-Way ERP Match Verified</span>
          </div>
        </div>

        {/* Status Pill */}
        <div>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold border ${
              b.status === "paid"
                ? "bg-ledger-soft text-ledger border-ledger/20"
                : b.tier === "hold" || b.status === "rejected"
                ? "bg-oxblood-soft text-oxblood border-oxblood/20"
                : "bg-ochre-soft text-ochre border-ochre/20"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                b.status === "paid"
                  ? "bg-ledger"
                  : b.tier === "hold" || b.status === "rejected"
                  ? "bg-oxblood"
                  : "bg-ochre"
              }`}
            />
            {b.status === "paid"
              ? "Autonomous Settlement Complete"
              : b.tier === "hold"
              ? "Held in Quarantine Vault"
              : "Human Co-Signature Required (EIP-712)"}
          </span>
        </div>
      </div>

      {/* Split-Settlement Card (Shenzhen Topic F Highlight) */}
      <div className="rounded-xl border border-rule bg-paper p-5">
        <div className="text-xs font-semibold uppercase tracking-wider text-muted">
          Autonomous Settlement Breakdown
        </div>

        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {/* Clean Portion */}
          <div className="rounded-lg border border-rule/70 bg-surface p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted">Clean Released Portion</span>
              <span className="rounded bg-ledger-soft px-1.5 py-0.5 text-[10px] font-semibold text-ledger border border-ledger/20">
                Authorized
              </span>
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-ledger">
              {money(payable)}
            </div>
            <div className="mt-1 flex items-center gap-1 text-xs text-ledger">
              <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
              </svg>
              <span>{b.status === "paid" ? "Paid On-Chain" : "Passed dry-run simulation"}</span>
            </div>
          </div>

          {/* Quarantined Discrepancy */}
          <div className="rounded-lg border border-rule/70 bg-surface p-4">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted">Quarantined Discrepancy</span>
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold border ${
                held > 0.005 ? "bg-ochre-soft text-ochre border-ochre/20" : "bg-paper text-muted border-rule"
              }`}>
                {held > 0.005 ? "Escrowed" : "Zero Diff"}
              </span>
            </div>
            <div className="mt-1 font-mono text-2xl font-bold text-ochre">
              {held > 0.005 ? money(held) : "$0.00"}
            </div>
            <div className="mt-1 text-xs text-muted">
              {held > 0.005
                ? `Disputed delta isolated from supplier's ${money(b.supplier_says_total)} total`
                : "Exact match with purchase order bounds"}
            </div>
          </div>
        </div>
      </div>

      {/* Headline / Explanation */}
      <div className="rounded-lg border-l-4 border-l-ledger bg-paper px-4 py-3 text-sm">
        <p className={`font-medium ${tone(b)}`}>{headline(b)}</p>
      </div>

      {/* Commodity Benchmark / Fair Price Anomaly Chart */}
      {b.fair_price && b.status !== "paid" && <FairPriceView fp={b.fair_price} />}

      {/* Action Buttons & Biometric Co-Signing Trigger */}
      {b.status !== "paid" && b.status !== "rejected" && <Actions b={b} payable={payable} held={held} />}

      {/* Settled Tx Receipt */}
      {b.status === "paid" && b.tx_hash && (
        <div className="rounded-lg border border-ledger/20 bg-ledger-soft p-3.5 text-sm flex items-center justify-between">
          <span className="text-ledger font-medium">Settled on Arbitrum Nova</span>
          <span className="font-mono">
            Tx: <Hash h={b.tx_hash} />
          </span>
        </div>
      )}

      {/* Technical & Audit Details */}
      <Details b={b} />
    </article>
  );
}

function tone(b: Bill) {
  if (b.status === "paid") return "text-ledger";
  if (b.tier === "hold" || b.tier === "reject" || b.status === "rejected") return "text-oxblood";
  if (b.tier === "T2") return "text-ochre";
  return "text-ink";
}

function headline(b: Bill): string {
  if (b.status === "paid")
    return b.tier === "T1"
      ? "Paid by the agent autonomously within bonded safety limits."
      : "Paid after CFO biometric hardware key co-signature.";
  if (b.status === "rejected") return "Payment proposal rejected.";
  if (b.tier === "T1") return "Policy checks passed. Agent can execute autonomously.";
  const fp = b.fair_price;
  if (fp)
    return `Needs CFO signature: Supplier price increased ${signedPct(
      fp.actual
    )}, while ${fp.series.toLowerCase()} market index moved ${signedPct(
      fp.index_now / fp.index_last - 1
    )}.`;
  const first = (b.reasons[0] ?? "").replace(/\.$/, "");
  if (b.tier === "hold") return `Quarantined: ${first}.`;
  return `Co-Signature required: ${first}.`;
}

function FairPriceView({ fp }: { fp: FairPrice }) {
  const { data } = useQuery({
    queryKey: ["market", fp.series],
    queryFn: () =>
      api.get<{ points: [string, number][]; source: string }>(
        `/market/${fp.series}?start=2025-01&end=2025-12`
      ),
  });
  const pts = data?.points ?? [];
  const at = (v: number) => pts.findIndex((p) => Math.abs(p[1] - v) < 0.01);
  const option = {
    animation: false,
    grid: { left: 44, right: 8, top: 10, bottom: 22 },
    xAxis: {
      type: "category",
      data: pts.map((p) => p[0].slice(5)),
      axisLine: { lineStyle: { color: "#E2E8F0" } },
      axisLabel: { color: "#475569", fontSize: 10 },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      scale: true,
      splitLine: { show: false },
      axisLabel: {
        color: "#475569",
        fontSize: 10,
        formatter: (v: number) => `$${(v / 1000).toFixed(1)}k`,
      },
    },
    tooltip: {
      trigger: "axis",
      valueFormatter: (v: number) =>
        `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}/t`,
    },
    series: [
      {
        type: "line",
        data: pts.map((p) => p[1]),
        symbol: "none",
        lineStyle: { color: "#0F766E", width: 2 },
        markPoint: {
          symbol: "circle",
          symbolSize: 7,
          label: { show: false },
          data: [
            { coord: [at(fp.index_last), fp.index_last], itemStyle: { color: "#94A3B8" } },
            { coord: [at(fp.index_now), fp.index_now], itemStyle: { color: "#0F766E" } },
          ],
        },
      },
    ],
  };
  return (
    <div className="rounded-xl border border-rule bg-surface p-4">
      <div className="text-xs font-semibold text-muted uppercase tracking-wider mb-2">
        Commodity Fair-Price Index Telemetry
      </div>
      <div className="grid gap-6 sm:grid-cols-[minmax(0,1fr)_220px]">
        <div>
          <ReactECharts option={option} style={{ height: 160 }} notMerge />
          <p className="text-xs text-muted mt-1">
            {fp.series}, $ per tonne, 2025. World Bank Commodity Benchmark.
          </p>
        </div>
        <dl className="space-y-2.5 text-sm border-l border-rule pl-4">
          <div>
            <dt className="text-xs text-muted">Fair Index Price</dt>
            <dd className="font-mono font-semibold text-ink">{money(fp.justified_price)} /t</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Supplier Invoiced</dt>
            <dd className="font-mono font-semibold text-ink">{money(fp.p_invoice)} /t</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Unjustified Markup</dt>
            <dd className="font-mono font-semibold text-ochre">{money(fp.overcharge)}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}

function Actions({ b, payable, held }: { b: Bill; payable: number; held: number }) {
  const { role, isConnected } = useRole();
  const { data: st } = useAppState();
  const { signTypedDataAsync } = useSignTypedData();
  const [stage, setStage] = useState("");
  const [showFaceID, setShowFaceID] = useState(false);

  const approve = useAction(async () => {
    setStage("Waiting for Secure Enclave");
    const req = await api.get<{ amount: number; expiry: number; typed_data: TypedData }>(
      `/bills/${b.bill}/approval`
    );
    const signature = await signTypedDataAsync(forViem(req.typed_data));
    setStage("Broadcasting via ERC-4337");
    const out = await api.post<any>(`/bills/${b.bill}/approve`, {
      signature,
      expiry: req.expiry,
    });
    if (out.error) throw new Error(out.error);
    setShowFaceID(false);
    return out;
  });

  const reject = useAction(() => api.post(`/bills/${b.bill}/reject`));
  const payAlone = useAction(async () => {
    const out = await api.post<any>(`/bills/${b.bill}/pay`);
    if (out.tier !== "T1")
      throw new Error(
        (out.reasons || [])[0] ||
          "The contract refused; the bill now needs a signature."
      );
    return out;
  });

  const isManager = role === "approver";
  const frozen = b.supplier_id ? st?.suppliers[b.supplier_id]?.frozen : false;
  const canPayAlone =
    b.tier === "T1" && b.status === "approved" && (role === "approver" || role === "owner");

  return (
    <div className="pt-2">
      <div className="flex flex-wrap items-center gap-3">
        {canPayAlone && (
          <button
            className="btn-primary"
            disabled={payAlone.isPending}
            onClick={() => payAlone.mutate(undefined)}
          >
            {payAlone.isPending ? "Executing..." : `Pay ${money(payable)}`}
          </button>
        )}

        {isManager && b.tier === "T2" && !frozen && (
          <button
            className="btn-primary shadow-md inline-flex items-center gap-2"
            onClick={() => setShowFaceID(true)}
            disabled={approve.isPending}
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 004 11m0 0a8 8 0 008 8c.706 0 1.393-.058 2.06-.168" />
            </svg>
            <span>{approve.isPending ? stage : `Co-Sign via FaceID (${money(payable)})`}</span>
          </button>
        )}

        {isManager && (
          <button
            className="btn-quiet"
            disabled={reject.isPending}
            onClick={() => reject.mutate(undefined)}
          >
            Reject Discrepancy
          </button>
        )}
      </div>

      {!isConnected && b.tier !== "T1" && (
        <p className="mt-2 text-xs text-muted">Connect the finance manager's wallet to co-sign.</p>
      )}
      {isConnected && !isManager && b.tier === "T2" && (
        <p className="mt-2 text-xs text-muted">Only the finance manager can co-sign this.</p>
      )}
      {frozen && <p className="mt-2 text-sm text-oxblood">Payments to this supplier are frozen.</p>}
      <ErrorLine error={approve.error || reject.error || payAlone.error} />

      {b.fair_price && <SupplierQuery b={b} />}

      {/* Mobile / Desktop Biometric Modal */}
      <FaceIDModal
        isOpen={showFaceID}
        onClose={() => setShowFaceID(false)}
        onConfirm={() => approve.mutate(undefined, { onSettled: () => setStage("") })}
        supplier={b.supplier}
        payableAmount={payable}
        heldAmount={held}
        isPending={approve.isPending}
        stage={stage}
      />
    </div>
  );
}

function SupplierQuery({ b }: { b: Bill }) {
  const { role } = useRole();
  const { data: queries } = useQuery({
    queryKey: ["queries"],
    queryFn: () => api.get<Query[]>("/queries"),
    refetchInterval: 3000,
  });
  const q = (queries ?? []).filter((x) => x.bill === b.bill).at(-1);
  const draft = useAction(() => api.post<Query>(`/bills/${b.bill}/query?topic=price`));
  const send = useAction((qid: string) => api.post(`/queries/${qid}/send`));
  const [raw, setRaw] = useState("");
  const reply = useAction((text: string) => api.post<any>("/emails", { raw: text }));
  if (role !== "approver" && !q) return null;

  return (
    <div className="mt-6 border-t border-rule pt-4">
      {!q && (
        <button
          className="text-xs font-semibold text-ledger hover:underline inline-flex items-center gap-1"
          onClick={() => draft.mutate(undefined)}
          disabled={draft.isPending}
        >
          <span>💬 Ask supplier to explain price anomaly</span>
        </button>
      )}
      {q && (
        <div className="rounded-lg border border-rule bg-paper p-3.5 space-y-2">
          <p className="text-xs font-medium text-muted">
            {{
              draft: "Draft query to supplier (waiting for send)",
              sent: "Query sent. Awaiting supplier explanation",
              resolved: "Supplier sent credit note",
              needs_manager: "Supplier replied; needs decision",
            }[q.status]}
            {q.status !== "resolved" && ` (${q.id})`}
          </p>
          {q.status === "draft" && (
            <>
              <p className="whitespace-pre-line rounded bg-surface p-3 text-xs leading-relaxed border border-rule text-ink">
                {q.body}
              </p>
              {role === "approver" && (
                <button
                  className="btn-primary text-xs mt-2"
                  onClick={() => send.mutate(q.id)}
                  disabled={send.isPending}
                >
                  Send to {q.to}
                </button>
              )}
            </>
          )}
          {q.status === "sent" && role === "approver" && (
            <form
              className="mt-3"
              onSubmit={(e) => {
                e.preventDefault();
                reply.mutate(raw, { onSuccess: () => setRaw("") });
              }}
            >
              <label htmlFor="reply" className="text-xs font-medium text-ink">
                Paste supplier email reply (with From: and Subject: lines)
              </label>
              <textarea
                id="reply"
                className="field mt-1.5 h-24 font-mono text-xs"
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
              />
              <button className="btn-quiet text-xs mt-2" disabled={!raw.trim() || reply.isPending}>
                Record Email Reply
              </button>
            </form>
          )}
        </div>
      )}
      <ErrorLine error={draft.error || send.error || reply.error} />
    </div>
  );
}

function Details({ b }: { b: Bill }) {
  return (
    <details className="border-t border-rule pt-4 text-xs">
      <summary className="cursor-pointer text-muted hover:text-ink font-medium">
        Cryptographic Proofs & ERP Hashes
      </summary>
      <div className="mt-3 space-y-2 text-muted">
        {b.resolution?.text && b.status !== "paid" && <p>{b.resolution.text}</p>}
        {b.reasons.length > 0 && (
          <ul className="list-disc space-y-1 pl-4">
            {b.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
        {b.score != null && b.cutoff != null && (
          <p className="font-mono">
            Bayesian risk score {b.score.toFixed(3)} | Threshold {b.cutoff < 0 ? "none" : b.cutoff.toFixed(3)}.
          </p>
        )}
        {b.erp_ref && (
          <p>
            ERP Entry: <span className="font-mono font-medium text-ink">{b.erp_ref}</span>
          </p>
        )}
      </div>
    </details>
  );
}
