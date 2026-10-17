import { useEffect, useRef, useState } from "react";
import type { PlanReply, Question } from "../../lib/api";
import { BillPanel } from "./BillPanel";
import { CasePanel } from "./CasePanel";
import { Queue } from "./Queue";
import { PlanPanel, QuestionPanel } from "./PlanPanel";
import { RequestBar } from "./RequestBar";

export type Focus =
  | { kind: "none" }
  | { kind: "bill"; id: string }
  | { kind: "case"; id: string }
  | { kind: "plan"; reply: PlanReply }
  | { kind: "question"; reply: Question };

/** Two parts: what needs you on the left, the one thing you are looking at on the right. */
export default function Desk() {
  const [focus, setFocus] = useState<Focus>({ kind: "none" });
  const [draft, setDraft] = useState("");
  const panel = useRef<HTMLElement>(null);
  const openBill = (id: string) => setFocus({ kind: "bill", id });
  useEffect(() => {
    if (focus.kind !== "none" && window.innerWidth < 1024) panel.current?.scrollIntoView({ behavior: "smooth" });
  }, [focus]);

  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-16 pt-6 sm:px-6">
      <RequestBar
        value={draft}
        onChange={setDraft}
        onReply={(r) => setFocus(r.kind === "plan" ? { kind: "plan", reply: r } : { kind: "question", reply: r })}
      />
      <div className="mt-6 grid gap-8 lg:grid-cols-[300px_minmax(0,1fr)]">
        <Queue
          selected={focus.kind === "bill" || focus.kind === "case" ? focus.id : null}
          onBill={openBill}
          onCase={(id) => setFocus({ kind: "case", id })}
        />
        <section ref={panel} className="min-w-0 scroll-mt-4" aria-live="polite">
          {focus.kind === "none" && <Empty />}
          {focus.kind === "bill" && <BillPanel id={focus.id} />}
          {focus.kind === "case" && <CasePanel id={focus.id} />}
          {focus.kind === "plan" && <PlanPanel reply={focus.reply} onBill={openBill} />}
          {focus.kind === "question" && (
            <QuestionPanel reply={focus.reply} onPlan={(r) => setFocus({ kind: "plan", reply: r })} onExample={(t) => setDraft(t)} />
          )}
        </section>
      </div>
    </div>
  );
}

function Empty() {
  return (
    <div className="max-w-[52ch] pt-2">
      <p className="text-xl">Pick something from the list, or ask the agent above.</p>
      <p className="mt-2 text-muted">It shows you a plan before any money moves.</p>
    </div>
  );
}
