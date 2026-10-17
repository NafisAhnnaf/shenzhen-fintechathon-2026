import { api, type PlanReply, type Question } from "../../lib/api";
import { useAction, useRole } from "../../lib/hooks";
import { ErrorLine } from "../../components/bits";

/** Plain-words requests. The agent answers with a plan to confirm, or one question. */
export function RequestBar({ value, onChange, onReply }: { value: string; onChange: (v: string) => void; onReply: (r: PlanReply | Question) => void }) {
  const { role } = useRole();
  const ask = useAction((text: string) => api.post<PlanReply | Question>("/request", { text, role: role === "approver" ? "finance_manager" : "owner" }));
  const submit = () => {
    const t = value.trim();
    if (t) ask.mutate(t, { onSuccess: onReply });
  };
  return (
    <div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label htmlFor="request" className="sr-only">
          Tell the agent what to do
        </label>
        <input
          id="request"
          className="field h-12 text-lg"
          placeholder="Tell the agent what to do, for example “Pay Acme's bills due this week except the disputed one”"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
        />
        <button className="btn-primary h-12 px-5" disabled={ask.isPending || !value.trim()}>
          {ask.isPending ? "Planning" : "Plan"}
        </button>
      </form>
      <ErrorLine error={ask.error} />
    </div>
  );
}
