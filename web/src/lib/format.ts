import type { LogLine } from "./api";

const usd = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export const money = (v: number | null | undefined) => (v == null ? "–" : `$${usd.format(v)}`);
export const money0 = (v: number | null | undefined) => (v == null ? "–" : `$${usd0.format(v)}`);
export const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`;
export const signedPct = (v: number, digits = 1) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
export const shortHash = (h: string) => `${h.slice(0, 10)}…${h.slice(-6)}`;
export const shortAddr = (a: string) => `${a.slice(0, 6)}…${a.slice(-4)}`;

export const time = (ts: number) =>
  new Date(ts * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export const ACTOR: Record<string, string> = {
  agent: "Agent",
  governor: "Governor",
  contract: "Contract",
  finance_manager: "Finance manager",
  owner: "Owner",
  underwriter: "Bank",
  arbiter: "Arbiter",
  system: "Policy",
};

export const ROLE: Record<string, string> = {
  owner: "Owner",
  approver: "Finance manager",
  agent: "Agent service",
  governor: "Governor service",
  underwriter: "Bank",
  arbiter: "Arbiter",
  viewer: "Viewer",
  "*": "Scripted run",
};

export const STAGE: Record<string, [string, string]> = {
  received: ["Received", "st-idle"],
  scheduled: ["Scheduled", "st-info"],
  needs_approval: ["Needs approval", "st-review"],
  on_hold: ["On hold", "st-hold"],
  paid: ["Paid", "st-paid"],
  rejected: ["Rejected", "st-idle"],
};

export const PAYER: Record<string, string> = { agent: "Agent", finance_manager: "Finance manager", history: "Before the agent (ERP)" };

const day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
export const date = (iso?: string | null) => (iso ? day.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`)) : "–");

/** One plain sentence per journal line. */
export function describe(l: LogLine, supplierName: (id?: string) => string): string {
  const d = l.detail || {};
  switch (l.kind) {
    case "intake":
      return `Received ${d.inv_no} for ${money(d.total)}`;
    case "decision":
      return d.tier === "T1"
        ? `Cleared to pay on its own`
        : d.tier === "T2"
          ? `Needs a signature: ${(d.reasons || [])[0] ?? ""}`
          : d.tier === "reject"
            ? `Rejected: ${(d.reasons || [])[0] ?? ""}`
            : `Held: ${(d.reasons || [])[0] ?? ""}`;
    case "pay_autonomous":
      return `Paid ${money(d.amount)} to ${supplierName(d.supplier)} on its own`;
    case "pay_approved":
      return `Paid ${money(d.amount)} to ${supplierName(d.supplier)} with the manager's signature`;
    case "approve":
      return `Approved ${money(d.amount)}`;
    case "reject":
      return "Rejected the bill";
    case "injection_flag":
      return `Found instructions hidden in supplier text`;
    case "policy_block":
      return `Refused by policy ${l.policy}: ${d.reason}`;
    case "revert":
      return `Contract refused: ${d.error}`;
    case "bad_signature":
      return "Refused a signature from the wrong key";
    case "freeze_payee":
      return `Froze payments to ${supplierName(d.supplier)}: ${d.reason}`;
    case "unfreeze_payee":
      return `Unfroze ${supplierName(d.supplier)}`;
    case "pause_self":
      return `Paused itself: ${d.reason}`;
    case "unpause":
      return "Resumed";
    case "case_open":
      return `Opened a case: ${String(d.kind).replace(/_/g, " ")}`;
    case "case_confirm":
      return `Confirmed case ${d.case}`;
    case "reconcile":
      return `Checked ${supplierName(d.supplier)}'s statement: ${(d.cases || []).length} case(s)`;
    case "open_receivable":
      return `Recorded ${money(d.amount)} owed back by the supplier`;
    case "file_claim":
      return `Filed a claim for ${money(d.amount)}`;
    case "claim_paid":
      return "Reserve repaid the company";
    case "record_offset":
      return `Recovered ${money(d.amount)} from the next bill`;
    case "cutoff_drop":
      return `Lowered the limit for ${d.group} bills to ${Number(d.after).toFixed(3)}`;
    case "probation":
      return `Next ${d.bills} bills from ${supplierName(d.supplier)} go to a person`;
    case "draft_query":
      return `Drafted a query to ${d.to}`;
    case "send_query":
      return `Sent query ${d.query}`;
    case "reply":
      return `Supplier replied: ${String(d.class).replace(/_/g, " ")}`;
    case "message":
      return `Message from ${supplierName(d.supplier)}: ${String(d.class).replace(/_/g, " ")}`;
    case "email_unknown_sender":
      return `Ignored an email from an unregistered sender (${d.from})`;
    case "request":
      return `“${d.text}”`;
    case "plan_preview":
      return d.summary;
    case "plan_run":
      return "Started the plan";
    case "plan_cancel":
      return `Cancelled the plan`;
    case "step_stopped":
      return `Stopped a step: ${d.reason}`;
    case "settings_proposed":
      return `Proposed the ${d.bundle} setting`;
    case "settings_approved":
      return "Underwriter approved the setting";
    case "settings_active":
      return `The ${d.bundle} setting is active on-chain`;
    case "anchor":
      return "Anchored today's log on-chain";
    case "erp_sync":
      return `Read ${d.orders} orders and ${d.suppliers} suppliers from ${d.source === "odoo" ? "Odoo" : d.source.toUpperCase()}`;
    case "erp_payment":
      return `Recorded the payment in ${d.erp === "odoo" ? "Odoo" : d.erp}: ${String(d.ref).replace(/^\w+:/, "")}`;
    case "erp_payment_failed":
      return `Could not record the payment in ${d.erp}; needs reconciliation`;
    case "hold":
      return `Held: ${d.reason}`;
    case "answer":
      return `Chose ${supplierName(d.choice) || d.choice}`;
    case "email_sent":
      return `Emailed ${d.to}: ${String(d.template).replace(/_/g, " ")}`;
    case "email_draft":
      return `Drafted an email for the finance manager: ${String(d.template).replace(/_/g, " ")}`;
    case "email_failed":
      return `Email to ${d.to} failed`;
    case "email_blocked":
      return `Email refused by policy`;
    case "mailbox_poll":
      return `Read ${d.messages} new message(s) from the mailbox`;
    case "approve_first":
      return `Signed ${money(d.amount)}; above ${money0(d.threshold)} the owner signs too`;
    case "payee_set":
      return `${d.new ? "Added" : "Changed payment details for"} ${supplierName(d.supplier)} after a call-back`;
    case "signing_key":
      return d.key ? `Enrolled ${supplierName(d.supplier)}'s invoice-signing key` : `Removed ${supplierName(d.supplier)}'s signing key`;
    case "budget_set":
      return d.monthly_usd == null ? `Cleared the ${d.centre} budget` : `Set the ${d.centre} budget to ${money0(d.monthly_usd)} a month`;
    case "draft_po":
      return `Drafted purchase order ${d.id}: ${d.qty} ${d.unit} of ${d.item}`;
    case "offer_draft":
      return `Drafted early-payment offer ${d.offer}: ${pct(d.pct)} off`;
    case "offer_accepted":
      return `Supplier accepted offer ${d.offer}: pay ${money(d.net)}`;
    case "offer_declined":
      return `Supplier declined offer ${d.offer}`;
    case "claim_dispute":
      return "The bank disputed the claim";
    case "claim_resolve":
      return `The arbiter approved ${money(d.amount)} of the claim`;
    case "pool_fund":
      return `The bank added ${money(d.amount)} to the reserve`;
    case "tx_replay":
      return "Refused a reused transaction";
    case "bad_owner_tx":
      return `Refused a transaction: ${d.error}`;
    case "refused":
      return `The governor refused to co-sign: ${d.reason}`;
    case "pay_timing":
      return d.mode === "now" ? "Bills cleared by the agent are paid at once" : "Bills are paid on their best date";
    case "pause_self":
      return `Paused: ${d.reason}`;
    case "case_dismiss":
      return "Dismissed the case";
    default:
      return l.kind.replace(/_/g, " ");
  }
}

/** Journal noise we do not show: internal routing and per-step echoes. */
export const QUIET = new Set(["route", "step_pay", "step_hold", "step_release", "step_query", "step_probation", "step_pause", "step_settings", "step_resume"]);
