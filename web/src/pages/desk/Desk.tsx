import { useEffect, useRef, useState } from "react";
import type { PlanReply, Question } from "../../lib/api";
import { BillPanel } from "./BillPanel";
import { CasePanel } from "./CasePanel";
import { Queue } from "./Queue";
import { PlanPanel, QuestionPanel } from "./PlanPanel";
import { RequestBar } from "./RequestBar";
import { HeroTreasuryCard } from "../../components/HeroTreasuryCard";

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
    if (focus.kind !== "none" && window.innerWidth < 1024) {
      panel.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [focus]);

  return (
    <div className="mx-auto max-w-[1360px] px-4 pb-20 pt-6 sm:px-6">
      {/* Verdict-First Hero Treasury Card */}
      <HeroTreasuryCard />

      {/* Multimodal Conversational Command Bar */}
      <RequestBar
        value={draft}
        onChange={setDraft}
        onReply={(r) =>
          setFocus(r.kind === "plan" ? { kind: "plan", reply: r } : { kind: "question", reply: r })
        }
      />

      {/* Main Workspace: Split Master-Detail Layout */}
      <div className="mt-8 grid gap-8 lg:grid-cols-[360px_minmax(0,1fr)]">
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
            <QuestionPanel
              reply={focus.reply}
              onPlan={(r) => setFocus({ kind: "plan", reply: r })}
              onExample={(t) => setDraft(t)}
            />
          )}
        </section>
      </div>
    </div>
  );
}

function Empty() {
  return (
    <div className="surface-card flex flex-col items-center justify-center p-12 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-ledger-soft text-ledger">
        <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      </div>
      <h3 className="mt-4 text-lg font-semibold text-ink">Autonomous AP Workspace</h3>
      <p className="mt-1.5 max-w-[44ch] text-sm text-muted">
        Select a pending invoice from the triage queue on the left, or tell the agent what to execute in the command bar above.
      </p>
      <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-rule bg-paper px-3 py-1 text-xs text-muted">
        <span className="h-2 w-2 rounded-full bg-ledger" />
        <span>Cryptographic 3-way match & commodity index checks active</span>
      </div>
    </div>
  );
}
