import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSignTypedData } from "wagmi";
import ReactECharts from "echarts-for-react";
import { api, type Bill, type FairPrice, type Query, type TypedData } from "../../lib/api";
import { money, signedPct } from "../../lib/format";
import { useAction, useAppState, useBills, useRole } from "../../lib/hooks";
import { forViem } from "../../lib/wallet";
import { ErrorLine, Hash } from "../../components/bits";

/** One bill: what we pay, why, and the one thing to do. Everything else sits under Details. */
export function BillPanel({ id }: { id: string }) {
  const { data: bills } = useBills();
  const b = bills?.find((x) => x.bill === id);
  if (!b) return <p className="text-muted">Loading the bill.</p>;
  const payable = b.status === "paid" ? b.amount : b.resolution?.amount ?? b.amount;
  const held = Math.max(0, b.supplier_says_total - payable);

  return (
    <article className="max-w-[720px]">
      <p className="text-muted">
        {b.supplier}, invoice {b.inv_no}, due {b.due}
      </p>
      <div className="mt-3 text-3xl font-medium tracking-tight">{money(payable)}</div>
      <p className="mt-1 text-sm text-muted">
        {b.status === "paid" ? "Paid." : "To pay."} {held > 0.005 ? `The supplier asked for ${money(b.supplier_says_total)}; ${money(held)} is held back.` : "Matches the supplier's bill."}
      </p>

      <p className={`mt-6 text-lg ${tone(b)}`}>{headline(b)}</p>

      {b.fair_price && b.status !== "paid" && <FairPriceView fp={b.fair_price} />}
      {b.status !== "paid" && b.status !== "rejected" && <Actions b={b} payable={payable} />}
      {b.status === "paid" && b.tx_hash && (
        <p className="mt-3 text-sm">
          Transaction <Hash h={b.tx_hash} />
        </p>
      )}
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
  if (b.status === "paid") return b.tier === "T1" ? "Paid by the agent on its own." : "Paid after the finance manager signed.";
  if (b.status === "rejected") return "Rejected.";
  if (b.tier === "T1") return "Checks passed. The agent can pay this on its own.";
  const fp = b.fair_price;
  if (fp) return `Needs your signature. The price is up ${signedPct(fp.actual)}, but ${fp.series.toLowerCase()} moved ${signedPct(fp.index_now / fp.index_last - 1)}.`;
  const first = (b.reasons[0] ?? "").replace(/\.$/, "");
  if (b.tier === "hold") return `Held. ${first}.`;
  return `Needs your signature. ${first}.`;
}

function FairPriceView({ fp }: { fp: FairPrice }) {
  const { data } = useQuery({
    queryKey: ["market", fp.series],
    queryFn: () => api.get<{ points: [string, number][]; source: string }>(`/market/${fp.series}?start=2025-01&end=2025-12`),
  });
  const pts = data?.points ?? [];
  const at = (v: number) => pts.findIndex((p) => Math.abs(p[1] - v) < 0.01);
  const option = {
    animation: false,
    grid: { left: 44, right: 8, top: 10, bottom: 22 },
    xAxis: { type: "category", data: pts.map((p) => p[0].slice(5)), axisLine: { lineStyle: { color: "#DCE0DB" } }, axisLabel: { color: "#8D9893", fontSize: 10 }, axisTick: { show: false } },
    yAxis: { type: "value", scale: true, splitLine: { show: false }, axisLabel: { color: "#8D9893", fontSize: 10, formatter: (v: number) => `${(v / 1000).toFixed(1)}k` } },
    tooltip: { trigger: "axis", valueFormatter: (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}/t` },
    series: [
      {
        type: "line",
        data: pts.map((p) => p[1]),
        symbol: "none",
        lineStyle: { color: "#1D2421", width: 1.5 },
        markPoint: {
          symbol: "circle",
          symbolSize: 7,
          label: { show: false },
          data: [
            { coord: [at(fp.index_last), fp.index_last], itemStyle: { color: "#8D9893" } },
            { coord: [at(fp.index_now), fp.index_now], itemStyle: { color: "#22573F" } },
          ],
        },
      },
    ],
  };
  return (
    <div className="mt-6 grid gap-6 sm:grid-cols-[minmax(0,1fr)_220px]">
      <div>
        <ReactECharts option={option} style={{ height: 150 }} notMerge />
        <p className="text-xs text-muted">{fp.series}, $ per tonne, 2025. World Bank.</p>
      </div>
      <dl className="space-y-2 text-sm">
        <div>
          <dt className="text-muted">Fair price</dt>
          <dd>{money(fp.justified_price)} a tonne</dd>
        </div>
        <div>
          <dt className="text-muted">Billed</dt>
          <dd>{money(fp.p_invoice)} a tonne</dd>
        </div>
        <div>
          <dt className="text-muted">Over the fair price</dt>
          <dd className="text-ochre">{money(fp.overcharge)}</dd>
        </div>
      </dl>
    </div>
  );
}

function Actions({ b, payable }: { b: Bill; payable: number }) {
  const { role, isConnected } = useRole();
  const { data: st } = useAppState();
  const { signTypedDataAsync } = useSignTypedData();
  const [stage, setStage] = useState("");

  const approve = useAction(async () => {
    setStage("Waiting for your wallet");
    const req = await api.get<{ amount: number; expiry: number; typed_data: TypedData }>(`/bills/${b.bill}/approval`);
    const signature = await signTypedDataAsync(forViem(req.typed_data));
    setStage("Paying");
    const out = await api.post<any>(`/bills/${b.bill}/approve`, { signature, expiry: req.expiry });
    if (out.error) throw new Error(out.error);
    return out;
  });
  const reject = useAction(() => api.post(`/bills/${b.bill}/reject`));
  const payAlone = useAction(async () => {
    const out = await api.post<any>(`/bills/${b.bill}/pay`);
    if (out.tier !== "T1") throw new Error((out.reasons || [])[0] || "The contract refused; the bill now needs a signature.");
    return out;
  });

  const isManager = role === "approver";
  const frozen = b.supplier_id ? st?.suppliers[b.supplier_id]?.frozen : false;
  const canPayAlone = b.tier === "T1" && b.status === "approved" && (role === "approver" || role === "owner");

  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center gap-3">
        {canPayAlone && (
          <button className="btn-primary" disabled={payAlone.isPending} onClick={() => payAlone.mutate(undefined)}>
            {payAlone.isPending ? "Paying" : `Pay ${money(payable)}`}
          </button>
        )}
        {isManager && b.tier === "T2" && !frozen && (
          <button className="btn-primary" disabled={approve.isPending} onClick={() => approve.mutate(undefined, { onSettled: () => setStage("") })}>
            {approve.isPending ? stage : `Sign and pay ${money(payable)}`}
          </button>
        )}
        {isManager && (
          <button className="btn-quiet" disabled={reject.isPending} onClick={() => reject.mutate(undefined)}>
            Reject
          </button>
        )}
      </div>
      {!isConnected && b.tier !== "T1" && <p className="text-sm text-muted">Connect the finance manager's wallet to sign.</p>}
      {isConnected && !isManager && b.tier === "T2" && <p className="text-sm text-muted">Only the finance manager can sign this.</p>}
      {frozen && <p className="mt-2 text-sm text-oxblood">Payments to this supplier are frozen.</p>}
      <ErrorLine error={approve.error || reject.error || payAlone.error} />
      {b.fair_price && <SupplierQuery b={b} />}
    </div>
  );
}

/** Ask the supplier, send with one tap, record their reply as it arrived. */
function SupplierQuery({ b }: { b: Bill }) {
  const { role } = useRole();
  const { data: queries } = useQuery({ queryKey: ["queries"], queryFn: () => api.get<Query[]>("/queries"), refetchInterval: 3000 });
  const q = (queries ?? []).filter((x) => x.bill === b.bill).at(-1);
  const draft = useAction(() => api.post<Query>(`/bills/${b.bill}/query?topic=price`));
  const send = useAction((qid: string) => api.post(`/queries/${qid}/send`));
  const [raw, setRaw] = useState("");
  const reply = useAction((text: string) => api.post<any>("/emails", { raw: text }));
  if (role !== "approver" && !q) return null;

  return (
    <div className="mt-8 border-t border-rule pt-5">
      {!q && (
        <button className="text-sm text-ledger hover:underline" onClick={() => draft.mutate(undefined)} disabled={draft.isPending}>
          Ask the supplier about the price
        </button>
      )}
      {q && (
        <>
          <p className="text-sm text-muted">
            {{ draft: "Query to the supplier, not sent yet", sent: "Query sent. Waiting for the supplier", resolved: "The supplier sent a credit note", needs_manager: "The supplier's reply needs your decision" }[q.status]}
            {q.status !== "resolved" && ` (${q.id})`}
          </p>
          {q.status === "draft" && (
            <>
              <p className="mt-2 max-w-[68ch] whitespace-pre-line rounded bg-paper p-4 text-sm leading-relaxed">{q.body}</p>
              {role === "approver" && (
                <button className="btn-primary mt-3" onClick={() => send.mutate(q.id)} disabled={send.isPending}>
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
              <label htmlFor="reply" className="text-sm">
                Paste their email, with the From and Subject lines
              </label>
              <textarea id="reply" className="field mt-1.5 h-28 font-mono text-xs" value={raw} onChange={(e) => setRaw(e.target.value)} />
              <button className="btn-quiet mt-2" disabled={!raw.trim() || reply.isPending}>
                Record reply
              </button>
            </form>
          )}
        </>
      )}
      <ErrorLine error={draft.error || send.error || reply.error} />
    </div>
  );
}

function Details({ b }: { b: Bill }) {
  return (
    <details className="mt-10 border-t border-rule pt-4 text-sm">
      <summary className="cursor-pointer text-muted hover:text-ink">Details</summary>
      <div className="mt-3 space-y-3">
        {b.resolution?.text && b.status !== "paid" && <p>{b.resolution.text}</p>}
        {b.reasons.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-muted">
            {b.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
        {b.score != null && b.cutoff != null && (
          <p className="text-muted">
            Risk score {b.score.toFixed(3)}; limit {b.cutoff < 0 ? "not set" : b.cutoff.toFixed(3)}.
          </p>
        )}
        <p className="text-muted">
          The amount is computed from our orders and goods receipts and can only be lowered by the bill ({money(b.erp_bound)} at most).
        </p>
        {b.erp_ref && <p>Recorded in the company's ERP as {b.erp_ref.replace(/^(\w+):/, (_, k) => (k === "odoo" ? "Odoo " : `${k} `))}.</p>}
        {b.offsets.map((o) => (
          <p key={o.against}>
            Recovered {money(o.amount)} owed from an earlier bill <Hash h={o.tx} />
          </p>
        ))}
        <Sources tags={b.tags} />
      </div>
    </details>
  );
}

const NUMBER_NAMES: Record<string, string> = {
  supplier_says_total: "Bill total",
  amount: "Amount to pay",
  erp_bound: "Most we can pay",
  score: "Risk score",
  cutoff: "Limit",
  injection_p: "Instruction-text score",
  premium: "Reserve premium",
  "resolution.amount": "Proposed payment",
  "resolution.held": "Held back",
  "resolution.credit": "Credit note",
  "fair_price.p_last": "Last price paid",
  "fair_price.p_invoice": "Price billed",
  "fair_price.justified_price": "Fair price",
  "fair_price.overcharge": "Over the fair price",
  "fair_price.index_last": "Index then",
  "fair_price.index_now": "Index now",
};

const SOURCE_NAMES: Record<string, string> = {
  "computed:erp_bounded": "our orders and receipts (the bill can only lower it)",
  erp: "our orders and receipts",
  computed: "calculated",
  settings: "settings",
};

/** Where every number on this card comes from (policy S5: an untagged number blocks the card). */
function Sources({ tags }: { tags?: Bill["tags"] }) {
  const rows = Object.entries(tags ?? {}).filter(([k]) => NUMBER_NAMES[k]);
  if (!rows.length) return null;
  return (
    <div>
      <p className="text-muted">Where each number comes from</p>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs">
        {rows.map(([k, t]) => (
          <div key={k} className="contents">
            <dt className="text-muted">{NUMBER_NAMES[k]}</dt>
            <dd>{t.label || t.sources.map((s) => SOURCE_NAMES[s] ?? s).join(" + ")}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
