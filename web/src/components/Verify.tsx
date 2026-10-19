import { useState } from "react";
import { verifyLine } from "./ui";
import { ErrorLine, Hash, Modal } from "./ui";

/** Checks that a journal line is inside a Merkle root stored on-chain (spec E4). */
export function VerifyButton({ index, label = "Verify" }: { index: number; label?: string }) {
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await verifyLine(index));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button className="link small" disabled={busy} onClick={go}>{busy ? "Checking" : label}</button>
      {(res || err) && (
        <Modal title="Is this record on-chain?" onClose={() => { setRes(null); setErr(null); }}>
          <ErrorLine error={err} />
          {res && !res.anchored && <p>{res.message} You can anchor now from Activity.</p>}
          {res?.anchored && (
            <>
              <p className={res.ok ? "ok" : "bad"}><b>{res.message}</b></p>
              <dl className="dl">
                <dt>Record hash</dt><dd className="mono">{res.leaf}</dd>
                <dt>Root on-chain</dt><dd className="mono">{res.root_on_chain}</dd>
                <dt>Anchored</dt><dd>{res.anchor_date} · covers {res.lines_covered} records · <Hash h={res.anchor_tx} /></dd>
                <dt>Proof</dt><dd>{res.proof.length} hashes</dd>
              </dl>
              <pre className="pre">{res.proof.join("\n")}</pre>
              <p className="note">Hash the record, then hash it with each proof value in turn (smaller value first). The result equals the root stored by the EvidenceAnchor contract.</p>
            </>
          )}
        </Modal>
      )}
    </>
  );
}
