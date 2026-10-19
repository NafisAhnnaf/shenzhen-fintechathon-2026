import { useNavigate, useSearchParams } from "react-router-dom";
import type { Bill } from "../lib/api";
import { date } from "../lib/format";
import { useBills } from "../lib/hooks";
import { BillDetail, useStateToday } from "../components/BillDetail";
import { Empty, Money, PageHead, PeriodPicker, StatusTag, Tabs, periodBounds, useRemembered, type Period } from "../components/ui";

type Tab = "needs_approval" | "scheduled" | "on_hold" | "paid" | "rejected" | "all";

export default function Bills() {
  const { data: bills } = useBills();
  const today = useStateToday();
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const [tab, setTab] = useRemembered<Tab>("bills-tab", "needs_approval");
  const [period, setPeriod] = useRemembered<Period>("bills-period", { key: "all", from: "2025-11-01", to: today });
  const [from, to] = periodBounds(period.key, today, period);
  const inPeriod = (bills ?? []).filter((b) => (!from || b.received >= from) && (!to || b.received <= to));
  const count = (k: Tab) => (k === "all" ? inPeriod.length : inPeriod.filter((b) => b.stage === k).length);
  const rows = inPeriod.filter((b) => tab === "all" || b.stage === tab);
  const wanted = params.get("bill");
  const sel = (bills ?? []).find((b) => b.bill === wanted) ?? rows[0];
  const pick = (b: Bill) => setParams({ bill: b.bill });

  return (
    <>
      <PageHead
        title="Bills"
        sub="Every supplier bill, checked against orders, goods received and market prices."
        actions={<button className="btn" onClick={() => nav("/inbox")}>Add a bill</button>}
      />
      <PeriodPicker value={period} onChange={setPeriod} today={today} />
      <Tabs<Tab>
        value={tab}
        onChange={(t) => { setTab(t); setParams({}); }}
        items={[["needs_approval", "Needs approval", count("needs_approval")], ["scheduled", "Scheduled", count("scheduled")], ["on_hold", "On hold", count("on_hold")], ["paid", "Paid", count("paid")], ["rejected", "Rejected", count("rejected")], ["all", "All", count("all")]]}
      />
      <div className="split">
        <div className="card">
          {rows.length === 0 ? (
            <Empty title="Nothing here">Bills arrive from the inbox, the mailbox or an upload.</Empty>
          ) : (
            <div className="tablebox">
              <table>
                <thead>
                  <tr><th>Supplier</th><th>Received</th><th>Due</th><th className="r">Amount</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {rows.map((b) => (
                    <tr key={b.bill} className="click" tabIndex={0} aria-selected={sel?.bill === b.bill} onClick={() => pick(b)} onKeyDown={(e) => e.key === "Enter" && pick(b)}>
                      <td>{b.supplier}<span className="s2 mono">{b.inv_no}</span></td>
                      <td>{date(b.received)}</td>
                      <td>{date(b.due)}</td>
                      <td className="r"><Money v={b.stage === "paid" ? b.amount : b.supplier_says_total} /></td>
                      <td>
                        <StatusTag stage={b.stage} />
                        <span className="s2">{b.stage === "paid" ? (b.paid_by === "agent" ? "By agent" : "By finance manager") : b.reasons[0] ?? ""}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="card">{sel ? <BillDetail id={sel.bill} /> : <Empty title="Pick a bill to see its checks" />}</div>
      </div>
    </>
  );
}
