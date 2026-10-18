import { useState, useEffect } from "react";
import { money, shortHash } from "../lib/format";

interface FaceIDModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  supplier: string;
  payableAmount: number;
  heldAmount: number;
  isPending: boolean;
  stage?: string;
  txHash?: string | null;
}

export function FaceIDModal({
  isOpen,
  onClose,
  onConfirm,
  supplier,
  payableAmount,
  heldAmount,
  isPending,
  stage,
}: FaceIDModalProps) {
  const [animating, setAnimating] = useState(false);

  useEffect(() => {
    if (isPending) {
      setAnimating(true);
    } else {
      setAnimating(false);
    }
  }, [isPending]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/60 backdrop-blur-sm transition-opacity sm:items-center p-0 sm:p-4">
      {/* Modal Container */}
      <div
        className="w-full max-w-lg overflow-hidden rounded-t-3xl sm:rounded-2xl border border-rule bg-surface shadow-2xl transition-all"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        {/* Mobile drag handle */}
        <div className="flex justify-center pt-3 pb-1 sm:hidden">
          <div className="h-1 w-10 rounded-full bg-rule" />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between border-b border-rule px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ledger-soft text-ledger">
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
            </div>
            <div>
              <h2 id="modal-title" className="text-base font-semibold text-ink">
                EIP-712 Dual-Key Authorization
              </h2>
              <p className="font-mono text-xs text-muted">Contract: BondedPaySafe.sol (0x4F...8B91)</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isPending}
            className="rounded-lg p-1.5 text-muted hover:bg-paper hover:text-ink disabled:opacity-50"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body Content */}
        <div className="p-6 space-y-5">
          {/* Payee & Split Summary Card */}
          <div className="rounded-xl border border-rule bg-paper p-4">
            <div className="flex items-baseline justify-between text-xs text-muted">
              <span>PAYEE CREDENTIAL</span>
              <span className="font-medium text-ledger">Tier 1 Supplier</span>
            </div>
            <div className="mt-1 text-base font-semibold text-ink">{supplier}</div>

            <div className="mt-4 grid grid-cols-2 gap-3 pt-3 border-t border-rule">
              <div>
                <span className="text-xs text-muted">Clean Released Portion</span>
                <div className="mt-0.5 font-mono text-lg font-semibold text-ledger">
                  {money(payableAmount)}
                </div>
                <span className="inline-flex items-center gap-1 text-[11px] text-ledger font-medium">
                  <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                  3-Way Matched
                </span>
              </div>
              <div>
                <span className="text-xs text-muted">Quarantined Escrow</span>
                <div className="mt-0.5 font-mono text-lg font-semibold text-ochre">
                  {heldAmount > 0 ? money(heldAmount) : "$0.00"}
                </div>
                <span className="text-[11px] text-ochre font-medium">
                  {heldAmount > 0 ? "⚠️ Anomaly Isolated" : "No Discrepancy"}
                </span>
              </div>
            </div>
          </div>

          {/* Cryptographic Dual Signer Proofs */}
          <div className="rounded-xl border border-rule bg-surface p-3.5 space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-muted">Signer 1 (Autonomous Agent v4.2 ECDSA)</span>
              <span className="font-mono text-ledger font-medium">Signed ✓</span>
            </div>
            <div className="flex items-center justify-between border-t border-rule pt-2">
              <span className="text-muted">Signer 2 (Marcus Vance, CFO EIP-712)</span>
              <span className="font-mono text-ochre font-medium">
                {animating ? "Asserting..." : "Awaiting FaceID"}
              </span>
            </div>
            <div className="flex items-center justify-between border-t border-rule pt-2 text-[11px] text-muted font-mono">
              <span>Domain Hash: {shortHash("0x82b4a2e5d9921bc4e491fa02c81e")}</span>
              <span>Sponsored Gas: 0.00012 ETH</span>
            </div>
          </div>

          {/* Biometric Interactive Target */}
          <div className="flex flex-col items-center justify-center py-3 text-center">
            <div className="relative flex items-center justify-center">
              {/* Outer pulsing ring */}
              <div
                className={`absolute h-20 w-20 rounded-full border-2 ${
                  animating
                    ? "border-ledger animate-ping opacity-75"
                    : "border-ledger/30"
                }`}
              />
              {/* Biometric Target Center */}
              <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-ledger-soft border border-ledger text-ledger shadow-inner">
                <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.75}
                    d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 004 11m0 0a8 8 0 008 8c.706 0 1.393-.058 2.06-.168"
                  />
                </svg>
              </div>
            </div>
            <p className="mt-3 text-xs font-medium text-ink">
              Hardware-Bound Key • Apple Secure Enclave / WebAuthn
            </p>
            <p className="text-[11px] text-muted">
              {stage || "Double-click side button or tap below to authenticate with FaceID"}
            </p>
          </div>

          {/* Action Buttons */}
          <div className="space-y-2">
            <button
              onClick={onConfirm}
              disabled={isPending}
              className="btn-primary w-full py-3 text-base font-semibold shadow-md"
            >
              {isPending ? (
                <span className="flex items-center gap-2">
                  <svg className="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  {stage || "Verifying Biometrics & Broadcasting..."}
                </span>
              ) : (
                `Authorize & Broadcast (${money(payableAmount)})`
              )}
            </button>
            <button
              onClick={onClose}
              disabled={isPending}
              className="btn-quiet w-full py-2.5 text-sm"
            >
              Cancel / Hold Disputed
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
