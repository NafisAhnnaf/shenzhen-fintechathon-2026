import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { money } from "../../lib/format";
import { TierMark } from "../../components/bits";
import { Art, C } from "../../components/Characters";

export interface ReadFields {
  inv_no: string;
  supplier_name: string;
  tax_id: string;
  sender_domain: string;
  po_id: string;
  date: string;
  due_date: string;
  terms: string;
  currency: string;
  lines: { item: string; desc: string; unit: string; qty: number; price: number }[];
  credit: number;
  total: number;
  bank_account: string;
  confidence: Record<string, number>;
  text: string;
}

type Stage = "received" | "reading" | "read" | "checking" | "decided" | "error";
interface Ev {
  stage: Stage;
  [k: string]: any;
}

const STEPS: [Stage, string][] = [
  ["received", "Received the file"],
  ["reading", "Reading the page"],
  ["read", "Fields extracted"],
  ["checking", "Checks and supervisor score"],
  ["decided", "Decision"],
];

/** One upload per file, however many times the panel mounts (React may mount it twice). */
const runs = new WeakMap<File, { events: Ev[]; listeners: Set<() => void> }>();

function start(file: File, onEnd: () => void) {
  const known = runs.get(file);
  if (known) return known;
  const run = { events: [] as Ev[], listeners: new Set<() => void>() };
  runs.set(file, run);
  const push = (e: Ev) => {
    run.events.push(e);
    run.listeners.forEach((l) => l());
  };
  (async () => {
    const f = new FormData();
    f.append("file", file);
    try {
      const r = await fetch("/api/documents/stream", { method: "POST", body: f });
      if (!r.ok || !r.body) throw new Error(`Upload failed (${r.status})`);
      const rd = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await rd.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, i).replace(/^data: /, "");
          buf = buf.slice(i + 2);
          if (chunk.trim()) push(JSON.parse(chunk));
        }
      }
      if (!run.events.some((e) => e.stage === "decided" || e.stage === "error")) push({ stage: "error", message: "The connection closed before a decision. Check the bill list." });
    } catch (e: any) {
      push({ stage: "error", message: e?.message ?? String(e) });
    } finally {
      onEnd();
    }
  })();
  return run;
}

/** Upload a bill and watch it being read: the page on the left, what the reader takes from it on the right. */
export function ReaderPanel({ file, onBill }: { file: File; onBill: (id: string) => void }) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<Ev[]>([]);
  const [t0] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  const url = useMemo(() => URL.createObjectURL(file), [file]);
  useEffect(() => () => URL.revokeObjectURL(url), [url]);

  useEffect(() => {
    const run = start(file, () => qc.invalidateQueries());
    const show = () => setEvents([...run.events]);
    run.listeners.add(show);
    show();
    return () => {
      run.listeners.delete(show);
    };
  }, [file]); // eslint-disable-line react-hooks/exhaustive-deps

  const last = events[events.length - 1];
  const finished = last?.stage === "decided" || last?.stage === "error";
  useEffect(() => {
    if (finished) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [finished]);

  const got = (s: Stage) => events.find((e) => e.stage === s);
  const read = got("read");
  const decided = got("decided");
  const error = got("error");
  // A step is done once the event that ends it has arrived.
  const ends: Record<string, boolean> = { received: !!got("received"), reading: !!read, read: !!read, checking: !!decided, decided: !!decided };
  const firstOpen = STEPS.findIndex(([s]) => !ends[s]) === -1 ? STEPS.length : STEPS.findIndex(([s]) => !ends[s]);
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  const isImg = file.type.startsWith("image/");

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-2xl">What the reader sees</h2>
        <span className="mono text-muted">
          {file.name} · {finished ? (read ? `read in ${read.seconds}s` : "") : `${((now - t0) / 1000).toFixed(1)}s`}
        </span>
      </div>

      <ol className="mt-4 flex flex-wrap gap-2" aria-label="Progress">
        {STEPS.map(([s, label], i) => {
          const state = i < firstOpen ? "done" : i === firstOpen ? (error ? "failed" : "active") : "todo";
          const cls = { done: "b-done", active: "b-attn", failed: "b-stop", todo: "b-idle" }[state];
          return (
            <li key={s} className={`badge ${cls}`}>
              {state === "active" ? <span className="spin dark" style={{ width: 12, height: 12 }} /> : state === "done" ? "✓" : state === "failed" ? "✕" : "○"}{" "}
              {s === "reading" && got("reading") ? `Reading with ${got("reading")!.reader}` : label}
            </li>
          );
        })}
      </ol>

      <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <div className="overflow-hidden rounded-lg border border-rule bg-paper" style={{ minHeight: 420 }}>
          {isPdf ? (
            <iframe title="The uploaded bill" src={`${url}#toolbar=0&view=FitH`} className="h-[560px] w-full" />
          ) : isImg ? (
            <img src={url} alt="The uploaded bill" className="w-full object-contain" />
          ) : (
            <p className="p-4 text-muted">An e-invoice file: no page to show.</p>
          )}
        </div>

        <div className="min-w-0">
          {!read && !error && (
            <div className="empty" style={{ minHeight: 360 }}>
              <Art html={C.clerk("magnify", 110)} />
              <p className="muted">Reading the page. The reader only fills in typed fields; it has no tools and no keys.</p>
            </div>
          )}
          {read && <ReadView r={read.read} live />}
          {error && (
            <p className="err mt-3" role="alert">
              {error.message}
            </p>
          )}
        </div>
      </div>

      {got("checking") && !decided && !error && (
        <p className="mt-5 flex items-center gap-3 font-semibold">
          <span className="spin dark" /> Checking against orders, deliveries and prices; the supervisor scores it.
        </p>
      )}
      {decided && (
        <div className="rise-in mt-6 flex flex-wrap items-center gap-4 rounded-lg bg-sunk p-5">
          <TierMark tier={decided.result.tier} status={decided.result.tier === "T1" ? "paid" : undefined} />
          <span className="min-w-0 flex-1">{(decided.result.reasons || [])[0]}</span>
          <button className="btn-primary" onClick={() => onBill(decided.result.bill)}>
            Open the bill
          </button>
        </div>
      )}
    </div>
  );
}

/** Every field the reader extracted, with its confidence. All of it is what the supplier's document says. */
export function ReadView({ r, live = false }: { r: ReadFields; live?: boolean }) {
  const c = (k: string) => r.confidence[k];
  const rows: [string, string, string?][] = [
    ["Invoice number", r.inv_no, "inv_no"],
    ["Supplier", r.supplier_name],
    ["Tax ID", r.tax_id],
    ["Sender domain", r.sender_domain],
    ["Purchase order", r.po_id, "po_id"],
    ["Date · due", `${r.date} · ${r.due_date}`],
    ["Terms", r.terms],
    ["Bank account", r.bank_account || "–"],
  ];
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        <span className="badge b-stop">supplier says</span> Every value below is what the document claims. The checks decide what we pay.
      </p>
      <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-5 gap-y-2 text-[15px]">
        {rows.map(([k, v, ck], i) => (
          <div key={k} className={`contents ${live ? "rise-in" : ""}`} style={live ? { animationDelay: `${i * 70}ms` } : undefined}>
            <dt className="text-muted">{k}</dt>
            <dd className="flex min-w-0 items-center gap-3">
              <span className="min-w-0 break-all font-semibold">{v}</span>
              {ck && <Conf v={c(ck)} />}
            </dd>
          </div>
        ))}
      </dl>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-muted">
            <tr className="rule-b">
              <th className="py-1.5 font-normal">Item</th>
              <th className="py-1.5 text-right font-normal">Qty</th>
              <th className="py-1.5 text-right font-normal">Price</th>
              <th className="py-1.5 text-right font-normal">Line</th>
            </tr>
          </thead>
          <tbody>
            {r.lines.map((l, i) => (
              <tr key={i} className={`rule-b ${live ? "rise-in" : ""}`} style={live ? { animationDelay: `${(rows.length + i) * 70}ms` } : undefined}>
                <td className="py-1.5 pr-3">
                  <span className="font-semibold">{l.item}</span> <span className="text-muted">{l.desc}</span>
                </td>
                <td className="num py-1.5 text-right">
                  {l.qty.toLocaleString()} {l.unit} <Conf v={c(`line${i}.qty`)} small />
                </td>
                <td className="num py-1.5 text-right">
                  {money(l.price)} <Conf v={c(`line${i}.price`)} small />
                </td>
                <td className="num py-1.5 text-right">{money(l.qty * l.price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="kv">
        {r.credit ? (
          <>
            <dt>Credit</dt>
            <dd className="num">−{money(r.credit)}</dd>
          </>
        ) : null}
        <dt>Total ({r.currency})</dt>
        <dd className="num flex items-center gap-3 text-lg font-bold">
          {money(r.total)} <Conf v={c("total")} />
        </dd>
      </dl>
      {r.text && (
        <div>
          <p className="qlabel">OTHER TEXT ON THE PAGE · SHOWN AS-IS, NEVER FOLLOWED</p>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-rule bg-paper p-3 font-mono text-[13px] text-body">{r.text}</pre>
        </div>
      )}
    </div>
  );
}

function Conf({ v, small = false }: { v?: number; small?: boolean }) {
  if (v == null) return null;
  const low = v < 0.8;
  return (
    <span className="inline-flex items-center gap-1.5 align-middle" title={`Reader confidence ${(v * 100).toFixed(0)}%`}>
      <span className="inline-block overflow-hidden rounded-full bg-sunk" style={{ width: small ? 28 : 56, height: 6 }}>
        <span className="block h-full rounded-full" style={{ width: `${v * 100}%`, background: low ? "#7A2E9E" : "#1F4CB8" }} />
      </span>
      {!small && <span className={`text-xs ${low ? "text-oxblood font-bold" : "text-muted"}`}>{(v * 100).toFixed(0)}%</span>}
    </span>
  );
}
