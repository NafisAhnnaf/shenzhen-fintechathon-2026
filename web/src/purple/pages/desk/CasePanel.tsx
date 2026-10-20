import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useSendTransaction, useSignTypedData } from "wagmi";
import { api, type Case, type PreparedTx, type TypedData } from "../../lib/api";
import { money } from "../../lib/format";
import { useAction, useAppState, useRole } from "../../lib/hooks";
import { forViem, txFor } from "../../lib/wallet";
import { Dl, ErrorLine, Hash } from "../../components/bits";
import { caseTitle } from "./Queue";

/** A case the agent opened on its own: a missed credit found on a statement, or a bank-detail change request. */
export function CasePanel({ id }: { id: string }) {
  const { data: cases } = useQuery({ queryKey: ["cases"], queryFn: () => api.get<Case[]>("/cases"), refetchInterval: 3000 });
  const { data: st } = useAppState();
  const c = cases?.find((x) => x.case_id === id);
  if (!c) return <p className="text-muted">Loading the case.</p>;
  const sup = st?.suppliers[c.supplier_id];
  return (
    <article>
      <h1 className="text-2xl font-medium tracking-tight">{caseTitle(c)}</h1>
      <p className="mt-1 text-muted">
        {sup?.name ?? c.supplier_id}, opened {c.created}
      </p>
      {c.kind === "missed_credit" && <MissedCredit c={c} />}
      {c.kind === "bank_change" && <BankChange c={c} />}
      {!["missed_credit", "bank_change"].includes(c.kind) && (
        <pre className="mt-6 whitespace-pre-wrap text-sm text-muted">{JSON.stringify(c.detail, null, 2)}</pre>
      )}
    </article>
  );
}

function MissedCredit({ c }: { c: Case }) {
  const { role } = useRole();
  const { data: st } = useAppState();
  const { signTypedDataAsync } = useSignTypedData();
  const [stage, setStage] = useState("");
  const [result, setResult] = useState<any>(null);
  const d = c.detail;

  const confirm = useAction(async () => {
    setStage("Sign the receivable in your wallet");
    const req = await api.get<{ expiry: number; receivable: TypedData; claim?: TypedData }>(`/cases/${c.case_id}/signing`);
    const receivable_signature = await signTypedDataAsync(forViem(req.receivable));
    let claim_signature: string | undefined;
    if (req.claim) {
      setStage("Sign the claim in your wallet");
      claim_signature = await signTypedDataAsync(forViem(req.claim));
    }
    setStage("Recording");
    const out = await api.post<any>(`/cases/${c.case_id}/confirm`, { receivable_signature, claim_signature, expiry: req.expiry });
    if (out.error) throw new Error(out.error);
    setResult(out);
    return out;
  });
  const skip = useAction(() => api.post(`/demo/advance?seconds=125`));
  const payout = useAction(async () => {
    const out = await api.post<any>(`/claims/${d.bill}/execute`);
    if (!out.ok) throw new Error(out.error === "BadState" ? "The underwriter's dispute window is still open." : out.error);
    return out;
  });

  return (
    <>
      <div className="mt-7 grid gap-6 sm:grid-cols-3">
        <div>
          <div className="text-xl">{money(d.paid)}</div>
          <div className="mt-0.5 text-sm text-muted">We paid, {d.tier === "T1" ? "on its own" : "with a signature"}</div>
        </div>
        <div>
          <div className="text-xl">{money(d.owed)}</div>
          <div className="mt-0.5 text-sm text-muted">Owed, per the supplier's statement</div>
        </div>
        <div>
          <div className="text-3xl font-medium tracking-tight text-ochre">{money(d.amount)}</div>
          <div className="mt-0.5 text-sm text-muted">Paid too much</div>
        </div>
      </div>
      <div className="mt-8 border-t border-rule pt-5">
        <p className="max-w-[65ch] text-lg">
          The supplier's statement lists credit {d.statement_line?.ref} against invoice {d.statement_line?.against}. Our records had no
          such return, and we paid the full bill.
        </p>
        <p className="mt-2 max-w-[65ch] text-muted">
          Confirming records the amount as owed back on-chain, lowers the agent's limit for this kind of bill
          {st?.chain.mode !== "standard" && d.tier === "T1" ? ", files a claim on the reserve" : ""}, and sends the supplier's next
          bills to a person. The agent deducts it from the supplier's next bill.
        </p>
        <div className="mt-2 text-sm">
          Original payment <Hash h={d.tx_hash} />
        </div>
      </div>

      <div className="mt-6">
        {c.status === "open" && role === "approver" && (
          <button className="btn-primary" disabled={confirm.isPending} onClick={() => confirm.mutate(undefined, { onSettled: () => setStage("") })}>
            {confirm.isPending ? stage : "Confirm and sign"}
          </button>
        )}
        {c.status === "open" && role !== "approver" && <p className="text-sm text-muted">The finance manager confirms this in their wallet.</p>}
        {(result || c.status === "confirmed") && (
          <div className="space-y-4">
            {result && (
              <Dl
                rows={[
                  ["Owed back, recorded on-chain", <Hash h={result.receivable_tx?.tx_hash} />],
                  ...(result.claim ? ([["Claim on the reserve", <Hash h={result.claim.tx_hash} />]] as any) : []),
                  ...(result.cutoff ? ([["Limit for these bills", `${result.cutoff.before.toFixed(3)} to ${result.cutoff.after.toFixed(3)}`]] as any) : []),
                  ["Next bills to a person", String(result.probation?.probation_left ?? "")],
                ]}
              />
            )}
            {d.tier === "T1" && st?.chain.mode !== "standard" && (
              <div className="flex flex-wrap items-center gap-3">
                <button className="btn-quiet" disabled={payout.isPending} onClick={() => payout.mutate(undefined)}>
                  Pay out the claim
                </button>
                {st?.network === "localhost" && (
                  <button className="btn-quiet" disabled={skip.isPending} onClick={() => skip.mutate(undefined)}>
                    Skip the 2-minute dispute window (local chain only)
                  </button>
                )}
                {payout.data && (
                  <span className="text-sm text-ledger">
                    Repaid <Hash h={payout.data.tx_hash} />
                  </span>
                )}
              </div>
            )}
          </div>
        )}
        <ErrorLine error={confirm.error || payout.error || skip.error} />
      </div>
    </>
  );
}

function BankChange({ c }: { c: Case }) {
  const { role } = useRole();
  const { data: st } = useAppState();
  const { sendTransactionAsync } = useSendTransaction();
  const sup = st?.suppliers[c.supplier_id];
  const unfreeze = useAction(async () => {
    const r = await api.get<{ tx: PreparedTx }>(`/owner-tx/unfreeze?supplier=${c.supplier_id}`);
    const hash = await sendTransactionAsync(txFor(r.tx));
    return api.post(`/payees/${c.supplier_id}/unfreeze`, { tx_hash: hash });
  });
  return (
    <div className="mt-7 max-w-[65ch]">
      <p className="text-lg">
        The supplier asked to be paid into a different account. The agent froze payments to them on-chain. Bank details never change
        from a message.
      </p>
      <p className="mt-3 text-muted">
        Call {sup?.name ?? c.supplier_id} on the number in your records, not one in the message ({sup?.contact}). If the change is
        real, the owner updates the payee, which restarts the cool-down. If it was not, leave the freeze in place.
      </p>
      {sup?.frozen && role === "owner" && (
        <button className="btn-quiet mt-5" disabled={unfreeze.isPending} onClick={() => unfreeze.mutate(undefined)}>
          {unfreeze.isPending ? "Waiting for your wallet" : "Unfreeze payee"}
        </button>
      )}
      {sup && !sup.frozen && <p className="mt-5 text-sm text-ledger">Payee is not frozen.</p>}
      <ErrorLine error={unfreeze.error} />
    </div>
  );
}
