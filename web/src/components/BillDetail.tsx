import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Bill, type Email, type LogLine, type TypedData } from "../lib/api";
import { ACTOR, date, describe, money, pct, signedPct, time } from "../lib/format";
import { useAction, useAppState, useCan, useSupplierName } from "../lib/hooks";
import { ErrorLine, Hash, Modal, Money, PaidBy, StatusTag, useSignData } from "./ui";
import { VerifyButton } from "./Verify";

export function BillDetail({ id }: { id: string }) {
  const { data: b, error } = useQuery({ queryKey: ["bill", id], queryFn: () => api.get<Bill>(`/bills/${id}`), refetchInterval: 4000 });
  if (error) return <div className="detail"><ErrorLine error={error} /></div>;
  if (!b) return <div className="detail muted">Loading the bill</div>;
  return (
    <div className="detail">
      <div className="between">
        <div>
          <h2>{b.supplier}</h2>
          <div className="muted mono">{b.inv_no} · {b.bill}</div>
        </div>
        <StatusTag stage={b.stage} />
      </div>
      <dl className="dl">
        <dt>Supplier says</dt>
        <dd>
          <Money v={b.supplier_says_total} />
          {b.fx && <span className="muted"> · billed {b.fx.currency} {b.fx.total.toLocaleString("en-US", { minimumFractionDigits: 2 })} at {b.fx.rate} per USD</span>}
        </dd>
        <dt>Most we owe (records)</dt>
        <dd><Money v={b.erp_bound} /></dd>
        <dt>Invoice date</dt>
        <dd>{date(b.inv_date)}</dd>
        <dt>Due</dt>
        <dd>{date(b.due)} · {b.terms === "2/10net30" ? "2% off if paid in 10 days, else 30 days" : "30 days"}</dd>
        <dt>Order</dt>
        <dd className="mono">{b.po || "–"}</dd>
        <dt>Received as</dt>
        <dd>{b.source === "e-invoice" ? "E-invoice" : b.source === "photo" ? "Phone photo" : b.source.toUpperCase()}</dd>
        {b.score != null && (
          <>
            <dt>Risk score</dt>
            <dd>{b.score.toFixed(3)} (limit {b.cutoff != null && b.cutoff >= 0 ? b.cutoff.toFixed(3) : "none: too little history"}) · {b.group.replace(/_/g, " ")}</dd>
          </>
        )}
      </dl>
      <Actions b={b} />
      <Match b={b} />
      <Checks b={b} />
      <Market b={b} />
      <BillEmails b={b} />
      <BillJournal id={b.bill} />
    </div>
  );
}

// ------------------------------------------------------------------ what can be done now
function Actions({ b }: { b: Bill }) {
  const can = useCan();
  const sign = useSignData();
  const [stage, setStage] = useState("");
  const [edit, setEdit] = useState(false);
  const [amount, setAmount] = useState<string>("");
  const [msg, setMsg] = useState("");
  const waiting = useQuery({
    queryKey: ["approval", b.bill],
    queryFn: () => api.get<{ amount: number; expiry: number; signer_role: string; needs_owner: boolean; dual_above: number; typed_data: TypedData }>(`/bills/${b.bill}/approval`),
    enabled: b.stage === "needs_approval" && (can.owner || can.manager),
    refetchInterval: 6000,
  });
  const ownerTurn = waiting.data?.signer_role === "owner";

  const approve = useAction(async () => {
    setStage("Sign the payment in your wallet");
    const q = amount ? `?amount=${encodeURIComponent(amount)}` : "";
    const req = await api.get<{ amount: number; expiry: number; typed_data: TypedData }>(`/bills/${b.bill}/approval${q}`);
    const signature = await sign(req.typed_data);
    setStage("Paying");
    const out = await api.post<any>(`/bills/${b.bill}/approve`, { signature, expiry: req.expiry, amount: req.amount });
    if (out.error) throw new Error(out.error);
    setMsg(out.needs_owner ? `Signed. Above ${money(out.threshold)} the owner signs too; they have been notified.` : `Paid ${money(out.amount)}.`);
    setEdit(false);
    return out;
  });
  const cosign = useAction(async () => {
    setStage("Sign the payment in your wallet");
    const req = waiting.data!;
    const signature = await sign(req.typed_data);
    const out = await api.post<any>(`/bills/${b.bill}/cosign`, { signature });
    if (out.error) throw new Error(out.error);
    setMsg(`Paid ${money(out.amount)} with both signatures.`);
    return out;
  });
  const reject = useAction(async () => {
    const out = await api.post<any>(`/bills/${b.bill}/reject`);
    if (out.error) throw new Error(out.error);
    return out;
  });
  const query = useAction(async () => {
    const q = await api.post<any>(`/bills/${b.bill}/query?topic=price`);
    const out = q.status === "draft" ? await api.post<any>(`/queries/${q.id}/send`) : q;
    if (out.error) throw new Error(out.error);
    setMsg(`Query ${out.id} sent to ${out.to}.`);
    return out;
  });
  const payNow = useAction(async () => {
    const out = await api.post<any>(`/bills/${b.bill}/pay`);
    if (out.tier !== "T1") throw new Error((out.reasons || [])[0] || "The contract refused; the bill now needs a signature.");
    setMsg(`Paid ${money(out.amount)} by the agent.`);
    return out;
  });
  const offer = useAction(async () => {
    const out = await api.post<any>("/offers", { bill: b.bill });
    if (out.error) throw new Error(out.error);
    setMsg(`Offer ${out.ref} drafted: ${pct(out.pct)} off for paying now. Send it from Inbox › Outbox.`);
    return out;
  });
  const busy = approve.isPending || cosign.isPending;
  const proposed = b.resolution?.amount ?? b.amount;

  if (b.stage === "paid")
    return (
      <div className="proposal">
        <div className="muted">Payment</div>
        <div className="row">
          <PaidBy by={b.paid_by} /> paid <Money v={b.amount} /> on {date(b.paid_on)}
        </div>
        <dl className="dl">
          <dt>Transaction</dt>
          <dd><Hash h={b.tx_hash} /></dd>
          <dt>ERP record</dt>
          <dd>{b.erp_ref ?? "–"}</dd>
          {b.offsets.length > 0 && (
            <>
              <dt>Recovered</dt>
              <dd>{b.offsets.map((o) => `${money(o.amount)} for ${o.against}`).join(", ")}</dd>
            </>
          )}
        </dl>
      </div>
    );
  if (b.stage === "rejected")
    return <div className="proposal"><div className="muted">Rejected</div><div>{b.reasons[0] ?? b.resolution?.text}</div></div>;

  return (
    <div className="proposal">
      <div className="muted">{b.stage === "on_hold" ? "Why it is held" : b.stage === "scheduled" ? "Cleared by the agent" : "Agent's proposal"}</div>
      {b.stage !== "on_hold" && <div className="big">Pay {money(proposed)}</div>}
      {b.resolution?.held ? <div>Hold <b>{money(b.resolution.held)}</b></div> : null}
      <div>{b.stage === "on_hold" ? b.hold_reason ?? b.reasons[0] : b.resolution?.text}</div>
      {ownerTurn && <div className="warn">The finance manager has signed. Above {money(waiting.data?.dual_above)} the owner signs too.</div>}
      {edit && (
        <label className="lbl">
          Amount to pay (up to {money(b.erp_bound)}, what the records support)
          <input className="field" type="number" step="0.01" min="0" max={b.erp_bound} value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
      )}
      <div className="row">
        {b.stage === "needs_approval" && can.manager && !ownerTurn && (
          <button className="btn primary" disabled={busy} onClick={() => approve.mutate(undefined)}>
            {approve.isPending ? stage : edit && amount ? `Approve and sign ${money(Number(amount))}` : "Approve and sign"}
          </button>
        )}
        {b.stage === "needs_approval" && can.owner && ownerTurn && (
          <button className="btn primary" disabled={busy} onClick={() => cosign.mutate(undefined)}>
            {cosign.isPending ? stage : `Sign as owner (${money(waiting.data?.amount)})`}
          </button>
        )}
        {b.stage === "needs_approval" && can.manager && !ownerTurn && (
          <button className="btn" onClick={() => setEdit(!edit)}>{edit ? "Keep the proposal" : "Edit amount"}</button>
        )}
        {b.stage === "scheduled" && can.staff && (
          <button className="btn primary" disabled={payNow.isPending} onClick={() => payNow.mutate(undefined)}>Pay now</button>
        )}
        {(b.stage === "scheduled" || b.stage === "needs_approval") && can.staff && !b.resolution?.offer && b.terms === "net30" && (
          <button className="btn" disabled={offer.isPending} onClick={() => offer.mutate(undefined)}>Offer early payment</button>
        )}
        {b.supplier_id && b.stage !== "scheduled" && can.intake && b.queries.length === 0 && (
          <button className="btn" disabled={query.isPending} onClick={() => query.mutate(undefined)}>Ask supplier</button>
        )}
        {can.staff && (
          <button className="btn danger" disabled={reject.isPending} onClick={() => reject.mutate(undefined)}>Reject</button>
        )}
      </div>
      {!can.staff && b.stage === "needs_approval" && <p className="note">The finance manager approves this in their wallet.</p>}
      {msg && <p className="ok small">{msg}</p>}
      <ErrorLine error={approve.error || cosign.error || reject.error || query.error || payNow.error || offer.error} />
    </div>
  );
}

// ------------------------------------------------------------------ three-way match
function Match({ b }: { b: Bill }) {
  if (!b.match.length) return null;
  return (
    <div className="sect">
      <h3>Invoice vs order vs goods received</h3>
      <div className="tablebox">
        <table>
          <thead>
            <tr><th>Line</th><th className="r">Billed</th><th className="r">Ordered</th><th className="r">Received</th><th className="r">Invoice price</th><th className="r">Order price</th></tr>
          </thead>
          <tbody>
            {b.match.map((m, i) => (
              <tr key={i}>
                <td>{m.desc}<span className="s2 mono">{m.item}</span></td>
                <td className={`r amt ${m.qty_ok ? "" : "bad"}`}>{m.invoice.qty} {m.unit}</td>
                <td className="r amt">{m.order ? `${m.order.qty} ${m.unit}` : "–"}</td>
                <td className="r amt">{m.received ? `${m.received.qty} ${m.unit}` : "–"}{m.received?.billed_before ? <span className="s2">{m.received.billed_before} billed before</span> : null}</td>
                <td className={`r amt ${m.price_ok ? "" : "bad"}`}>{m.invoice.price.toLocaleString("en-US", { minimumFractionDigits: 2 })}</td>
                <td className="r amt">{m.order ? m.order.price.toLocaleString("en-US", { minimumFractionDigits: 2 }) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {b.low_confidence.length > 0 && <p className="warn small">The reader was unsure of: {b.low_confidence.join(", ")}. Check them on the document.</p>}
    </div>
  );
}

function Checks({ b }: { b: Bill }) {
  const codes = new Set(b.mismatches.map((m) => m.code));
  const passed: string[] = [];
  if (b.supplier_id && !codes.has("domain") && !codes.has("tax_id") && !codes.has("bank_change")) passed.push("Registered supplier, sender and bank details match the registry");
  if (b.po && !codes.has("no_order")) passed.push(`Matches order ${b.po}`);
  if (!codes.has("qty") && b.match.length) passed.push("Billed quantity is within what was received");
  if (!codes.has("price") && b.match.length) passed.push("Prices are within the order's tolerance");
  if (!codes.has("arith")) passed.push("Lines add up to the total");
  if (!codes.has("duplicate")) passed.push("Not a duplicate of an earlier bill");
  if (b.injection_p < 0.5) passed.push("No instructions hidden in the supplier's text");
  const other = b.reasons.filter((r) => !b.mismatches.some((m) => m.reason === r));
  return (
    <div className="sect">
      <h3>Checks</h3>
      <ul className="checks">
        {passed.map((t) => <li key={t}><span className="ck ok">✓</span><span>{t}</span></li>)}
        {b.mismatches.map((m, i) => <li key={`m${i}`}><span className="ck no">✕</span><span>{m.reason}</span></li>)}
        {b.injection_p >= 0.5 && <li><span className="ck no">✕</span><span>The supplier's text contains instructions to the system (p = {b.injection_p.toFixed(2)})</span></li>}
        {other.map((r, i) => <li key={`r${i}`}><span className="ck wa">!</span><span>{r}</span></li>)}
      </ul>
    </div>
  );
}

function Market({ b }: { b: Bill }) {
  const fp = b.fair_price;
  const hp = b.mismatches.find((m) => m.code === "price_history")?.detail;
  if (!fp && !hp) return null;
  if (hp)
    return (
      <div className="sect">
        <h3>Price check (supplier history)</h3>
        <dl className="dl">
          <dt>Last order price</dt><dd className="amt">{money(hp.p_last)}</dd>
          <dt>This bill</dt><dd className="amt">{money(hp.p_invoice)} ({signedPct(hp.actual)})</dd>
          <dt>Usual change</dt><dd>within {pct(hp.band, 0)} over {hp.purchases} orders</dd>
          <dt>Held</dt><dd className="amt">{money(hp.overcharge)}</dd>
        </dl>
      </div>
    );
  return (
    <div className="sect">
      <h3>Market check ({fp!.series}, World Bank monthly)</h3>
      <dl className="dl">
        <dt>Last price paid</dt><dd className="amt">{money(fp!.p_last)} per {b.match[0]?.unit ?? "unit"}</dd>
        <dt>This bill</dt><dd className="amt">{money(fp!.p_invoice)} ({signedPct(fp!.actual)})</dd>
        <dt>Index moved</dt><dd>{signedPct(fp!.index_now / fp!.index_last - 1)} ({fp!.index_last.toLocaleString()} → {fp!.index_now.toLocaleString()} $/t)</dd>
        <dt>Justified price</dt><dd className="amt">{money(fp!.justified_price)} ({signedPct(fp!.justified)})</dd>
        <dt>Over the market</dt><dd className="amt bad">{money(fp!.overcharge)}</dd>
      </dl>
    </div>
  );
}

function BillEmails({ b }: { b: Bill }) {
  const { data } = useQuery({ queryKey: ["outbox"], queryFn: () => api.get<Email[]>("/outbox"), refetchInterval: 6000 });
  const [open, setOpen] = useState<Email | null>(null);
  const mine = data?.filter((e) => e.bill === b.bill) ?? [];
  if (!mine.length) return null;
  return (
    <div className="sect">
      <h3>Emails</h3>
      <ul className="checks">
        {mine.map((e) => (
          <li key={e.id}>
            <span className={`ck ${e.status === "sent" ? "ok" : "wa"}`}>{e.status === "sent" ? "✓" : "•"}</span>
            <button className="link" style={{ textAlign: "left" }} onClick={() => setOpen(e)}>
              {e.subject} <span className="muted">· {e.status === "sent" ? `sent by ${e.actor === "agent" ? "the agent" : ACTOR[e.actor] ?? e.actor}` : e.status}</span>
            </button>
          </li>
        ))}
      </ul>
      {open && (
        <Modal title={open.subject} onClose={() => setOpen(null)}>
          <p className="muted small">To {open.to} · {open.status}</p>
          <pre className="pre">{open.body}</pre>
        </Modal>
      )}
    </div>
  );
}

function BillJournal({ id }: { id: string }) {
  const name = useSupplierName();
  const { data } = useQuery({ queryKey: ["journal", id], queryFn: () => api.get<LogLine[]>(`/journal?bill=${id}&limit=60`), refetchInterval: 6000 });
  if (!data?.length) return null;
  return (
    <div className="sect">
      <h3>What happened</h3>
      <ul className="timeline">
        {data.filter((l) => l.kind !== "route").map((l) => (
          <li key={l.index}>
            <span className="muted mono">{time(l.ts)}</span>
            <span>{ACTOR[l.actor] ?? l.actor}</span>
            <span className="between">
              <span className="grow">{describe(l, name)} {l.tx_hash && <Hash h={l.tx_hash} />}</span>
              <VerifyButton index={l.index!} />
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function useStateToday() {
  const { data } = useAppState();
  return data?.today ?? "2025-12-10";
}
