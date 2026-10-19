import type { ReactNode } from "react";
import type { AsyncState } from "../useAsync";

export function Loadable<T>({ state, children }: { state: AsyncState<T>; children: (data: T) => ReactNode }) {
  if (state.status === "loading") return <div className="empty">Loading...</div>;
  if (state.status === "error")
    return (
      <div className="card error">
        Could not load data: {state.error.message}. Is the results server running (
        <code>python -m backend.results_api</code>)?
      </div>
    );
  return <>{children(state.data)}</>;
}

export function Outcome({ correct }: { correct: boolean | undefined }) {
  if (correct === undefined) return <span className="badge">no ground truth</span>;
  return correct ? <span className="badge good">✓ Correct</span> : <span className="badge bad">✗ Wrong</span>;
}

const STOP_LABELS: Record<string, string> = {
  proposed: "proposed rework",
  budget_forced: "budget forced",
  llm_error: "LLM error",
  crash: "crashed",
};

export function StopBadge({ reason }: { reason: string | null | undefined }) {
  const r = reason ?? "none";
  const cls = r === "proposed" ? "badge" : r === "budget_forced" ? "badge warn" : "badge bad";
  return <span className={cls}>{STOP_LABELS[r] ?? r}</span>;
}

export function Stat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="stat">
      <div className="v">{value}</div>
      <div className="l">{label}</div>
    </div>
  );
}

export function Crumbs({ items }: { items: [string, string | null][] }) {
  return (
    <div className="crumbs">
      {items.map(([label, link], i) => (
        <span key={i}>
          {i > 0 && " / "}
          {link ? <a href={link}>{label}</a> : label}
        </span>
      ))}
    </div>
  );
}
