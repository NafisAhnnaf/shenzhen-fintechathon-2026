// Client for the FastAPI back end (apagent/api.py). The session cookie (email or wallet sign-in) goes with every call.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** Raised on 401 so the app can send the person to the sign-in page. */
export const SIGNED_OUT = "desk:signed-out";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {}, credentials: "same-origin" };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["content-type"] = "application/json";
  }
  const r = await fetch(`/api${path}`, init);
  const text = await r.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (r.status === 401 && !path.startsWith("/auth/") && path !== "/me") window.dispatchEvent(new Event(SIGNED_OUT));
  if (!r.ok) throw new ApiError(r.status, (data && (data.detail || data.message || data.error)) || r.statusText);
  return data as T;
}

export const api = {
  get: <T>(p: string) => call<T>("GET", p),
  post: <T>(p: string, body?: unknown) => call<T>("POST", p, body ?? {}),
  upload: <T>(p: string, file: File) => {
    const f = new FormData();
    f.append("file", file);
    return call<T>("POST", p, f);
  },
};

// ------------------------------------------------------------------ types
export type Role = "owner" | "approver" | "clerk" | "underwriter" | "arbiter" | "viewer" | "*";
export type Stage = "received" | "scheduled" | "needs_approval" | "on_hold" | "paid" | "rejected";

export interface Me {
  kind: "account" | "wallet";
  address: string | null;
  role: Role | "none";
  label: string;
  name: string;
  email: string;
  company: string | null;
  companies: { id: string; name: string; slug: string; role: string }[];
  two_factor?: boolean;
  signs_as?: string | null;
  expected_wallet?: string | null;
}

export interface Public {
  network: string;
  chain_id: number;
  rpc: string;
  company: string;
  roles: Record<string, string>;
  auth: boolean;
  login: "accounts" | "wallet";
  demo_date: string;
}

export interface ChainState {
  network: string;
  vault: string;
  vault_balance_usd: number;
  naive_balance_usd: number;
  pool_balance_usd: number;
  pool_locked_usd: number;
  pool_free_usd: number;
  pool_owed_usd: number;
  pool_paused: boolean;
  agent_paused: boolean;
  settings_id: number;
  mode: "standard" | "self_reserve" | "bonded";
  p_day_usd: number;
  p_nday: number;
  p_supweek_usd: number;
  r_usd: number;
  p_cap_usd: number;
}

export interface AppState {
  network: string;
  signing: "client" | "server";
  today: string;
  company: string;
  cash_usd: number;
  chain: ChainState;
  bundle: string;
  money: Record<string, number>;
  contracts: Record<string, string>;
  roles: Record<string, string>;
  server_holds: string[];
  chain_id: number;
  rpc: string;
  explorer: string | null;
  suppliers: Record<string, { name: string; contact: string; frozen: boolean; probation_left: number; rail: "token" | "bank" }>;
  open_cases: Case[];
  erp: Record<string, any>;
  pending_settings: Record<string, string>;
  consistency: { ok: boolean; checked: number; mismatches: Record<string, any>[] };
}

export interface MatchRow {
  item: string;
  desc: string;
  unit: string;
  invoice: { qty: number; price: number; amount: number };
  order: { qty: number; price: number } | null;
  received: { qty: number; billed_before: number } | null;
  qty_ok: boolean;
  price_ok: boolean;
}

export interface Bill {
  bill: string;
  inv_no: string;
  supplier: string;
  supplier_id: string | null;
  status: string;
  stage: Stage;
  tier: string | null;
  paid_by: "agent" | "finance_manager" | "history" | null;
  group: string;
  supplier_says_total: number;
  amount: number;
  erp_bound: number;
  score: number | null;
  cutoff: number | null;
  reasons: string[];
  resolution: { action: string; amount: number; held?: number; text: string; offer?: string } | null;
  fair_price: Record<string, any> | null;
  injection_p: number;
  tx_hash: string | null;
  due: string;
  terms: string;
  disputed: boolean;
  mismatches: { code: string; reason: string; detail?: Record<string, any> }[];
  offsets: { against: string; amount: number; tx: string | null }[];
  premium: number | null;
  erp_ref: string | null;
  received: string;
  paid_on: string | null;
  source: string;
  po: string;
  inv_date: string;
  currency: string;
  fx: { currency: string; total: number; rate: number; date: string } | null;
  hold_reason: string | null;
  plan_id: string | null;
  match: MatchRow[];
  confidence: Record<string, number>;
  low_confidence: string[];
  queries: string[];
  emails: string[];
  cases: string[];
}

export interface LogLine {
  index?: number;
  ts: number;
  actor: string;
  kind: string;
  detail: Record<string, any>;
  plan_id: string | null;
  bill_id: string | null;
  policy: string | null;
  decision: string | null;
  tx_hash: string | null;
  security: boolean;
  anchored?: boolean;
}

export interface Case {
  case_id: string;
  kind: string;
  supplier_id: string;
  status: string;
  detail: Record<string, any>;
  created: string;
}

export interface Step {
  n: number;
  kind: string;
  bill: string | null;
  supplier: string | null;
  amount: number | null;
  tier: string | null;
  reason: string;
  status: "planned" | "done" | "stopped" | "skipped" | "needs_signature" | "failed" | "running";
  result: Record<string, any>;
}

export interface Plan {
  plan_id: string;
  intent: string;
  value: string | null;
  summary: string;
  steps: Step[];
  totals: Record<string, number>;
  status: "preview" | "running" | "done" | "cancelled";
  answer: Record<string, any> | null;
}

export interface RouteReply {
  kind: "question" | "plan";
  id?: string;
  plan?: Plan;
  route: { text: string; outcome: string; question?: { kind: string; text: string; slot?: string; options?: any[]; examples?: string[] } };
}

export interface Email {
  id: string;
  template: string;
  to: string;
  supplier: string;
  supplier_name: string;
  bill: string | null;
  status: "draft" | "sent" | "failed" | "blocked";
  actor: string;
  created: string;
  sent?: string;
  auto: boolean;
  subject: string;
  body: string;
  via?: string;
  error?: string;
}

export interface TypedData {
  domain: Record<string, any>;
  types: Record<string, { name: string; type: string }[]>;
  primaryType: string;
  message: Record<string, any>;
}

export interface PreparedTx {
  from: string;
  to: string;
  data: string;
  chainId: number;
  gas: string;
}

export interface Inbox {
  documents: { key: string; file: string; pdf: string; supplier: string; inv_no: string; total: number; taken: boolean }[];
  emails: string[];
  statements: string[];
}

export interface BundleCal {
  name: string;
  beta: number;
  p_nday: number;
  p_day_usd: number;
  lambdas: Record<string, number>;
  t1_share: number;
  K_usd: number;
  r_usd: number;
  chen_usd: number;
  max_exposure_usd: number;
}

export interface PaymentRow {
  date: string;
  bill: string;
  inv_no: string;
  supplier_id: string;
  supplier: string;
  amount: number;
  by: "agent" | "finance_manager" | "history";
  rail: "token" | "bank" | null;
  tx_hash: string | null;
  erp_ref: string | null;
  plan_id: string | null;
}

export interface Payments {
  from: string | null;
  to: string | null;
  today: string;
  totals: Record<string, { amount: number; count: number }>;
  rows: PaymentRow[];
}

export interface Notification {
  ts: number;
  for: string;
  severity: "action" | "alert";
  text: string;
  bill: string | null;
  kind: string;
}
