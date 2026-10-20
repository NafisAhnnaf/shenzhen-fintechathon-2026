import { useEffect, useRef, useState } from "react";
import type { PlanReply, Question } from "../../lib/api";
import { BillPanel } from "./BillPanel";
import { CasePanel } from "./CasePanel";
import { Queue } from "./Queue";
import { PlanPanel, QuestionPanel } from "./PlanPanel";
import { RequestBar } from "./RequestBar";
import { ReaderPanel } from "./ReaderPanel";
import { Art, C } from "../../components/Characters";

export type Focus =
  | { kind: "none" }
  | { kind: "bill"; id: string }
  | { kind: "case"; id: string }
  | { kind: "plan"; reply: PlanReply }
  | { kind: "question"; reply: Question }
  | { kind: "reading"; file: File; n: number };

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
    <div>
      <RequestBar
        value={draft}
        onChange={setDraft}
        onReply={(r) => setFocus(r.kind === "plan" ? { kind: "plan", reply: r } : { kind: "question", reply: r })}
      />
      <div className="desk">
        <Queue
          selected={focus.kind === "bill" || focus.kind === "case" ? focus.id : null}
          onBill={openBill}
          onCase={(id) => setFocus({ kind: "case", id })}
          onUpload={(file) => setFocus({ kind: "reading", file, n: Date.now() })}
        />
        <section ref={panel} className="card detail scroll-mt-20" aria-live="polite">
          {focus.kind === "none" && <Empty />}
          {focus.kind === "bill" && <BillPanel id={focus.id} />}
          {focus.kind === "case" && <CasePanel id={focus.id} />}
          {focus.kind === "reading" && <ReaderPanel key={focus.n} file={focus.file} onBill={openBill} />}
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
    <div className="empty">
      <Art html={C.clerk("idle", 120)} />
      <h2>Pick something from the list, or ask the agent above.</h2>
      <p className="muted">It shows you a plan before any money moves.</p>
    </div>
  );
}
