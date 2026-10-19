import { describe, expect, it } from "vitest";
import { invalidRuns, openByDefault, pct, summarizeStep, testSpans } from "./format";
import { parseHash, href } from "./router";
import type { ModeMetrics, Step, Trace } from "./types";

const runStep = (step: number, name: string, passed: boolean, cost: number): Step => ({
  step,
  thought: "",
  tool: "run_test",
  args: { test_name: name },
  result: {
    unit_id: "U-1",
    test_name: name,
    passed,
    cost_s: cost,
    readings: {},
    failures: passed ? [] : ["motor_3 current 6.60 A outside 3.4-5.0"],
    run_index: 0,
    unit_total_test_time_s: 0,
  },
  test_time_s: 0,
  observation: "",
  hypotheses: [],
});

describe("router", () => {
  it("parses routes and round-trips names with special characters", () => {
    expect(parseHash("")).toEqual({ page: "home" });
    expect(parseHash("#/eval/lite-library")).toEqual({ page: "eval", name: "lite-library" });
    expect(parseHash(href("eval", "a b", "library", "library-0001"))).toEqual({
      page: "evalRun",
      name: "a b",
      mode: "library",
      runId: "library-0001",
    });
    expect(parseHash("#/trace/run-1")).toEqual({ page: "trace", runId: "run-1" });
    expect(parseHash("#/nope/x/y")).toEqual({ page: "notFound" });
  });
});

describe("format", () => {
  it("formats percentages", () => {
    expect(pct(0.8333)).toBe("83.3%");
    expect(pct(null)).toBe("n/a");
  });

  it("summarizes each tool", () => {
    expect(summarizeStep(runStep(2, "motor_spin_test", false, 30))).toBe("motor_spin_test failed (1 failure)");
    expect(summarizeStep(runStep(2, "imu_static", true, 20))).toBe("imu_static passed");
    const err = { ...runStep(3, "x", true, 0), result: { error: "unknown test: x" } };
    expect(summarizeStep(err)).toBe("Error: unknown test: x");
    const search: Step = {
      ...runStep(4, "", true, 0),
      tool: "search_failure_library",
      result: { retriever: "bm25", matches: [{ id: "FL-003", root_cause_code: "MOTOR_WINDING_SHORT" }] },
    };
    expect(summarizeStep(search)).toBe("Top match FL-003 (MOTOR_WINDING_SHORT)");
    const rework: Step = {
      ...runStep(5, "", true, 0),
      tool: "propose_rework",
      result: { action: "replace_motor", target: "motor_3", suite_passed: true, failing_tests: [] },
    };
    expect(summarizeStep(rework)).toBe("replace_motor on motor_3: suite passed");
  });

  it("lays out test spans back to back", () => {
    const trace = { steps: [runStep(2, "a", true, 5), runStep(3, "b", false, 30)] } as unknown as Trace;
    expect(testSpans(trace)).toEqual([
      { step: 2, test: "a", start: 0, cost: 5, passed: true },
      { step: 3, test: "b", start: 5, cost: 30, passed: false },
    ]);
  });

  it("opens failing and cited steps by default", () => {
    expect(openByDefault(runStep(2, "a", true, 5), false)).toBe(false);
    expect(openByDefault(runStep(2, "a", true, 5), true)).toBe(true);
    expect(openByDefault(runStep(2, "a", false, 5), false)).toBe(true);
  });

  it("counts runs that ended without a diagnosis", () => {
    const m = { stop_reasons: { proposed: 8, llm_error: 22 } } as unknown as ModeMetrics;
    expect(invalidRuns(m)).toBe(22);
  });
});
