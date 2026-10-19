import type { ModeMetrics, Step, TestResult, Trace } from "./types";

export const pct = (x: number | null | undefined, digits = 1): string =>
  x == null ? "n/a" : `${(100 * x).toFixed(digits)}%`;

export const secs = (x: number | null | undefined): string => (x == null ? "n/a" : `${Math.round(x)} s`);

export const num = (x: number | null | undefined, digits = 2): string => (x == null ? "n/a" : x.toFixed(digits));

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export const MODE_LABELS: Record<string, string> = {
  library: "With library",
  no_library: "Without library",
};

export const modeLabel = (mode: string): string => MODE_LABELS[mode] ?? mode;

export function isTestResult(r: unknown): r is TestResult {
  return typeof r === "object" && r !== null && "test_name" in r && "passed" in r;
}

export function stepError(step: Step): string | null {
  const r = step.result as { error?: unknown };
  return typeof r?.error === "string" ? r.error : null;
}

/** One line describing what a step did, for the collapsed timeline row. */
export function summarizeStep(step: Step): string {
  const err = stepError(step);
  if (err) return `Error: ${err}`;
  const r = step.result as Record<string, unknown>;
  switch (step.tool) {
    case "list_tests":
      return `Station offers ${Array.isArray(r.tests) ? r.tests.length : 0} tests`;
    case "run_test": {
      if (!isTestResult(r)) return "Test ran";
      const n = r.failures.length;
      return r.passed ? `${r.test_name} passed` : `${r.test_name} failed (${n} ${n === 1 ? "failure" : "failures"})`;
    }
    case "search_failure_library": {
      const m = Array.isArray(r.matches) ? (r.matches as { id: string; root_cause_code: string }[]) : [];
      return m.length ? `Top match ${m[0].id} (${m[0].root_cause_code})` : "No matches";
    }
    case "propose_rework": {
      const target = r.target ? ` on ${String(r.target)}` : "";
      if (r.action === "none") return "Proposed no rework";
      return `${String(r.action)}${target}: suite ${r.suite_passed ? "passed" : "still failing"}`;
    }
    default:
      return step.tool;
  }
}

export interface TestSpan {
  step: number;
  test: string;
  start: number;
  cost: number;
  passed: boolean;
}

/** Station time used by each run_test, in order, for the budget bar. */
export function testSpans(trace: Trace): TestSpan[] {
  const spans: TestSpan[] = [];
  let t = 0;
  for (const s of trace.steps) {
    if (s.tool !== "run_test" || !isTestResult(s.result)) continue;
    spans.push({ step: s.step, test: s.result.test_name, start: t, cost: s.result.cost_s, passed: s.result.passed });
    t += s.result.cost_s;
  }
  return spans;
}

/** Runs that ended for reasons other than a diagnosis; they are scored as wrong. */
export function invalidRuns(m: ModeMetrics): number {
  return Object.entries(m.stop_reasons)
    .filter(([k]) => k === "llm_error" || k === "crash")
    .reduce((acc, [, v]) => acc + v, 0);
}

/** Expand steps that carry the story: failures, errors, library lookups, the rework, and cited evidence. */
export function openByDefault(step: Step, evidence: boolean): boolean {
  if (step.tool === "list_tests") return false;
  if (step.tool !== "run_test" || evidence || stepError(step)) return true;
  return isTestResult(step.result) && !step.result.passed;
}
