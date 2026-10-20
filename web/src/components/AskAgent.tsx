import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Plan, type PreparedTx, type RouteReply, type Step } from "../lib/api";
import { money } from "../lib/format";
import { useAction, useCan, useSupplierName } from "../lib/hooks";
import { ErrorLine, Hash, useSendPrepared } from "./ui";

const STEP: Record<string, string> = {
  planned: "Waiting",
  running: "Running",
  done: "Done",
  stopped: "Stopped",
  skipped: "Left out",
  needs_signature: "Needs a signature",
  failed: "Failed",
};

const EXAMPLES = ["Pay Acme's bills due this week except the disputed one", "Why was bill 0002 held?", "Be more careful this month"];

/** The request box in the top bar. A request becomes one question (if unclear) and then a plan from a fixed
 * template; nothing with an effect runs before Run. */
export function AskAgent() {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [reply, setReply] = useState<RouteReply | null>(null);
  const can = useCan();
  const ask = useAction(async (t: string) => {
    const r = await api.post<RouteReply>("/request", { text: t });
    setReply(r);
    return r;
  });
  const answer = useAction(async (choice: string) => {
    const r = await api.post<RouteReply>(`/questions/${reply!.id}/answer`, { choice });
    setReply(r);
    return r;
  });

  const submit = () => {
    if (!text.trim()) return;
    setOpen(true);
    ask.mutate(text.trim());
  };

  return (
    <div className="search ask" onFocus={() => setOpen(true)}>
      <label htmlFor="ask" className="ask-label">Ask the agent</label>
      <input
        id="ask"
        aria-label="Ask the agent"
        placeholder={can.staff ? "Type a request, e.g. “Pay Acme's bills due this week except the disputed one”" : "Only the owner and the finance manager can give the agent requests"}
        value={text}
        disabled={!can.staff}
        maxLength={500}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      {can.staff && <button className="btn small primary" disabled={!text.trim() || ask.isPending} onClick={submit}>Ask</button>}
      {open && (ask.isPending || reply || ask.error) && (
        <div className="popover">
          <div className="between">
            <span className="muted small">“{reply?.route?.text ?? text}”</span>
            <button className="btn small" onClick={() => { setOpen(false); setReply(null); setText(""); }}>
              Close
            </button>
          </div>
          {ask.isPending && <p className="row"><span className="spin" /> Reading your request</p>}
          {reply?.kind === "question" && <QuestionView reply={reply} onChoose={(c) => answer.mutate(c)} busy={answer.isPending} onExample={(t) => { setText(t); ask.mutate(t); }} />}
          {reply?.kind === "plan" && reply.plan && <PlanView initial={reply.plan} onDone={() => undefined} />}
          {reply?.kind === "refused" && <p className="warn" style={{ marginTop: 10 }}>{reply.reason}</p>}
          {reply?.kind === "answer" && <p style={{ marginTop: 10, whiteSpace: "pre-wrap" }}>{reply.text}</p>}
          {reply?.reader && (
            <p className="note small" style={{ marginTop: 8 }}>
              {reply.reader.decider === "agent"
                ? `Read by ${reply.reader.model}${reply.reader.tools?.length ? `; looked at: ${[...new Set(reply.reader.tools.filter((t) => t !== "propose_action" && t !== "ask_user"))].map((t) => t.replace(/_/g, " ")).join(", ") || "nothing"}` : ""}. Nothing runs until you press Run.`
                : reply.reader.fallback
                  ? "The AI was unavailable; the rule reader answered."
                  : "Read by the rule reader."}
            </p>
          )}
          <ErrorLine error={ask.error || answer.error} />
        </div>
      )}
    </div>
  );
}

function QuestionView({ reply, onChoose, busy, onExample }: { reply: RouteReply; onChoose: (c: string) => void; busy: boolean; onExample: (t: string) => void }) {
  const q = reply.route!.question!;
  const name = useSupplierName();
  const label = (o: any) => (typeof o === "string" ? (q.slot === "supplier" ? name(o) : q.slot === "bill" ? `Bill ${o}` : o) : o.label);
  return (
    <div className="stack" style={{ marginTop: 10 }}>
      <b>{q.text}</b>
      {q.options && q.options.length > 0 && (
        <div className="row">
          {q.options.map((o: any) => (
            <button key={typeof o === "string" ? o : o.intent} className="btn" disabled={busy} onClick={() => onChoose(typeof o === "string" ? o : o.intent)}>
              {label(o)}
            </button>
          ))}
        </div>
      )}
      {(q.examples ?? (q.kind === "unsupported" ? EXAMPLES : [])).length > 0 && (
        <div className="stack">
          {(q.examples ?? EXAMPLES).map((e: string) => (
            <button key={e} className="link" style={{ textAlign: "left" }} onClick={() => onExample(e)}>
              {e}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PlanView({ initial }: { initial: Plan; onDone: () => void }) {
  const [plan, setPlan] = useState<Plan>(initial);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const stop = useRef(false);
  const name = useSupplierName();
  const nav = useNavigate();
  const can = useCan();
  const send = useSendPrepared();
  if (plan.plan_id !== initial.plan_id) setPlan(initial);

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
    const hash = await send(r.tx);
    const out = await api.post<any>(`/plans/${plan.plan_id}/sign`, { tx_hash: hash });
    setPlan(await api.get<Plan>(`/plans/${plan.plan_id}`));
    return out;
  });

  if (plan.answer) {
    const a = plan.answer;
    return (
      <div className="stack" style={{ marginTop: 10 }}>
        <p>{a.text}</p>
        {a.card && (
          <button className="link" style={{ textAlign: "left" }} onClick={() => nav(`/bills?bill=${a.card.bill}`)}>
            Open bill {a.card.inv_no}
          </button>
        )}
        {a.bills?.length > 0 && (
          <ul className="checks">
            {a.bills.map((b: any) => (
              <li key={b.bill}>
                <span />
                <button className="link" style={{ textAlign: "left" }} onClick={() => nav(`/bills?bill=${b.bill}`)}>
                  {b.inv_no} · {money(b.amount)} · due {b.due}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const canRun = plan.status === "preview" && plan.steps.some((s) => s.status === "planned");
  const needsOwner = plan.steps.some((s) => (s.kind === "settings" || s.kind === "resume") && s.status === "needs_signature");
  return (
    <div className="stack" style={{ marginTop: 10 }}>
      <b>{plan.summary}</b>
      {plan.totals.cash_after != null && plan.totals.cash_after < plan.totals.cash_floor && (
        <p className="bad small">This would take cash below the floor of {money(plan.totals.cash_floor)}.</p>
      )}
      {plan.steps.length > 0 && (
        <table>
          <tbody>
            {plan.steps.map((s) => (
              <tr key={s.n}>
                <td>
                  {stepTitle(s, name)}
                  {s.status === "skipped" && s.reason && <span className="s2">{s.reason.replace(/^excluded: /, "Left out: ")}</span>}
                  {s.result?.tx?.tx_hash && <span className="s2"><Hash h={s.result.tx.tx_hash} /></span>}
                </td>
                <td className="r small">
                  <span className={s.status === "done" ? "ok" : s.status === "stopped" || s.status === "failed" ? "bad" : s.status === "needs_signature" || (s.status === "planned" && s.tier === "T2") ? "warn" : "muted"}>
                    {s.status === "planned" && s.tier === "T2" ? "Needs a signature" : STEP[s.status] ?? s.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="row">
        {canRun && can.staff && (
          <button className="btn primary" onClick={run} disabled={running}>
            {running ? "Running" : "Run"}
          </button>
        )}
        {(running || plan.status === "running") && (
          <button className="btn danger" onClick={() => cancel.mutate(undefined)}>
            Cancel the rest
          </button>
        )}
        {needsOwner && can.owner && (
          <button className="btn primary" disabled={sign.isPending} onClick={() => sign.mutate(undefined)}>
            {sign.isPending ? "Waiting for your wallet" : "Sign in your wallet"}
          </button>
        )}
        {needsOwner && !can.owner && <span className="note">The owner signs this in their wallet.</span>}
        {plan.status === "done" && <span className="ok">Done.</span>}
        {plan.status === "cancelled" && <span className="bad">Cancelled. Payments already sent stay sent.</span>}
      </div>
      <ErrorLine error={err || cancel.error || sign.error} />
    </div>
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
      return `Ask ${name(s.supplier)} about the bill`;
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
