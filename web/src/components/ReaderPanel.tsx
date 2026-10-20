import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { money } from "../lib/format";
import { Tag } from "./ui";

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
  ["received", "Received"],
  ["reading", "Reading the page"],
  ["read", "Fields extracted"],
  ["checking", "Checks and risk score"],
  ["decided", "Decision"],
];

/** One upload per file, however many times the panel mounts (React may mount it twice in development). */
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
      const r = await fetch("/api/documents/stream", { method: "POST", body: f, credentials: "same-origin" });
      if (!r.ok || !r.body) {
        const t = await r.text().catch(() => "");
        throw new Error(`Upload failed (${r.status}) ${t.slice(0, 160)}`);
      }
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
      if (!run.events.some((e) => e.stage === "decided" || e.stage === "error"))
        push({ stage: "error", message: "The connection closed before a decision. Check Bills." });
    } catch (e: any) {
      push({ stage: "error", message: e?.message ?? String(e) });
    } finally {
      onEnd();
    }
  })();
  return run;
}

/** Watch a bill being read: the page on the left, every field the reader takes from it on the right, then the decision. */
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

  const got = (s: Stage) => events.find((e) => e.stage === s);
  const read = got("read");
  const decided = got("decided");
  const error = got("error");
  const finished = !!(decided || error);
  useEffect(() => {
    if (finished) return;
    const t = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(t);
  }, [finished]);
  // A step is done once the event that ends it has arrived.
  const ends: Record<string, boolean> = { received: !!got("received"), reading: !!read, read: !!read, checking: !!decided, decided: !!decided };
  const open = STEPS.findIndex(([s]) => !ends[s]);
  const firstOpen = open === -1 ? STEPS.length : open;
  const isPdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
  const isImg = file.type.startsWith("image/");
  const r = decided?.result;

  return (
    <div className="stack">
      <div className="between">
        <span className="mono muted">{file.name}</span>
        <span className="mono muted">{finished ? (read ? `read in ${read.seconds}s` : "") : `${((now - t0) / 1000).toFixed(1)}s`}</span>
      </div>
      <div className="row" aria-label="Progress">
        {STEPS.map(([s, label], i) => {
          const state = i < firstOpen ? "done" : i === firstOpen ? (error ? "failed" : "active") : "todo";
          const text = s === "reading" && got("reading") ? `Reading with ${got("reading")!.reader}` : label;
          return (
            <span key={s} className={`status ${state === "done" ? "st-ok" : state === "active" ? "st-info" : state === "failed" ? "st-bad" : "st-idle"}`}>
              {state === "active" ? <span className="spin" style={{ width: 10, height: 10 }} /> : state === "done" ? "✓" : state === "failed" ? "✕" : "○"} {text}
            </span>
          );
        })}
      </div>
      <div className="reader-grid">
        <div className="card reader-page">
          {isPdf ? (
            <iframe title="The uploaded bill" src={`${url}#toolbar=0&view=FitH`} />
          ) : isImg ? (
            <img src={url} alt="The uploaded bill" />
          ) : (
            <p className="note" style={{ padding: 14 }}>An e-invoice file: no page to show.</p>
          )}
        </div>
        <div className="stack" style={{ minWidth: 0 }}>
          {!read && !error && (
            <p className="row note">
              <span className="spin" /> Reading the page. The reader only fills in typed fields; it has no tools and no keys.
            </p>
          )}
          {read && <ReadView r={read.read} live />}
          {error && <p className="err" role="alert">{error.message}</p>}
        </div>
      </div>
      {got("checking") && !decided && !error && (
        <p className="row"><span className="spin" /> Checking against orders, goods received and prices; the risk service scores it.</p>
      )}
      {r && (
        <div className="proposal reader-decision">
          <Tag tone={r.tier === "T1" ? "ok" : r.tier === "T2" ? "review" : "bad"}>
            {r.tier === "T1" ? (r.scheduled ? `Cleared, pays ${r.scheduled}` : "Paid on its own") : r.tier === "T2" ? "Needs approval" : r.tier === "reject" ? "Rejected" : "On hold"}
          </Tag>
          <span className="grow">{(r.reasons || [])[0]}</span>
          {r.bill && <button className="btn primary" onClick={() => onBill(r.bill)}>Open the bill</button>}
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
    <div className="stack">
      <p className="note">
        <Tag tone="bad">supplier says</Tag> Every value below is what the document claims. The checks decide what we pay.
      </p>
      <dl className="dl">
        {rows.map(([k, v, ck], i) => (
          <div key={k} className={live ? "contents reader-in" : "contents"} style={live ? { animationDelay: `${i * 60}ms` } : undefined}>
            <dt>{k}</dt>
            <dd className="row">
              <b>{v}</b>
              {ck && <Conf v={c(ck)} />}
            </dd>
          </div>
        ))}
      </dl>
      <div className="tablebox">
        <table>
          <thead>
            <tr>
              <th>Item</th>
              <th className="right">Qty</th>
              <th className="right">Price</th>
              <th className="right">Line</th>
            </tr>
          </thead>
          <tbody>
            {r.lines.map((l, i) => (
              <tr key={i}>
                <td><b>{l.item}</b> <span className="muted">{l.desc}</span></td>
                <td className="right num">{l.qty.toLocaleString()} {l.unit} <Conf v={c(`line${i}.qty`)} small /></td>
                <td className="right num">{money(l.price)} <Conf v={c(`line${i}.price`)} small /></td>
                <td className="right num">{money(l.qty * l.price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="dl">
        {r.credit ? (
          <>
            <dt>Credit</dt>
            <dd className="num">−{money(r.credit)}</dd>
          </>
        ) : null}
        <dt>Total ({r.currency})</dt>
        <dd className="row num"><b>{money(r.total)}</b> <Conf v={c("total")} /></dd>
      </dl>
      {r.text && (
        <div className="sect">
          <span className="small muted">Other text on the page · shown as-is, never followed</span>
          <pre className="pre">{r.text}</pre>
        </div>
      )}
    </div>
  );
}

function Conf({ v, small = false }: { v?: number; small?: boolean }) {
  if (v == null) return null;
  const low = v < 0.8;
  return (
    <span className="row" style={{ gap: 6, display: "inline-flex" }} title={`Reader confidence ${(v * 100).toFixed(0)}%`}>
      <span className={`bar-meter ${low ? "over" : ""}`} style={{ width: small ? 26 : 52, display: "inline-block" }}>
        <span style={{ width: `${v * 100}%` }} />
      </span>
      {!small && <span className={`small ${low ? "bad" : "muted"}`}>{(v * 100).toFixed(0)}%</span>}
    </span>
  );
}
