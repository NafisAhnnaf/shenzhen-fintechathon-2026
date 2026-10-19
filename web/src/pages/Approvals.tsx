import { useEffect, useState } from "react";
import { date, money } from "../lib/format";
import { useBills, useCan } from "../lib/hooks";
import { BillDetail } from "../components/BillDetail";
import { Empty, PageHead } from "../components/ui";

export default function Approvals() {
  const { data: bills } = useBills();
  const can = useCan();
  const q = (bills ?? []).filter((b) => b.stage === "needs_approval").sort((a, b) => a.due.localeCompare(b.due));
  const [id, setId] = useState<string | null>(null);
  // Keep showing the bill just signed, so its result stays on screen after it leaves the queue.
  useEffect(() => {
    if (!id && q[0]) setId(q[0].bill);
  }, [id, q]);
  const sel = q.find((b) => b.bill === id) ?? (id ? { bill: id } : q[0]);
  return (
    <>
      <PageHead
        title="Approvals"
        sub={can.manager ? "Bills the agent may not pay alone. Each comes with the agent's proposal; you sign in your wallet." : "Bills the agent may not pay alone, waiting for the finance manager (and the owner above the two-signature limit)."}
      />
      {q.length === 0 && !sel ? (
        <div className="card"><Empty title="Nothing waiting">Bills that need a signature appear here.</Empty></div>
      ) : (
        <div className="split">
          <div className="card queue">
            {q.map((b) => (
              <button key={b.bill} className="qitem" aria-selected={sel?.bill === b.bill} onClick={() => setId(b.bill)}>
                <span className="between"><b>{b.supplier}</b><span className="amt">{money(b.resolution?.amount ?? b.amount)}</span></span>
                <span className="muted small">{b.reasons[0]} · <span className="mono">{b.inv_no}</span> · due {date(b.due)}</span>
              </button>
            ))}
          </div>
          <div className="card">{sel && <BillDetail id={sel.bill} />}</div>
        </div>
      )}
    </>
  );
}
