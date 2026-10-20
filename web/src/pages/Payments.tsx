import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, type LogLine, type Payments as P } from "../lib/api";
import { PAYER, date, money, pct } from "../lib/format";
import { useAction, useCan } from "../lib/hooks";
import { useStateToday } from "../components/BillDetail";
import { VerifyButton } from "../components/Verify";
import BankTransfers from "../components/BankTransfers";
import { Empty, ErrorLine, Hash, Money, PageHead, PaidBy, PeriodPicker, Tabs, downloadCsv, periodBounds, useRemembered, type Period } from "../components/ui";

export default function Payments() {
  const [tab, setTab] = useRemembered<"register" | "upcoming" | "bank">("payments-tab", "register");
  return (
    <>
      <PageHead title="Payments" sub="Every payment, who made it, and its on-chain record." />
      <Tabs value={tab} onChange={setTab} items={[["register", "Paid"], ["upcoming", "Upcoming and offers"], ["bank", "Bank transfers"]]} />
      {tab === "register" ? <Register /> : tab === "bank" ? <BankTransfers /> : <Upcoming />}
    </>
  );
}

function Register() {
  const today = useStateToday();
  const nav = useNavigate();
  const [period, setPeriod] = useRemembered<Period>("payments-period", { key: "month", from: "2025-11-01", to: today });
  const [by, setBy] = useRemembered<string>("payments-by", "all");
  const [from, to] = periodBounds(period.key, today, period);
  const qs = new URLSearchParams({ ...(from ? { start: from } : {}), ...(to ? { end: to } : {}), by });
  const { data, error } = useQuery({ queryKey: ["payments", qs.toString()], queryFn: () => api.get<P>(`/payments?${qs}`), refetchInterval: 6000 });
  const t = data?.totals ?? {};
  const tile = (k: string, label: string) => (
    <div>
      <div className="k">{label}</div>
      <div className="v">{money(t[k]?.amount ?? 0)}</div>
      <div className="muted small">{t[k]?.count ?? 0} payment{t[k]?.count === 1 ? "" : "s"}</div>
    </div>
  );
  const exportCsv = () =>
    downloadCsv(`payments-${from ?? "start"}-${to ?? today}.csv`, [
      ["date", "supplier", "invoice", "bill", "amount_usd", "paid_by", "rail", "transaction", "erp_ref"],
      ...(data?.rows ?? []).map((r) => [r.date, r.supplier, r.inv_no, r.bill, r.amount.toFixed(2), PAYER[r.by], r.rail, r.tx_hash, r.erp_ref]),
    ]);
  return (
    <>
      <div className="between">
        <PeriodPicker value={period} onChange={setPeriod} today={today} />
        <button className="btn" onClick={exportCsv} disabled={!data?.rows.length}>Export CSV</button>
      </div>
      <div className="card tiles">
        {tile("all", "Total paid")}
        {tile("agent", "Paid by the agent")}
        {tile("finance_manager", "Approved by the finance manager")}
        {tile("history", "Before the agent (ERP history)")}
      </div>
      <div className="row">
        {[["all", "All"], ["agent", "Agent"], ["finance_manager", "Finance manager"], ["history", "ERP history"]].map(([k, l]) => (
          <button key={k} className="chip" aria-pressed={by === k} onClick={() => setBy(k)}>{l}</button>
        ))}
      </div>
      <ErrorLine error={error} />
      <div className="card">
        {data && data.rows.length === 0 ? (
          <Empty title="No payments in this period" />
        ) : (
          <div className="tablebox">
            <table>
              <thead>
                <tr><th>Date</th><th>Supplier</th><th>Invoice</th><th className="r">Amount</th><th>Paid by</th><th>Rail</th><th>Transaction</th><th /></tr>
              </thead>
              <tbody>
                {data?.rows.slice(0, 400).map((r) => (
                  <tr key={r.bill} className={r.by !== "history" ? "click" : ""} onClick={() => r.by !== "history" && nav(`/bills?bill=${r.bill}`)}>
                    <td style={{ whiteSpace: "nowrap" }}>{date(r.date)}</td>
                    <td>{r.supplier}{r.plan_id && <span className="s2">From a typed request</span>}</td>
                    <td className="mono">{r.inv_no}</td>
                    <td className="r"><Money v={r.amount} /></td>
                    <td><PaidBy by={r.by} /></td>
                    <td>{r.rail === "bank" ? "Bank transfer" : r.rail === "token" ? "tUSDC" : "–"}</td>
                    <td onClick={(e) => e.stopPropagation()}>{r.by === "history" ? <span className="muted small">{r.erp_ref ?? "in the ERP"}</span> : <Hash h={r.tx_hash} />}</td>
                    <td onClick={(e) => e.stopPropagation()}>{r.by !== "history" && <VerifyPayment bill={r.bill} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(data?.rows.length ?? 0) > 400 && <p className="note" style={{ padding: 12 }}>Showing the latest 400. Export for the rest.</p>}
          </div>
        )}
      </div>
    </>
  );
}

/** Find this bill's payment record in the journal, then verify it against the on-chain anchor. */
function VerifyPayment({ bill }: { bill: string }) {
  const { data } = useQuery({ queryKey: ["journal", bill], queryFn: () => api.get<LogLine[]>(`/journal?bill=${bill}&limit=60`), staleTime: 10_000 });
  const line = data?.find((l) => l.kind === "pay_autonomous" || l.kind === "pay_approved");
  if (!line) return null;
  return <VerifyButton index={line.index!} />;
}

function Upcoming() {
  const can = useCan();
  const nav = useNavigate();
  const { data: sched } = useQuery({ queryKey: ["schedule"], queryFn: () => api.get<{ pay_timing: string; rows: any[] }>("/schedule"), refetchInterval: 6000 });
  const { data: off } = useQuery({ queryKey: ["offers"], queryFn: () => api.get<{ candidates: any[]; offers: any[] }>("/offers"), refetchInterval: 6000 });
  const runDue = useAction(() => api.post<any[]>("/schedule/run"));
  const offer = useAction(async (bill: string) => {
    const out = await api.post<any>("/offers", { bill });
    if (out.error) throw new Error(out.error);
    return out;
  });
  return (
    <>
      <div className="card">
        <div className="between" style={{ padding: "12px 14px" }}>
          <div>
            <h2>Pay dates</h2>
            <p className="note">
              {sched?.pay_timing === "best_date"
                ? "Bills cleared by the agent are paid on these dates: early when a discount pays off, otherwise the day before they are due."
                : "Bills cleared by the agent are paid at once. The owner can switch to paying on the best date in Settings."}
            </p>
          </div>
          {can.staff && <button className="btn" onClick={() => runDue.mutate(undefined)}>Pay what is due today</button>}
        </div>
        {sched?.rows.length ? (
          <div className="tablebox">
            <table>
              <thead><tr><th>Pay on</th><th>Supplier</th><th>Invoice</th><th>Due</th><th className="r">Amount</th><th>Why this date</th></tr></thead>
              <tbody>
                {sched.rows.map((r) => (
                  <tr key={r.bill} className="click" onClick={() => nav(`/bills?bill=${r.bill}`)}>
                    <td>{date(r.pay_on)}</td>
                    <td>{r.supplier}<span className="s2">{r.stage === "needs_approval" ? "Needs approval first" : "Cleared"}</span></td>
                    <td className="mono">{r.inv_no}</td>
                    <td>{date(r.due)}</td>
                    <td className="r"><Money v={r.amount} /></td>
                    <td className="small">{r.early ? `Early: the discount is worth ${pct(r.annual_return)} a year` : "Day before it is due"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No bills waiting to be paid" />
        )}
      </div>

      <div className="card">
        <div style={{ padding: "12px 14px" }}>
          <h2>Early-payment offers</h2>
          <p className="note">Pay a supplier now in return for a discount, when the discount beats the cost of the credit line and cash stays above the floor. The finance manager sends each offer.</p>
        </div>
        {off?.candidates.length ? (
          <div className="tablebox">
            <table>
              <thead><tr><th>Supplier</th><th>Invoice</th><th>Due</th><th className="r">Amount</th><th className="r">Offer</th><th className="r">Worth a year</th><th /></tr></thead>
              <tbody>
                {off.candidates.map((c) => (
                  <tr key={c.bill}>
                    <td>{c.supplier}</td>
                    <td className="mono">{c.inv_no}</td>
                    <td>{date(c.due)} <span className="s2">{c.days_early} days early</span></td>
                    <td className="r"><Money v={c.amount} /></td>
                    <td className="r">{pct(c.pct)} off · <Money v={c.discount} /></td>
                    <td className="r">{pct(c.annual_return)}</td>
                    <td>{can.staff && <button className="btn small" disabled={offer.isPending} onClick={() => offer.mutate(c.bill)}>Draft offer</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No bill worth paying early right now" />
        )}
        {off?.offers.length ? (
          <div className="tablebox">
            <table>
              <thead><tr><th>Offer</th><th>Bill</th><th className="r">Discount</th><th>Status</th><th>Open until</th></tr></thead>
              <tbody>
                {off.offers.map((o) => (
                  <tr key={o.ref}>
                    <td className="mono">{o.ref}</td>
                    <td className="mono">{o.bill}</td>
                    <td className="r"><Money v={o.discount} /> ({pct(o.pct)})</td>
                    <td>{o.status === "draft" ? "Drafted: send it from Inbox › Outbox" : o.status}</td>
                    <td>{date(o.expires)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
      <ErrorLine error={runDue.error || offer.error} />
    </>
  );
}
