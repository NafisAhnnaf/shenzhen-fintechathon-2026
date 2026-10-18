import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, type Case, type Inbox } from "../../lib/api";
import { money } from "../../lib/format";
import { useAction, useAppState, useBills } from "../../lib/hooks";
import { ErrorLine } from "../../components/bits";

type FilterTab = "needs" | "all" | "inbox";

/** High-density institutional triage queue. */
export function Queue({
  selected,
  onBill,
  onCase,
}: {
  selected: string | null;
  onBill: (id: string) => void;
  onCase: (id: string) => void;
}) {
  const { data: bills } = useBills();
  const { data: st } = useAppState();
  const [tab, setTab] = useState<FilterTab>("needs");

  const needs = (bills ?? []).filter(
    (b) => b.status === "held" || (b.status === "approved" && b.tier === "T2")
  );
  const cases = st?.open_cases ?? [];

  return (
    <aside className="space-y-4">
      {/* Segmented Triage Filter Header */}
      <div className="flex rounded-lg border border-rule bg-paper p-1 text-xs">
        <button
          onClick={() => setTab("needs")}
          className={`flex-1 rounded-md py-1.5 px-2 font-medium transition-all flex items-center justify-center gap-1.5 ${
            tab === "needs"
              ? "bg-surface text-ink shadow-xs"
              : "text-muted hover:text-ink"
          }`}
        >
          <span>Needs Co-Sign</span>
          {(needs.length > 0 || cases.length > 0) && (
            <span className="rounded-full bg-ochre px-1.5 py-0.2 text-[10px] font-bold text-white">
              {needs.length + cases.length}
            </span>
          )}
        </button>
        <button
          onClick={() => setTab("all")}
          className={`flex-1 rounded-md py-1.5 px-2 font-medium transition-all ${
            tab === "all"
              ? "bg-surface text-ink shadow-xs"
              : "text-muted hover:text-ink"
          }`}
        >
          All ({(bills ?? []).length})
        </button>
        <button
          onClick={() => setTab("inbox")}
          className={`flex-1 rounded-md py-1.5 px-2 font-medium transition-all ${
            tab === "inbox"
              ? "bg-surface text-ink shadow-xs"
              : "text-muted hover:text-ink"
          }`}
        >
          Inbox
        </button>
      </div>

      {/* Needs Co-Sign View */}
      {tab === "needs" && (
        <div className="space-y-2">
          {needs.length === 0 && cases.length === 0 && (
            <div className="rounded-xl border border-rule bg-surface p-6 text-center text-sm text-muted">
              No pending invoices requiring manual signature.
            </div>
          )}

          {cases.map((c) => (
            <Row
              key={c.case_id}
              active={selected === c.case_id}
              onClick={() => onCase(c.case_id)}
              title={caseTitle(c)}
              sub={st?.suppliers[c.supplier_id]?.name ?? c.supplier_id}
              tag="Discrepancy"
              tone="oxblood"
            />
          ))}

          {needs.map((b) => (
            <Row
              key={b.bill}
              active={selected === b.bill}
              onClick={() => onBill(b.bill)}
              title={b.supplier}
              sub={b.tier === "hold" ? "Held" : "Pending CFO Co-Signature"}
              right={money(b.resolution?.amount ?? b.amount)}
              tag={
                b.fair_price?.flagged
                  ? "⚠️ Price Anomaly"
                  : b.tier === "T2"
                  ? "EIP-712 Dual-Key"
                  : "Held"
              }
              tone={b.tier === "hold" ? "oxblood" : "ochre"}
            />
          ))}
        </div>
      )}

      {/* All Bills View */}
      {tab === "all" && (
        <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
          {(bills ?? []).map((b) => (
            <Row
              key={b.bill}
              active={selected === b.bill}
              onClick={() => onBill(b.bill)}
              title={b.supplier}
              sub={`Inv ${b.inv_no} • Due ${b.due}`}
              right={money(b.resolution?.amount ?? b.amount)}
              tag={
                b.status === "paid"
                  ? "Auto-Paid ✓"
                  : b.tier === "T1"
                  ? "T1 Clear"
                  : b.tier === "T2"
                  ? "Needs Co-Sign"
                  : "Held"
              }
              tone={
                b.status === "paid" || b.tier === "T1"
                  ? "ledger"
                  : b.tier === "T2"
                  ? "ochre"
                  : "oxblood"
              }
            />
          ))}
        </div>
      )}

      {/* Inbox View */}
      {tab === "inbox" && <InboxBox onBill={onBill} onCase={onCase} />}
    </aside>
  );
}

function Row({
  title,
  sub,
  right,
  tag,
  active,
  onClick,
  tone,
}: {
  title: string;
  sub: string;
  right?: string;
  tag?: string;
  active: boolean;
  onClick: () => void;
  tone: "ochre" | "oxblood" | "ledger";
}) {
  const toneClasses = {
    ochre: {
      border: "border-l-ochre",
      badge: "bg-ochre-soft text-ochre border-ochre/20",
    },
    oxblood: {
      border: "border-l-oxblood",
      badge: "bg-oxblood-soft text-oxblood border-oxblood/20",
    },
    ledger: {
      border: "border-l-ledger",
      badge: "bg-ledger-soft text-ledger border-ledger/20",
    },
  }[tone];

  return (
    <button
      onClick={onClick}
      className={`group w-full rounded-xl border border-l-4 p-3.5 text-left transition-all ${
        toneClasses.border
      } ${
        active
          ? "border-rule bg-surface shadow-md ring-1 ring-ledger"
          : "border-rule bg-surface/90 hover:bg-surface hover:shadow-xs"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold text-sm text-ink group-hover:text-ledger transition-colors">
            {title}
          </div>
          <div className="mt-0.5 text-xs text-muted truncate">{sub}</div>
        </div>
        {right && (
          <div className="font-mono text-sm font-semibold text-ink whitespace-nowrap">
            {right}
          </div>
        )}
      </div>

      {tag && (
        <div className="mt-2.5 flex items-center justify-between pt-2 border-t border-rule/50">
          <span
            className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-semibold ${toneClasses.badge}`}
          >
            {tag}
          </span>
          <span className="text-[11px] text-muted group-hover:translate-x-0.5 transition-transform">
            Review →
          </span>
        </div>
      )}
    </button>
  );
}

function InboxBox({
  onBill,
  onCase,
}: {
  onBill: (id: string) => void;
  onCase: (id: string) => void;
}) {
  const { data } = useQuery({
    queryKey: ["inbox"],
    queryFn: () => api.get<Inbox>("/inbox"),
    refetchInterval: 5000,
  });
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useAction((f: File) => api.upload<{ bill: string }>("/documents", f));
  const take = useAction((key: string) => api.post<{ bill: string }>(`/inbox/documents/${key}`));
  const email = useAction((name: string) => api.post<any>(`/inbox/emails/${name}`));
  const statement = useAction((name: string) =>
    api.post<Case[]>(
      `/inbox/statements/${encodeURIComponent(name)}?supplier_id=${name.split("-")[0]}`
    )
  );

  const docs = (data?.documents ?? []).filter((d) => !d.taken);
  const count = docs.length + (data?.emails.length ?? 0) + (data?.statements.length ?? 0);

  return (
    <div className="rounded-xl border border-rule bg-surface p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted">
          Pending Ingestion ({count})
        </span>
        <button
          className="text-xs font-semibold text-ledger hover:underline inline-flex items-center gap-1"
          onClick={() => fileRef.current?.click()}
        >
          <span>+ Upload PDF</span>
        </button>
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept=".json,.pdf,.png,.jpg,.jpeg,.webp"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload.mutate(f, { onSuccess: (r) => onBill(r.bill) });
            e.target.value = "";
          }}
        />
      </div>

      <ErrorLine error={upload.error || take.error || email.error || statement.error} />

      <ul className="divide-y divide-rule text-sm">
        {docs.map((d) => (
          <li key={d.key} className="py-2.5">
            <button
              className="flex w-full items-center justify-between text-left hover:text-ledger transition-colors"
              disabled={take.isPending}
              onClick={() => take.mutate(d.key, { onSuccess: (r) => onBill(r.bill) })}
            >
              <div className="truncate">
                <span className="block font-medium text-xs text-ink">{d.supplier}</span>
                <span className="block text-[11px] text-muted">Uploaded document</span>
              </div>
              <span className="font-mono text-xs font-semibold text-ink">{money(d.total)}</span>
            </button>
          </li>
        ))}

        {(data?.emails ?? []).map((n) => (
          <li key={n} className="py-2.5">
            <button
              className="w-full text-left text-xs text-muted hover:text-ink"
              disabled={email.isPending}
              onClick={() => email.mutate(n)}
            >
              📩 Email: {n.replace(/\.eml$/, "").replace(/_/g, " ")}
            </button>
          </li>
        ))}

        {(data?.statements ?? []).map((n) => (
          <li key={n} className="py-2.5">
            <button
              className="w-full text-left text-xs text-muted hover:text-ink"
              disabled={statement.isPending}
              onClick={() =>
                statement.mutate(n, {
                  onSuccess: (cs) => cs[0] && onCase(cs[0].case_id),
                })
              }
            >
              📊 Bank Statement: {n.replace(/\.csv$/, "")}
            </button>
          </li>
        ))}

        {count === 0 && <li className="py-4 text-center text-xs text-muted">Inbox is empty.</li>}
      </ul>
    </div>
  );
}

export function caseTitle(c: Case) {
  return (
    {
      missed_credit: `Overpaid ${money(c.detail.amount)}`,
      bank_change: "Asked to change bank details",
      unmatched_credit: "Credit with no bill",
      unmatched_charge: "Charge with no bill",
    }[c.kind] ?? c.kind.replace(/_/g, " ")
  );
}
