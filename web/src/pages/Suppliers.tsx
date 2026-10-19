import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type PreparedTx } from "../lib/api";
import { money0, shortAddr } from "../lib/format";
import { useAction, useAppState, useCan } from "../lib/hooks";
import { Empty, ErrorLine, Modal, PageHead, Tag, useSendPrepared } from "../components/ui";

interface Row {
  id: string;
  name: string;
  contact: string;
  domain: string;
  rail: "token" | "bank";
  frozen: boolean;
  active: boolean | null;
  active_at: number | null;
  probation_left: number;
  confirmed_errors: number;
  signing_key: string;
  paid_ytd: number;
  open_cases: string[];
}

export default function Suppliers() {
  const can = useCan();
  const { data: rows } = useQuery({ queryKey: ["suppliers"], queryFn: () => api.get<Row[]>("/suppliers"), refetchInterval: 6000 });
  const [sel, setSel] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const s = rows?.find((r) => r.id === sel) ?? rows?.[0];
  return (
    <>
      <PageHead
        title="Suppliers"
        sub="The registry the agent may pay. A new or changed payee can be paid only after a cool-down, and only after someone phones the supplier on the number already on file."
        actions={can.owner && <button className="btn" onClick={() => setAdding(true)}>Add a supplier</button>}
      />
      <div className="split">
        <div className="card tablebox">
          <table>
            <thead><tr><th>Supplier</th><th>Paid by</th><th>Status</th><th className="r">Paid this year</th></tr></thead>
            <tbody>
              {rows?.map((r) => (
                <tr key={r.id} className="click" aria-selected={s?.id === r.id} onClick={() => setSel(r.id)}>
                  <td>{r.name}<span className="s2">{r.contact}</span></td>
                  <td>{r.rail === "bank" ? "Bank transfer" : "tUSDC wallet"}</td>
                  <td><SupplierStatus r={r} /></td>
                  <td className="r amt">{money0(r.paid_ytd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">{s ? <SupplierDetail r={s} /> : <Empty title="Pick a supplier" />}</div>
      </div>
      {adding && <AddSupplier onClose={() => setAdding(false)} />}
    </>
  );
}

function SupplierStatus({ r }: { r: Row }) {
  if (r.frozen) return <Tag tone="bad">Frozen</Tag>;
  if (r.active === false) return <Tag tone="review">Cool-down</Tag>;
  if (r.probation_left > 0) return <Tag tone="review">Probation: {r.probation_left} bills</Tag>;
  return <Tag tone="ok">Active</Tag>;
}

function SupplierDetail({ r }: { r: Row }) {
  const can = useCan();
  const send = useSendPrepared();
  const [change, setChange] = useState(false);
  const [key, setKey] = useState(r.signing_key);
  const unfreeze = useAction(async () => {
    const t = await api.get<{ tx: PreparedTx }>(`/owner-tx/unfreeze?supplier=${r.id}`);
    const hash = await send(t.tx);
    const out = await api.post<any>(`/payees/${r.id}/unfreeze`, { tx_hash: hash });
    if (out.error) throw new Error(out.error);
    return out;
  });
  const enrol = useAction(() => api.post(`/suppliers/${r.id}/signing-key`, { address: key }));
  return (
    <div className="detail">
      <div className="between">
        <div><h2>{r.name}</h2><div className="muted mono">{r.id}</div></div>
        <SupplierStatus r={r} />
      </div>
      <dl className="dl">
        <dt>Contact</dt><dd>{r.contact}</dd>
        <dt>Email domain</dt><dd>{r.domain} <span className="muted">(look-alike domains are refused)</span></dd>
        <dt>Paid by</dt><dd>{r.rail === "bank" ? "Bank transfer (mainland rail)" : "tUSDC to the registered wallet"}</dd>
        <dt>Confirmed mistakes</dt><dd>{r.confirmed_errors}</dd>
        <dt>Signs its invoices</dt><dd>{r.signing_key ? <span className="mono">{shortAddr(r.signing_key)}</span> : "No"}</dd>
        {r.active === false && r.active_at && <><dt>Payable from</dt><dd>{new Date((r.active_at > 1e12 ? r.active_at : r.active_at * 1000)).toLocaleString()}</dd></>}
        {r.open_cases.length > 0 && <><dt>Open cases</dt><dd>{r.open_cases.join(", ")}</dd></>}
      </dl>
      {can.owner ? (
        <div className="stack">
          <div className="row">
            <button className="btn" onClick={() => setChange(true)}>Change payment details</button>
            {r.frozen && <button className="btn primary" disabled={unfreeze.isPending} onClick={() => unfreeze.mutate(undefined)}>{unfreeze.isPending ? "Waiting for your wallet" : "Unfreeze"}</button>}
          </div>
          <label className="lbl">
            Invoice-signing key (the supplier's address; leave empty to remove)
            <span className="row">
              <input className="field grow" value={key} onChange={(e) => setKey(e.target.value)} placeholder="0x…" />
              <button className="btn" disabled={enrol.isPending} onClick={() => enrol.mutate(undefined)}>Save</button>
            </span>
          </label>
          <ErrorLine error={unfreeze.error || enrol.error} />
        </div>
      ) : (
        <p className="note">Only the owner changes payment details, unfreezes a supplier or enrols a signing key.</p>
      )}
      {change && <ChangePayee r={r} onClose={() => setChange(false)} />}
    </div>
  );
}

/** Call-back first, then the owner's transaction, then the cool-down. */
function ChangePayee({ r, onClose }: { r: Row; onClose: () => void }) {
  const send = useSendPrepared();
  const [rail, setRail] = useState(r.rail);
  const [wallet, setWallet] = useState("");
  const [number, setNumber] = useState("");
  const [person, setPerson] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const save = useAction(async () => {
    const t = await api.get<{ tx: PreparedTx }>(`/payees/${r.id}/tx?wallet=${wallet}&rail=${rail}`);
    const hash = await send(t.tx);
    const out = await api.post<any>(`/payees/${r.id}`, { wallet, rail, tx_hash: hash, callback: { confirmed, number, spoke_to: person } });
    if (out.error) throw new Error(out.error);
    onClose();
    return out;
  });
  const ready = confirmed && number && person && (rail === "bank" || /^0x[0-9a-fA-F]{40}$/.test(wallet));
  return (
    <Modal title={`Change payment details: ${r.name}`} onClose={onClose}>
      <p className="note">Never use a phone number from the email or invoice that asked for the change. Call the number already in your records.</p>
      <label className="lbl">Number you called (from our records)<input className="field" value={number} onChange={(e) => setNumber(e.target.value)} /></label>
      <label className="lbl">Who confirmed the change<input className="field" value={person} onChange={(e) => setPerson(e.target.value)} /></label>
      <label className="row"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> The supplier confirmed the new details on that call</label>
      <label className="lbl">Paid by
        <select className="field" value={rail} onChange={(e) => setRail(e.target.value as "token" | "bank")}>
          <option value="token">tUSDC wallet</option>
          <option value="bank">Bank transfer</option>
        </select>
      </label>
      {rail === "token" && <label className="lbl">New wallet address<input className="field mono" value={wallet} onChange={(e) => setWallet(e.target.value)} placeholder="0x…" /></label>}
      <p className="note">After you sign, the supplier cannot be paid until the cool-down ends. If it is frozen, unfreeze it afterwards.</p>
      <div className="row"><button className="btn primary" disabled={!ready || save.isPending} onClick={() => save.mutate(undefined)}>{save.isPending ? "Waiting for your wallet" : "Sign the change"}</button></div>
      <ErrorLine error={save.error} />
    </Modal>
  );
}

function AddSupplier({ onClose }: { onClose: () => void }) {
  const send = useSendPrepared();
  const { data: st } = useAppState();
  const [f, setF] = useState({ id: "", name: "", tax_id: "", domain: "", contact: "", rail: "token", wallet: "" });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  const save = useAction(async () => {
    const id = f.id.trim().toUpperCase();
    const t = await api.get<{ tx: PreparedTx }>(`/payees/${id}/tx?wallet=${f.wallet}&rail=${f.rail}`);
    const hash = await send(t.tx);
    const out = await api.post<any>(`/payees/${id}`, { wallet: f.wallet, rail: f.rail, tx_hash: hash, callback: { confirmed: true, onboarding: true },
      new: { name: f.name, tax_id: f.tax_id, domain: f.domain, contact: f.contact } });
    if (out.error) throw new Error(out.error);
    onClose();
    return out;
  });
  const ready = f.id && f.name && f.tax_id && f.domain && f.contact.includes("@") && (f.rail === "bank" || /^0x[0-9a-fA-F]{40}$/.test(f.wallet)) && !st?.suppliers[f.id.toUpperCase()];
  return (
    <Modal title="Add a supplier" onClose={onClose}>
      {[["id", "Reference (as in the ERP)"], ["name", "Name"], ["tax_id", "Tax ID"], ["domain", "Email domain"], ["contact", "Accounts email"]].map(([k, l]) => (
        <label key={k} className="lbl">{l}<input className="field" value={(f as any)[k]} onChange={set(k)} /></label>
      ))}
      <label className="lbl">Paid by<select className="field" value={f.rail} onChange={set("rail")}><option value="token">tUSDC wallet</option><option value="bank">Bank transfer</option></select></label>
      {f.rail === "token" && <label className="lbl">Wallet address<input className="field mono" value={f.wallet} onChange={set("wallet")} /></label>}
      <p className="note">A new supplier's first bills go to a person (probation), and it cannot be paid until the cool-down ends.</p>
      <div className="row"><button className="btn primary" disabled={!ready || save.isPending} onClick={() => save.mutate(undefined)}>{save.isPending ? "Waiting for your wallet" : "Sign and add"}</button></div>
      <ErrorLine error={save.error} />
    </Modal>
  );
}
