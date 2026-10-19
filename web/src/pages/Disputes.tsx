import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type TypedData } from "../lib/api";
import { ACTOR, date, describe, money, time } from "../lib/format";
import { useAction, useAppState, useCan, useSupplierName } from "../lib/hooks";
import { Empty, ErrorLine, Hash, PageHead, Tag, useSignData } from "../components/ui";

interface Dispute {
  id: string;
  kind: string;
  label: string;
  status: string;
  supplier_id: string;
  supplier: string;
  created: string;
  bill: string | null;
  detail: Record<string, any>;
  receivable: { amount: number; open: number } | null;
  claim: { status: string; reserve_usd: number; loss_usd: number; paid_usd: number; recovered_usd: number; mode: string; dispute_until: number } | null;
  emails: { id: string; subject: string; status: string; template: string }[];
  timeline: { ts: number; actor: string; kind: string; detail: Record<string, any>; tx_hash: string | null }[];
}

const OPEN = new Set(["open", "sent", "needs_manager", "draft"]);
const STATUS: Record<string, string> = { open: "Open", confirmed: "Confirmed", dismissed: "Dismissed", sent: "Waiting for the supplier", needs_manager: "Needs the finance manager", resolved: "Resolved", draft: "Draft" };

export default function Disputes() {
  const { data } = useQuery({ queryKey: ["disputes"], queryFn: () => api.get<Dispute[]>("/disputes"), refetchInterval: 5000 });
  const [sel, setSel] = useState<string | null>(null);
  const [show, setShow] = useState<"open" | "all">("open");
  const rows = (data ?? []).filter((d) => show === "all" || OPEN.has(d.status));
  // Keep the case just acted on in view after it leaves the open list.
  useEffect(() => {
    if (!sel && rows[0]) setSel(rows[0].id);
  }, [sel, rows]);
  const d = (data ?? []).find((x) => x.id === sel) ?? rows[0];
  return (
    <>
      <PageHead title="Disputes" sub="Mistakes the agent found, questions to suppliers, and reserve claims, each with what happened so far." />
      <div className="row">
        <button className="chip" aria-pressed={show === "open"} onClick={() => setShow("open")}>Open</button>
        <button className="chip" aria-pressed={show === "all"} onClick={() => setShow("all")}>All</button>
      </div>
      {rows.length === 0 && !d ? (
        <div className="card"><Empty title="Nothing open">Cases open when a statement does not match, a bank-detail change arrives, or the agent asks a supplier about a price.</Empty></div>
      ) : (
        <div className="split">
          <div className="card queue">
            {rows.map((x) => (
              <button key={x.id} className="qitem" aria-selected={d?.id === x.id} onClick={() => setSel(x.id)}>
                <span className="between"><b>{x.label}</b><Tag tone={OPEN.has(x.status) ? "review" : "idle"}>{STATUS[x.status] ?? x.status}</Tag></span>
                <span className="muted small">{x.supplier} · {x.id} · {date(x.created)}</span>
              </button>
            ))}
          </div>
          <div className="card">{d && <DisputeDetail d={d} />}</div>
        </div>
      )}
    </>
  );
}

function DisputeDetail({ d }: { d: Dispute }) {
  const name = useSupplierName();
  const nav = useNavigate();
  return (
    <div className="detail">
      <div className="between">
        <div><h2>{d.label}</h2><div className="muted">{d.supplier} · {d.id}</div></div>
        <Tag tone={OPEN.has(d.status) ? "review" : "idle"}>{STATUS[d.status] ?? d.status}</Tag>
      </div>
      {d.kind === "missed_credit" && <MissedCredit d={d} />}
      {d.kind === "bank_change" && (
        <div className="proposal">
          <div>Someone asked to change the bank details for {d.supplier}. Payments to them are frozen, and the agent warned the supplier at its registered address.</div>
          <div className="row"><button className="btn" onClick={() => nav("/suppliers")}>Do the call-back in Suppliers</button></div>
        </div>
      )}
      {d.kind === "query" && (
        <div className="proposal">
          <div>The agent asked {d.supplier} about the {d.detail.topic}{d.detail.amount ? ` (${money(d.detail.amount)} over the justified price)` : ""}. When they reply, paste the email in the Inbox; a credit note lowers what we pay, nothing in a reply can raise it.</div>
          {d.bill && <div className="row"><button className="btn" onClick={() => nav(`/bills?bill=${d.bill}`)}>Open the bill</button></div>}
        </div>
      )}
      {d.emails.length > 0 && (
        <div className="sect">
          <h3>Emails</h3>
          <ul className="checks">
            {d.emails.map((e) => <li key={e.id}><span className={`ck ${e.status === "sent" ? "ok" : "wa"}`}>{e.status === "sent" ? "✓" : "•"}</span><span>{e.subject} <span className="muted">· {e.status === "draft" ? "waiting in the outbox" : e.status}</span></span></li>)}
          </ul>
        </div>
      )}
      <div className="sect">
        <h3>What happened</h3>
        <ul className="timeline">
          {d.timeline.map((l, i) => (
            <li key={i}>
              <span className="muted mono">{time(l.ts)}</span>
              <span>{ACTOR[l.actor] ?? l.actor}</span>
              <span>{describe({ ...l, plan_id: null, bill_id: d.bill, policy: null, decision: null, security: false }, name)} {l.tx_hash && <Hash h={l.tx_hash} />}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function MissedCredit({ d }: { d: Dispute }) {
  const can = useCan();
  const { data: st } = useAppState();
  const sign = useSignData();
  const [stage, setStage] = useState("");
  const x = d.detail;
  const confirm = useAction(async () => {
    setStage("Sign the amount owed back");
    const req = await api.get<{ expiry: number; receivable: TypedData; claim?: TypedData }>(`/cases/${d.id}/signing`);
    const receivable_signature = await sign(req.receivable);
    let claim_signature: string | undefined;
    if (req.claim) {
      setStage("Sign the reserve claim");
      claim_signature = await sign(req.claim);
    }
    setStage("Recording");
    const out = await api.post<any>(`/cases/${d.id}/confirm`, { receivable_signature, claim_signature, expiry: req.expiry });
    if (out.error) throw new Error(out.error);
    return out;
  });
  const payout = useAction(async () => {
    const out = await api.post<any>(`/claims/${d.bill}/execute`);
    if (!out.ok) throw new Error(out.error === "BadState" ? "The bank's dispute time is still open, or the claim is disputed." : out.error);
    return out;
  });
  const skip = useAction(() => api.post(`/demo/advance?seconds=125`));
  return (
    <>
      <div className="card tiles">
        <div><div className="k">We paid</div><div className="v">{money(x.paid)}</div><div className="muted small">{x.tier === "T1" ? "by the agent" : "after a signature"}</div></div>
        <div><div className="k">Owed, per the statement</div><div className="v">{money(x.owed)}</div></div>
        <div><div className="k">Paid too much</div><div className="v bad">{money(x.amount)}</div></div>
      </div>
      <p>The supplier's statement lists credit {x.statement_line?.ref} against invoice {x.statement_line?.against}. Our records had no such return, and we paid in full.</p>
      {d.status === "open" && (
        <div className="proposal">
          <div>Confirming records {money(x.amount)} as owed back on-chain, tightens the agent's limit for this kind of bill{st?.chain.mode !== "standard" && x.tier === "T1" ? ", files a claim on the reserve" : ""}, sends the supplier's next bills to a person, and drafts a refund request. The agent also deducts it from the supplier's next bill.</div>
          <div className="row">
            {can.manager ? (
              <button className="btn primary" disabled={confirm.isPending} onClick={() => confirm.mutate(undefined)}>{confirm.isPending ? stage : "Confirm and sign"}</button>
            ) : <span className="note">The finance manager confirms this in their wallet.</span>}
          </div>
        </div>
      )}
      {d.receivable && <p>Owed back: <b>{money(d.receivable.open)}</b> still open of {money(d.receivable.amount)}.</p>}
      {d.claim && d.claim.status !== "none" && (
        <div className="proposal">
          <div className="muted">Reserve claim ({d.claim.mode === "bonded" ? "bank-funded" : "own reserve"})</div>
          <dl className="dl">
            <dt>Status</dt><dd>{{ locked: "No claim", filed: "Filed: the bank may dispute it for a short time", disputed: "Disputed by the bank: the arbiter decides", resolved: "Decided by the arbiter", paid: "Paid to the company", released: "Released" }[d.claim.status] ?? d.claim.status}</dd>
            <dt>Claimed</dt><dd>{money(d.claim.loss_usd)}</dd>
            <dt>Paid out</dt><dd>{money(d.claim.paid_usd)}</dd>
            <dt>Recovered since</dt><dd>{money(d.claim.recovered_usd)}</dd>
          </dl>
          {(d.claim.status === "filed" || d.claim.status === "resolved") && can.staff && (
            <div className="row">
              <button className="btn primary" disabled={payout.isPending} onClick={() => payout.mutate(undefined)}>Pay out the claim</button>
              {can.owner && st?.network === "localhost" && d.claim.status === "filed" && <button className="btn" onClick={() => skip.mutate(undefined)}>Skip the dispute time (demo)</button>}
            </div>
          )}
        </div>
      )}
      <ErrorLine error={confirm.error || payout.error || skip.error} />
    </>
  );
}
