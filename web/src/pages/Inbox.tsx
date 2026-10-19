import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Email, type Inbox as InboxT } from "../lib/api";
import { money } from "../lib/format";
import { useAction, useCan } from "../lib/hooks";
import { Empty, ErrorLine, Modal, PageHead, Tabs, Tag, useRemembered } from "../components/ui";

export default function Inbox() {
  const [tab, setTab] = useRemembered<"in" | "out">("inbox-tab", "in");
  const { data: out } = useQuery({ queryKey: ["outbox"], queryFn: () => api.get<Email[]>("/outbox"), refetchInterval: 5000 });
  const drafts = out?.filter((e) => e.status === "draft").length ?? 0;
  return (
    <>
      <PageHead title="Inbox" sub="Bills, supplier emails and statements arrive here; the agent's own emails go out from the outbox." />
      <Tabs value={tab} onChange={setTab} items={[["in", "Incoming"], ["out", "Outbox", drafts || undefined]]} />
      {tab === "in" ? <Incoming /> : <Outbox emails={out ?? []} />}
    </>
  );
}

function Incoming() {
  const can = useCan();
  const nav = useNavigate();
  const { data } = useQuery({ queryKey: ["inbox"], queryFn: () => api.get<InboxT>("/inbox"), refetchInterval: 6000 });
  const { data: mail } = useQuery({ queryKey: ["mail"], queryFn: () => api.get<any>("/mail") });
  const [result, setResult] = useState<any>(null);
  const [paste, setPaste] = useState(false);
  const [raw, setRaw] = useState("");
  const done = (r: any) => {
    setResult(r);
    if (r?.bill && !String(r.bill).startsWith("TRY")) nav(`/bills?bill=${r.bill}`);
    return r;
  };
  const take = useAction(async (key: string) => done(await api.post<any>(`/inbox/documents/${key}`)));
  const upload = useAction(async (f: File) => done(await api.upload<any>("/documents", f)));
  const email = useAction(async (name: string) => { const r = await api.post<any>(`/inbox/emails/${encodeURIComponent(name)}`); setResult(r); return r; });
  const pasted = useAction(async () => { const r = await api.post<any>("/emails", { raw }); setResult(r); setPaste(false); setRaw(""); return r; });
  const stmt = useAction(async (name: string) => {
    const r = await api.post<any[]>(`/inbox/statements/${encodeURIComponent(name)}?supplier_id=${name.split("-")[0]}`);
    setResult({ statement: name, cases: r });
    return r;
  });
  const poll = useAction(async () => { const r = await api.post<any[]>("/mailbox/poll"); setResult({ polled: r }); return r; });
  const docs = data?.documents.filter((d) => !d.taken) ?? [];

  return (
    <>
      <div className="row">
        {can.staff && (
          <>
            <label className="btn primary">
              Upload a bill
              <input type="file" accept=".json,.pdf,image/*" hidden onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
            </label>
            <label className="btn">
              Take a photo
              <input type="file" accept="image/*" capture="environment" hidden onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
            </label>
            <button className="btn" disabled={poll.isPending} onClick={() => poll.mutate(undefined)}>{poll.isPending ? "Checking" : "Check mail"}</button>
            <button className="btn" onClick={() => setPaste(true)}>Paste an email</button>
          </>
        )}
        {mail && (
          <span className="note">
            Mailbox: {mail.incoming.kind === "imap" ? `${mail.incoming.user} (IMAP)` : "drop folder"} · outgoing: {mail.outgoing.kind === "smtp" ? mail.outgoing.host : "saved to the outbox folder"} · the agent emails on its own: {mail.auto ? "on" : "off"}
          </span>
        )}
      </div>
      {(upload.isPending || take.isPending) && <p className="row"><span className="spin" /> Reading and checking the bill</p>}
      <ErrorLine error={take.error || upload.error || email.error || stmt.error || poll.error || pasted.error} />
      {result && <ResultLine r={result} onClose={() => setResult(null)} />}

      <div className="split even">
        <div className="card">
          <div style={{ padding: "12px 14px" }}><h2>Bills waiting ({docs.length})</h2></div>
          {docs.length === 0 ? <Empty title="No bills waiting" /> : (
            <div className="tablebox">
              <table>
                <tbody>
                  {docs.map((d) => (
                    <tr key={d.key}>
                      <td>{d.supplier}<span className="s2 mono">{d.inv_no}</span></td>
                      <td className="r amt">{money(d.total)}</td>
                      <td className="r">
                        <a className="small" href={`/api/files/documents/${(d.pdf || d.file).split("/").pop()}`} target="_blank" rel="noreferrer">View</a>
                        {can.staff && <button className="btn small" style={{ marginLeft: 8 }} disabled={take.isPending} onClick={() => take.mutate(d.key)}>Process</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="stack">
          <div className="card">
            <div style={{ padding: "12px 14px" }}><h2>Emails</h2></div>
            {data?.emails.length ? (
              <table><tbody>{data.emails.map((e) => (
                <tr key={e}><td className="mono">{e}</td><td className="r">
                  <a className="small" href={`/api/files/inbox/${e}`} target="_blank" rel="noreferrer">View</a>
                  {can.staff && <button className="btn small" style={{ marginLeft: 8 }} onClick={() => email.mutate(e)}>Process</button>}
                </td></tr>))}</tbody></table>
            ) : <Empty title="No emails" />}
          </div>
          <div className="card">
            <div style={{ padding: "12px 14px" }}><h2>Supplier statements</h2></div>
            {data?.statements.length ? (
              <table><tbody>{data.statements.map((s) => (
                <tr key={s}><td className="mono">{s}</td><td className="r">
                  <a className="small" href={`/api/files/statements/${s}`} target="_blank" rel="noreferrer">View</a>
                  {can.staff && <button className="btn small" style={{ marginLeft: 8 }} onClick={() => stmt.mutate(s)}>Reconcile</button>}
                </td></tr>))}</tbody></table>
            ) : <Empty title="No statements" />}
          </div>
        </div>
      </div>
      {paste && (
        <Modal title="Paste a supplier email" onClose={() => setPaste(false)}>
          <p className="note">Include the From: and Subject: lines. A reply quoting one of our references (Q-001, OF-001) goes to that query or offer.</p>
          <textarea className="field" aria-label="Email" value={raw} onChange={(e) => setRaw(e.target.value)} placeholder={"From: Acme Accounts <accounts@acme-hk.com>\nSubject: Re: Q-001\n\nCredit note CN-7781 for USD 4,160.48 is attached."} />
          <div className="row"><button className="btn primary" disabled={!raw.trim() || pasted.isPending} onClick={() => pasted.mutate(undefined)}>Record the email</button></div>
        </Modal>
      )}
    </>
  );
}

function ResultLine({ r, onClose }: { r: any; onClose: () => void }) {
  let text = "";
  if (r.polled) text = r.polled.length ? `Read ${r.polled.length} item(s) from the mailbox.` : "No new mail.";
  else if (r.statement) text = `${r.statement}: ${r.cases.length} line(s) did not match our records; see Disputes.`;
  else if (r.supplier === null) text = `Ignored: ${r.from} is not a registered supplier's address.`;
  else if (r.offer) text = `Offer ${r.offer}: ${r.status}.`;
  else if (r.reply_to) text = `Reply to ${r.reply_to}: ${String(r.class).replace(/_/g, " ")}. ${r.resolution?.text ?? ""}`;
  else if (r.class) text = `Message from ${r.supplier}: ${String(r.class).replace(/_/g, " ")}${r.freeze ? ". Payments to this supplier are frozen and the real supplier has been warned." : "."}`;
  else if (r.tier) text = `Bill ${r.bill}: ${r.tier === "T1" ? (r.scheduled ? `cleared, paid on ${r.scheduled}` : "paid by the agent") : r.tier === "T2" ? "needs approval" : r.tier === "hold" ? "held" : "rejected"}. ${(r.reasons || [])[0] ?? ""}`;
  return (
    <div className="card pad between">
      <span>{text}</span>
      <button className="btn small" onClick={onClose}>OK</button>
    </div>
  );
}

const TEMPLATE: Record<string, string> = {
  payment_notice: "Payment notice",
  query: "Question to supplier",
  duplicate_notice: "Duplicate notice",
  bank_change_alert: "Bank-change warning",
  refund_request: "Refund request",
  early_payment_offer: "Early-payment offer",
};

function Outbox({ emails }: { emails: Email[] }) {
  const can = useCan();
  const [open, setOpen] = useState<Email | null>(null);
  const send = useAction(async (id: string) => {
    const r = await api.post<Email>(`/outbox/${id}/send`);
    if (r.status !== "sent") throw new Error(r.error || `Not sent: ${r.status}`);
    return r;
  });
  if (!emails.length) return <div className="card"><Empty title="The agent has not sent any email yet" /></div>;
  return (
    <>
      <p className="note">The agent sends payment notices, price questions, duplicate notices and bank-change warnings on its own, always to the supplier's registered address and only from fixed templates. Emails that change what we pay wait here for the finance manager.</p>
      <ErrorLine error={send.error} />
      <div className="card tablebox">
        <table>
          <thead><tr><th>Status</th><th>Kind</th><th>To</th><th>Subject</th><th>Sent by</th><th /></tr></thead>
          <tbody>
            {emails.map((e) => (
              <tr key={e.id} className="click" onClick={() => setOpen(e)}>
                <td>{e.status === "sent" ? <Tag tone="ok">Sent</Tag> : e.status === "draft" ? <Tag tone="review">Waiting</Tag> : <Tag tone="bad">{e.status}</Tag>}</td>
                <td>{TEMPLATE[e.template] ?? e.template}</td>
                <td>{e.supplier_name}<span className="s2">{e.to}</span></td>
                <td>{e.subject}</td>
                <td>{e.status === "sent" ? (e.actor === "agent" ? "Agent" : "Finance manager") : "–"}</td>
                <td onClick={(ev) => ev.stopPropagation()}>{e.status === "draft" && can.manager && <button className="btn small primary" disabled={send.isPending} onClick={() => send.mutate(e.id)}>Send</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && (
        <Modal title={open.subject} onClose={() => setOpen(null)}>
          <p className="muted small">To {open.to} · {open.status}{open.via ? ` via ${open.via}` : ""}</p>
          <pre className="pre">{open.body}</pre>
        </Modal>
      )}
    </>
  );
}
