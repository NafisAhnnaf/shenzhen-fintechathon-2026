import { api, type PlanReply, type Question } from "../../lib/api";
import { useAction, useRole } from "../../lib/hooks";
import { ErrorLine } from "../../components/bits";

const SUGGEST = ["Pay everything from Acme due this week except the disputed bill", "Pay the copper supplier", "Add a new bank account for Acme", "Be more careful this month"];

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
        className="reqbar"
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
                    placeholder="Tell the agent what to do, for example “Pay Acme's bills due this week except the disputed one”"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
        />
        <button className="btn btn-primary btn-lg" disabled={ask.isPending || !value.trim()}>
          {ask.isPending ? "Planning" : "Plan"}
        </button>
      </form>
      <div className="sugg" aria-label="Try one of these">
        {SUGGEST.map((t) => (
          <button key={t} type="button" onClick={() => onChange(t)}>
            {t}
          </button>
        ))}
      </div>
      <ErrorLine error={ask.error} />
    </div>
  );
}
