import { useRef, useState } from "react";
import { useSendTransaction } from "wagmi";
import { api, type Plan, type PlanReply, type PreparedTx, type Question, type Step } from "../../lib/api";
import { money } from "../../lib/format";
import { useAction, useAppState, useRole, useSupplierName } from "../../lib/hooks";
import { txFor } from "../../lib/wallet";
import { ErrorLine, Hash } from "../../components/bits";

const STATUS: Record<Step["status"], string> = {
  planned: "Waiting",
  done: "Done",
  stopped: "Stopped",
  skipped: "Left out",
  needs_signature: "Needs a signature",
  failed: "Failed",
};

/** A plan built from a fixed template. Nothing with an effect runs before Run. Steps run one at a time so Cancel works. */
export function PlanPanel({ reply, onBill }: { reply: PlanReply; onBill: (id: string) => void }) {
  const [plan, setPlan] = useState<Plan>(reply.plan);
  const [running, setRunning] = useState(false);
  const stop = useRef(false);
  const [err, setErr] = useState<unknown>(null);
  const { role } = useRole();
  const name = useSupplierName();
  const { data: st } = useAppState();
  const { sendTransactionAsync } = useSendTransaction();
  if (plan.plan_id !== reply.plan.plan_id) setPlan(reply.plan);

  const run = async () => {
    setErr(null);
    setRunning(true);
    stop.current = false;
    try {
      while (!stop.current) {
        const r = await api.post<{ step: Step | null; plan: Plan }>(`/plans/${plan.plan_id}/step`);
        setPlan(r.plan);
        if (!r.step || r.plan.status !== "running") break;
      }
    } catch (e) {
      setErr(e);
    } finally {
      setRunning(false);
    }
  };
  const cancel = useAction(async () => {
    stop.current = true;
    const p = await api.post<Plan>(`/plans/${plan.plan_id}/cancel`);
    setPlan(p);
    return p;
  });
  const sign = useAction(async () => {
    const r = await api.get<{ tx: PreparedTx }>(`/plans/${plan.plan_id}/tx`);
    const hash = await sendTransactionAsync(txFor(r.tx));
    const out = await api.post<any>(`/plans/${plan.plan_id}/sign`, { tx_hash: hash });
    setPlan(await api.get<Plan>(`/plans/${plan.plan_id}`));
    return out;
  });

  const effects = plan.steps.filter((s) => s.status !== "skipped");
  const needsOwner = plan.steps.some((s) => (s.kind === "settings" || s.kind === "resume") && s.status === "needs_signature");
  const canRun = plan.status === "preview" && effects.some((s) => s.status === "planned");

  if (plan.answer) return <Answer plan={plan} onBill={onBill} />;

  return (
    <article>
      <h1 className="max-w-[60ch] text-xl leading-snug">{plan.summary}</h1>
      {plan.totals.count != null && plan.totals.cash_after < plan.totals.cash_floor && (
        <p className="mt-2 text-sm text-oxblood">This would take cash below the floor of {money(plan.totals.cash_floor)}.</p>
      )}

      {plan.steps.length > 0 && (
        <ol className="mt-6 divide-y divide-rule border-y border-rule">
          {plan.steps.map((s) => (
            <li key={s.n} className="flex items-baseline justify-between gap-4 py-3 text-sm">
              <div className="min-w-0">
                {s.bill ? (
                  <button className="text-left hover:underline" onClick={() => onBill(s.bill!)}>
                    {stepTitle(s, name)}
                  </button>
                ) : (
                  stepTitle(s, name)
                )}
                {s.status === "skipped" && s.reason && <div className="text-muted">{s.reason.replace(/^excluded: /, "Left out: ")}</div>}
                {s.result?.tx?.tx_hash && (
                  <div>
                    <Hash h={s.result.tx.tx_hash} />
                  </div>
                )}
              </div>
              <span className={`shrink-0 ${s.status === "done" ? "text-ledger" : s.status === "stopped" ? "text-oxblood" : s.status === "needs_signature" || (s.status === "planned" && s.tier === "T2") ? "text-ochre" : "text-muted"}`}>
                {s.status === "planned" && s.tier === "T2" ? "Needs a signature" : STATUS[s.status]}
              </span>
            </li>
          ))}
        </ol>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        {canRun && (role === "owner" || role === "approver") && (
          <button className="btn-primary" onClick={run} disabled={running}>
            {running ? "Running" : "Run"}
          </button>
        )}
        {(running || plan.status === "running") && (
          <button className="btn-danger" onClick={() => cancel.mutate(undefined)}>
            Cancel the rest
          </button>
        )}

        {needsOwner && role === "owner" && (
          <button className="btn-primary" disabled={sign.isPending} onClick={() => sign.mutate(undefined)}>
            {sign.isPending ? "Waiting for your wallet" : "Sign in wallet"}
          </button>
        )}
        {needsOwner && role !== "owner" && <p className="text-sm text-muted">The owner signs this in their wallet.</p>}
        {canRun && !(role === "owner" || role === "approver") && <p className="text-sm text-muted">Connect the owner's or the finance manager's wallet to run it.</p>}
        {plan.status === "done" && <p className="text-sm text-ledger">Done.</p>}
        {plan.status === "cancelled" && <p className="text-sm text-oxblood">Cancelled. Payments already sent stay sent.</p>}
      </div>
      {st && plan.intent === "SET_DIAL" && sign.data?.state && (
        <p className="mt-3 text-sm">
          Now active on-chain: {sign.data.state.p_nday} payments and {money(sign.data.state.p_day_usd)} a day on its own, reserve{" "}
          {money(sign.data.state.r_usd)} per payment.
        </p>
      )}
      <ErrorLine error={err || cancel.error || sign.error} />
    </article>
  );
}

function stepTitle(s: Step, name: (id?: string | null) => string) {
  switch (s.kind) {
    case "pay":
      return `Pay ${name(s.supplier)} ${money(s.amount)}`;
    case "skip":
      return `${name(s.supplier)} ${money(s.amount)}`;
    case "hold":
      return `Hold ${name(s.supplier)} ${money(s.amount)}`;
    case "release":
      return `Release ${name(s.supplier)} ${money(s.amount)}`;
    case "query":
      return `Query ${name(s.supplier)}`;
    case "probation":
      return `Send ${name(s.supplier)}'s next bills to a person`;
    case "settings":
      return "Change the risk setting on-chain";
    case "pause":
      return "Pause the agent on-chain";
    case "resume":
      return "Resume the agent on-chain";
    default:
      return s.kind;
  }
}

function Answer({ plan, onBill }: { plan: Plan; onBill: (id: string) => void }) {
  const a = plan.answer!;
  const bills = (a.bills ?? (a.card ? [a.card] : [])) as any[];
  return (
    <article>
      <p className="max-w-[65ch] text-xl leading-snug">{a.text}</p>
      {a.schedule && (
        <p className="mt-2 text-sm text-muted">
          {a.below_floor ? "This would take cash below the floor." : "Cash stays above the floor."}
        </p>
      )}
      {bills.length > 0 && (
        <ul className="mt-5 divide-y divide-rule border-y border-rule text-sm">
          {bills.map((b) => (
            <li key={b.bill}>
              <button className="flex w-full justify-between gap-4 py-2.5 text-left hover:bg-paper" onClick={() => onBill(b.bill)}>
                <span>
                  {b.supplier}, {b.inv_no}
                </span>
                <span>{money(b.amount)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

/** One question with buttons when the request has more than one reading. */
export function QuestionPanel({ reply, onPlan, onExample }: { reply: Question; onPlan: (r: PlanReply) => void; onExample: (t: string) => void }) {
  const q = reply.route.question;
  const name = useSupplierName();
  const { data: st } = useAppState();
  const answer = useAction((choice: string) => api.post<PlanReply>(`/questions/${reply.id}/answer`, { choice }));
  const label = (o: any) => {
    if (typeof o === "object") return o.label;
    if (typeof o === "string" && o.startsWith("MAT:")) return `All ${o.slice(4).toLowerCase()} bills`;
    if (o === "ALL") return "All suppliers";
    return st?.suppliers[o]?.name ?? name(o) ?? o;
  };
  const value = (o: any) => (typeof o === "object" ? o.intent : o);

  return (
    <article>
      <p className="text-sm text-muted">“{reply.route.text}”</p>
      <h1 className="mt-2 text-xl">{q.text}</h1>
      {q.options && q.options.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {q.options.map((o) => (
            <button key={value(o)} className="btn-quiet" disabled={answer.isPending} onClick={() => answer.mutate(value(o), { onSuccess: onPlan })}>
              {label(o)}
            </button>
          ))}
        </div>
      )}
      {q.examples && (
        <ul className="mt-5 space-y-2">
          {q.examples.map((e) => (
            <li key={e}>
              <button className="text-ledger hover:underline" onClick={() => onExample(e)}>
                {e}
              </button>
            </li>
          ))}
        </ul>
      )}
      <ErrorLine error={answer.error} />
    </article>
  );
}
