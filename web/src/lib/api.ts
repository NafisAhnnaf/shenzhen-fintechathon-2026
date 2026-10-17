// Thin client for the FastAPI back end (apagent/api.py). Types mirror what the API returns.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["content-type"] = "application/json";
  }
  const r = await fetch(`/api${path}`, init);
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) throw new ApiError(r.status, (data && (data.detail || data.error)) || r.statusText);
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
export type Tier = "T1" | "T2" | "hold" | "reject" | "history" | null;

export interface ChainState {
  network: string;
  vault: string;
  vault_balance_usd: number;
  naive_balance_usd: number;
  pool_balance_usd: number;
  pool_locked_usd: number;
  pool_free_usd: number;
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

export interface Supplier {
  name: string;
  contact: string;
  frozen: boolean;
  probation_left: number;
  rail: "token" | "bank";
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
  suppliers: Record<string, Supplier>;
  open_cases: Case[];
  consistency: { ok: boolean; checked: number; mismatches: unknown[] };
}

export interface FairPrice {
  item: string;
  material: string;
  p_last: number;
  p_invoice: number;
  actual: number;
  justified: number;
  excess: number;
  justified_price: number;
  overcharge: number;
  qty: number;
  index_last: number;
  index_now: number;
  series: string;
  flagged: boolean;
}

export interface Bill {
  bill: string;
  inv_no: string;
  supplier: string;
  supplier_id: string | null;
  status: "received" | "held" | "approved" | "paid" | "rejected";
  tier: Tier;
  group: string;
  supplier_says_total: number;
  amount: number;
  erp_bound: number;
  score: number | null;
  cutoff: number | null;
  reasons: string[];
  resolution: { action: string; amount: number; held?: number; text: string; credit_note?: string; credit?: number } | null;
  fair_price: FairPrice | null;
  injection_p: number;
  tx_hash: string | null;
  due: string;
  terms: string;
  disputed: boolean;
  mismatches: { code: string; reason: string }[];
  offsets: { against: string; amount: number; tx: string | null }[];
  premium: number | null;
  erp_ref: string | null;
}

export interface LogLine {
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
  status: "planned" | "done" | "stopped" | "skipped" | "needs_signature" | "failed";
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

export interface Question {
  kind: "question";
  id: string;
  route: { text: string; outcome: string; question: { kind: string; text: string; options?: any[]; examples?: string[] } };
}

export interface PlanReply {
  kind: "plan";
  plan: Plan;
}

export interface Query {
  id: string;
  bill: string;
  to: string;
  topic: string;
  subject: string;
  body: string;
  status: "draft" | "sent" | "resolved" | "needs_manager";
  amount: number | null;
}

export interface TxResult {
  ok: boolean;
  tx_hash: string | null;
  error: string | null;
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
