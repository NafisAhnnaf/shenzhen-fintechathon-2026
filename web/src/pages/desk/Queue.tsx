import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, type Case, type Inbox } from "../../lib/api";
import { money } from "../../lib/format";
import { useAction, useAppState, useBills } from "../../lib/hooks";
import { ErrorLine } from "../../components/bits";

/** One list: what needs a person. The inbox stays closed until asked for. */
export function Queue({ selected, onBill, onCase }: { selected: string | null; onBill: (id: string) => void; onCase: (id: string) => void }) {
  const { data: bills } = useBills();
  const { data: st } = useAppState();
  const needs = (bills ?? []).filter((b) => b.status === "held" || (b.status === "approved" && b.tier === "T2"));
  const cases = st?.open_cases ?? [];

  return (
    <aside className="space-y-8">
      <div>
        <h2 className="text-sm font-semibold">Needs you</h2>
        <ul className="mt-2">
          {needs.length === 0 && cases.length === 0 && <li className="py-2 text-sm text-muted">Nothing right now.</li>}
          {cases.map((c) => (
            <Row key={c.case_id} active={selected === c.case_id} onClick={() => onCase(c.case_id)} title={caseTitle(c)} sub={st?.suppliers[c.supplier_id]?.name ?? c.supplier_id} tone="oxblood" />
          ))}
          {needs.map((b) => (
            <Row
              key={b.bill}
              active={selected === b.bill}
              onClick={() => onBill(b.bill)}
              title={b.supplier}
              sub={b.tier === "hold" ? "Held" : "Needs your signature"}
              right={money(b.resolution?.amount ?? b.amount)}
              tone={b.tier === "hold" ? "oxblood" : "ochre"}
            />
          ))}
        </ul>
      </div>
      <InboxBox onBill={onBill} onCase={onCase} />
    </aside>
  );
}

function Row({ title, sub, right, active, onClick, tone }: { title: string; sub: string; right?: string; active: boolean; onClick: () => void; tone: "ochre" | "oxblood" }) {
  return (
    <li>
      <button
        onClick={onClick}
        className={`flex w-full items-baseline justify-between gap-3 rounded px-3 py-2.5 text-left ${active ? "bg-surface shadow-[inset_2px_0_0_#22573F]" : "hover:bg-surface"}`}
      >
        <span className="min-w-0">
          <span className="block truncate">{title}</span>
          <span className={`block text-sm ${tone === "ochre" ? "text-ochre" : "text-oxblood"}`}>{sub}</span>
        </span>
        {right && <span className="shrink-0 text-sm">{right}</span>}
      </button>
    </li>
  );
}

function InboxBox({ onBill, onCase }: { onBill: (id: string) => void; onCase: (id: string) => void }) {
  const { data } = useQuery({ queryKey: ["inbox"], queryFn: () => api.get<Inbox>("/inbox"), refetchInterval: 5000 });
  const [open, setOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useAction((f: File) => api.upload<{ bill: string }>("/documents", f));
  const take = useAction((key: string) => api.post<{ bill: string }>(`/inbox/documents/${key}`));
  const email = useAction((name: string) => api.post<any>(`/inbox/emails/${name}`));
  const statement = useAction((name: string) => api.post<Case[]>(`/inbox/statements/${encodeURIComponent(name)}?supplier_id=${name.split("-")[0]}`));
  const docs = (data?.documents ?? []).filter((d) => !d.taken);
  const count = docs.length + (data?.emails.length ?? 0) + (data?.statements.length ?? 0);

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <button className="text-sm font-semibold hover:underline" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          Inbox {count > 0 && <span className="font-normal text-muted">({count})</span>}
        </button>
        <button className="text-sm text-ledger hover:underline" onClick={() => fileRef.current?.click()}>
          {upload.isPending ? "Reading" : "Upload a bill"}
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
      {open && (
        <ul className="mt-2 max-h-[50vh] overflow-y-auto text-sm">
          {docs.map((d) => (
            <li key={d.key}>
              <button className="flex w-full justify-between gap-3 rounded px-3 py-2 text-left hover:bg-surface" disabled={take.isPending} onClick={() => take.mutate(d.key, { onSuccess: (r) => onBill(r.bill) })}>
                <span className="truncate">{d.supplier}</span>
                <span className="shrink-0 text-muted">{money(d.total)}</span>
              </button>
            </li>
          ))}
          {(data?.emails ?? []).map((n) => (
            <li key={n}>
              <button className="w-full rounded px-3 py-2 text-left text-muted hover:bg-surface" disabled={email.isPending} onClick={() => email.mutate(n)}>
                Email: {n.replace(/\.eml$/, "").replace(/_/g, " ")}
              </button>
            </li>
          ))}
          {(data?.statements ?? []).map((n) => (
            <li key={n}>
              <button
                className="w-full rounded px-3 py-2 text-left text-muted hover:bg-surface"
                disabled={statement.isPending}
                onClick={() => statement.mutate(n, { onSuccess: (cs) => cs[0] && onCase(cs[0].case_id) })}
              >
                Statement: {n.replace(/\.csv$/, "")}
              </button>
            </li>
          ))}
          {count === 0 && <li className="px-3 py-2 text-muted">Empty.</li>}
        </ul>
      )}
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
