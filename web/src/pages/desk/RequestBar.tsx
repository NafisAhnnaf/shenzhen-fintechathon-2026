import { api, type PlanReply, type Question } from "../../lib/api";
import { useAction, useRole } from "../../lib/hooks";
import { ErrorLine } from "../../components/bits";

const SUGGESTIONS = [
  "Pay Acme's bills due this week except the disputed one",
  "Pay all routine bills under $5,000",
  "Hold payments to suppliers with price anomalies",
] as const;

/** Plain-words requests with multimodal cues and quick-action chips. */
export function RequestBar({
  value,
  onChange,
  onReply,
}: {
  value: string;
  onChange: (v: string) => void;
  onReply: (r: PlanReply | Question) => void;
}) {
  const { role } = useRole();
  const ask = useAction((text: string) =>
    api.post<PlanReply | Question>("/request", {
      text,
      role: role === "approver" ? "finance_manager" : "owner",
    })
  );

  const submitWith = (text: string) => {
    const t = text.trim();
    if (t) {
      onChange(t);
      ask.mutate(t, { onSuccess: onReply });
    }
  };

  const submit = () => submitWith(value);

  return (
    <div className="space-y-2.5">
      <form
        className="relative flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="relative flex-1">
          {/* Leading Icon */}
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5 text-muted">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
          </div>

          <input
            id="request"
            className="field h-12 pl-11 pr-14 text-sm sm:text-base font-medium shadow-xs"
            placeholder="Ask agent or speak command, e.g. “Pay Acme's bills due this week except the disputed one”"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            autoComplete="off"
          />

          {/* Trailing shortcut indicator */}
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3">
            <kbd className="hidden sm:inline-flex items-center rounded border border-rule bg-paper px-1.5 py-0.5 text-[10px] font-mono text-muted">
              ⌘K
            </kbd>
          </div>
        </div>

        <button
          type="submit"
          className="btn-primary h-12 px-6 text-sm font-semibold shadow-xs"
          disabled={ask.isPending || !value.trim()}
        >
          {ask.isPending ? (
            <span className="flex items-center gap-1.5">
              <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Thinking
            </span>
          ) : (
            "Orchestrate"
          )}
        </button>
      </form>

      {/* Quick Action Suggestion Chips */}
      <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
        <span className="text-muted font-medium text-[11px]">Instant Actions:</span>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => submitWith(s)}
            disabled={ask.isPending}
            className="inline-flex items-center gap-1 rounded-full border border-rule bg-surface px-3 py-1 text-xs text-muted hover:border-ledger hover:text-ledger hover:bg-ledger-soft transition-all"
          >
            <span>✨</span>
            <span className="truncate max-w-[280px] sm:max-w-none">{s}</span>
          </button>
        ))}
      </div>

      <ErrorLine error={ask.error} />
    </div>
  );
}
