import { secs, testSpans } from "../format";
import type { Trace } from "../types";

/** Station test time spent per test, against the run's time budget. */
export function BudgetBar({ trace }: { trace: Trace }) {
  const spans = testSpans(trace);
  const used = spans.reduce((a, s) => a + s.cost, 0);
  const budget = trace.agent?.config.time_budget_s ?? Math.max(used, 1);
  const scale = Math.max(budget, used);
  return (
    <div>
      <div className="budget" role="img" aria-label={`${secs(used)} of ${secs(budget)} test budget used`}>
        {spans.map((s) => (
          <div
            key={s.step}
            className={"seg" + (s.passed ? "" : " fail")}
            style={{ left: `${(100 * s.start) / scale}%`, width: `${(100 * s.cost) / scale}%` }}
            title={`Step ${s.step}: ${s.test} (${secs(s.cost)}, ${s.passed ? "passed" : "failed"})`}
          />
        ))}
      </div>
      <div className="budget-legend">
        <span>
          {secs(used)} used of {secs(budget)} budget · {spans.length} tests ·{" "}
          <span className="swatch" style={{ background: "var(--series-1)" }} />
          passed <span className="swatch" style={{ background: "var(--critical)", marginLeft: 8 }} />
          failed
        </span>
        <span>{secs(budget)}</span>
      </div>
    </div>
  );
}
