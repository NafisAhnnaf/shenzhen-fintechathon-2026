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
    <aside className="qcol">
      <div className="card">
        <div className="qh"><h2>Needs you</h2>{needs.length + cases.length > 0 && <span className="badge b-attn">{needs.length + cases.length}</span>}</div>
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
        className="qitem"
        aria-current={active}
      >
        <span className="min-w-0">
          <span className="block truncate">{title}</span>
          <small className={tone === "ochre" ? "text-ochre" : "text-oxblood"}>{sub}</small>
        </span>
        {right && <span className="num shrink-0">{right}</span>}
      </button>
    </li>
  );
}

function InboxBox({ onBill, onCase }: { onBill: (id: string) => void; onCase: (id: string) => void }) {
  const { data } = useQuery({ queryKey: ["inbox"], queryFn: () => api.get<Inbox>("/inbox"), refetchInterval: 5000 });
  const [open, setOpen] = useState(true);
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useAction((f: File) => api.upload<{ bill: string }>("/documents", f));
  const take = useAction((key: string) => api.post<{ bill: string }>(`/inbox/documents/${key}`));
  const email = useAction((name: string) => api.post<any>(`/inbox/emails/${name}`));
  const statement = useAction((name: string) => api.post<Case[]>(`/inbox/statements/${encodeURIComponent(name)}?supplier_id=${name.split("-")[0]}`));
  const cameraRef = useRef<HTMLInputElement>(null);
  const isPhone = typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches;
  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) upload.mutate(f, { onSuccess: (r) => onBill(r.bill) });
    e.target.value = "";
  };
  const docs = (data?.documents ?? []).filter((d) => !d.taken);
  const count = docs.length + (data?.emails.length ?? 0) + (data?.statements.length ?? 0);

  return (
    <div className="card">
      <div className="qh">
        <button className="btn-link" style={{ padding: 0, fontSize: 15, fontWeight: 800, color: "var(--ink)" }} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          Inbox {count > 0 && <span className="font-normal text-muted">({count})</span>}
        </button>
        <span className="flex gap-3">
          {isPhone && (
            <button className="btn-link" style={{ fontSize: 14 }} disabled={upload.isPending} onClick={() => cameraRef.current?.click()}>
              Take a photo
            </button>
          )}
          <button className="btn-link" style={{ fontSize: 14 }} onClick={() => fileRef.current?.click()}>
            {upload.isPending ? "Reading" : "Upload a bill"}
          </button>
        </span>
        <input ref={fileRef} type="file" className="hidden" accept=".json,.pdf,.png,.jpg,.jpeg,.webp" onChange={onFile} />
        {/* capture opens the rear camera directly on a phone */}
        <input ref={cameraRef} type="file" className="hidden" accept="image/jpeg,image/png" capture="environment" onChange={onFile} />
      </div>
      <ErrorLine error={upload.error || take.error || email.error || statement.error} />
      {open && (
        <ul className="max-h-[56vh] overflow-y-auto">
          {docs.map((d) => (
            <li key={d.key}>
              <button className="qitem" disabled={take.isPending} onClick={() => take.mutate(d.key, { onSuccess: (r) => onBill(r.bill) })}>
                <span className="min-w-0"><span className="block truncate">{d.supplier}</span><small className="text-muted" style={{ fontWeight: 600 }}>Bill {d.inv_no}</small></span>
                <span className="num shrink-0">{money(d.total)}</span>
              </button>
            </li>
          ))}
          {(data?.emails ?? []).map((n) => (
            <li key={n}>
              <button className="qitem" disabled={email.isPending} onClick={() => email.mutate(n)}>
                <span><small className="text-ledger">Email</small>{n.replace(/\.eml$/, "").replace(/_/g, " ")}</span>
              </button>
            </li>
          ))}
          {(data?.statements ?? []).map((n) => (
            <li key={n}>
              <button
                className="qitem"
                disabled={statement.isPending}
                onClick={() => statement.mutate(n, { onSuccess: (cs) => cs[0] && onCase(cs[0].case_id) })}
              >
                <span><small className="text-ledger">Statement</small>{n.replace(/\.csv$/, "")}</span>
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
