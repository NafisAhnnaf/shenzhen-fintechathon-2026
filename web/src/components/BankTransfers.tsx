import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { date, money } from "../lib/format";
import { useAction, useAppState, useCan, useSupplierName } from "../lib/hooks";
import { Empty, ErrorLine, Money, Tag } from "./ui";

interface Transfer { bill: string; amount: number; creditor: string; account: string; supplier: string; reference: string; paid_on: string | null }
interface BankFiles {
  account: string;
  ready: Transfer[];
  files: { id: string; created: string; by: string; count: number; total: number; sha256: string; bills: string[] }[];
  confirmed: Record<string, { booked: string; bank_ref: string; amount: number }>;
  outstanding: Transfer[];
  outside: { amount: number; booked: string; counterparty: string; supplier: string | null; remittance: string }[];
}

/** Payments › Bank transfers: approved transfers go into an ISO 20022 file for the bank; the bank's statement
 * confirms them, and any debit nobody approved is flagged. */
export default function BankTransfers() {
  const can = useCan();
  const name = useSupplierName();
  const { data: st } = useAppState();
  const { data, error } = useQuery({ queryKey: ["bank-files"], queryFn: () => api.get<BankFiles>("/bank-files"), refetchInterval: 6000 });
  const [msg, setMsg] = useState("");
  const make = useAction(async () => {
    const r = await api.post<{ id: string; count: number; total: number }>("/bank-files");
    setMsg(`Payment file ${r.id}: ${r.count} transfer(s), ${money(r.total)}. Download it and upload it to the bank portal.`);
    window.location.assign(`/api/bank-files/${r.id}.xml`);
  });
  const report = (r: any) =>
    setMsg(`Statement read: ${r.matched.length} payment(s) confirmed, ${r.outside.length} debit(s) outside the desk, ${r.outstanding.length} still waiting.`);
  const upload = useAction(async (f: File) => report(await api.upload<any>("/bank-statements", f)));
  const demo = useAction(async ({ id, outside }: { id: string; outside: boolean }) => report(await api.post<any>(`/demo/bank-statement/${id}?outside=${outside}`)));
  const local = st?.network === "localhost" || st?.network === "fisco";
  if (!data) return <ErrorLine error={error} />;
  return (
    <div className="stack">
      {msg && <div className="card pad between"><span>{msg}</span><button className="btn small" onClick={() => setMsg("")}>OK</button></div>}
      {data.outside.length > 0 && (
        <div className="banner bad">
          {data.outside.length} debit(s) left the bank account without an approval in the desk. See below; the owner has been alerted.
        </div>
      )}
      <div className="split even">
        <div className="card pad stack">
          <div className="between">
            <h2>Waiting for a payment file ({data.ready.length})</h2>
            {can.staff && <button className="btn primary" disabled={!data.ready.length || make.isPending} onClick={() => make.mutate(undefined)}>Make payment file</button>}
          </div>
          <p className="note">
            Bills to suppliers paid by bank transfer are approved and recorded on chain like the rest; the money goes from {data.account} by
            bank transfer. The file is ISO 20022 pain.001, which bank portals accept for bulk payments.
          </p>
          {data.ready.length === 0 ? <p className="muted">Nothing waiting.</p> : (
            <table>
              <tbody>
                {data.ready.map((t) => (
                  <tr key={t.bill}><td>{name(t.supplier)}<div className="muted small mono">{t.account}</div></td><td className="mono small">{t.bill}</td><td className="r"><Money v={t.amount} /></td></tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card pad stack">
          <h2>Bank statement</h2>
          <p className="note">Import the bank's end-of-day statement (camt.053). Each debit is matched to a payment the desk approved, by our reference or by amount and supplier.</p>
          {can.intake && (
            <label className="btn" style={{ justifySelf: "start" }}>
              Import statement (.xml)
              <input type="file" accept=".xml,application/xml,text/xml" hidden onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
            </label>
          )}
          <dl className="dl">
            <dt>Confirmed by the bank</dt><dd>{Object.keys(data.confirmed).length}</dd>
            <dt>Sent, not yet on a statement</dt><dd>{data.outstanding.length}</dd>
            <dt>Debits outside the desk</dt><dd className={data.outside.length ? "bad" : ""}>{data.outside.length}</dd>
          </dl>
        </div>
      </div>

      <div className="card">
        <div style={{ padding: "12px 14px" }}><h2>Payment files</h2></div>
        {data.files.length === 0 ? <Empty title="No payment files yet" /> : (
          <div className="tablebox">
            <table>
              <thead><tr><th>File</th><th>Made</th><th className="r">Transfers</th><th className="r">Total</th><th>Bank</th><th /></tr></thead>
              <tbody>
                {data.files.map((f) => {
                  const booked = f.bills.filter((b) => data.confirmed[b]).length;
                  return (
                    <tr key={f.id}>
                      <td className="mono">{f.id}<div className="muted small mono" title={f.sha256}>sha256 {f.sha256.slice(0, 12)}…</div></td>
                      <td>{date(f.created)}</td>
                      <td className="r">{f.count}</td>
                      <td className="r"><Money v={f.total} /></td>
                      <td>{booked === f.count ? <Tag tone="ok">All booked</Tag> : booked ? <Tag tone="review">{booked} of {f.count} booked</Tag> : <Tag tone="idle">Not on a statement yet</Tag>}</td>
                      <td className="row" style={{ justifyContent: "flex-end" }}>
                        {can.staff && <a className="btn small" href={`/api/bank-files/${f.id}.xml`}>Download</a>}
                        {local && can.owner && booked < f.count && (
                          <>
                            <button className="btn small" disabled={demo.isPending} onClick={() => demo.mutate({ id: f.id, outside: false })}>Demo bank: book it</button>
                            <button className="btn small" disabled={demo.isPending} onClick={() => demo.mutate({ id: f.id, outside: true })}>…with an unapproved debit</button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {data.outside.length > 0 && (
        <div className="card">
          <div style={{ padding: "12px 14px" }}><h2>Debits outside the desk</h2><p className="note">Money that left the account with no approval here. Check with the bank and whoever has portal access.</p></div>
          <table>
            <thead><tr><th>Booked</th><th>To</th><th className="r">Amount</th><th>Bank's description</th></tr></thead>
            <tbody>
              {data.outside.map((o, i) => (
                <tr key={i}><td>{date(o.booked)}</td><td>{o.supplier ? name(o.supplier) : o.counterparty}</td><td className="r bad"><Money v={o.amount} /></td><td className="muted">{o.remittance}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorLine error={make.error || upload.error || demo.error} />
    </div>
  );
}
