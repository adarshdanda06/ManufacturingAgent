// Shapes of the JSON written by agent/graph.py (traces) and eval/run_eval.py (results).

export type StopReason = "proposed" | "budget_forced" | "llm_error" | "crash" | null;
export type ToolName = "list_tests" | "run_test" | "search_failure_library" | "propose_rework";

export type Readings = Record<string, unknown>;

export interface Hypothesis {
  root_cause_code: string;
  confidence: number;
  rationale: string;
}

export interface TestSpec {
  name: string;
  subsystem: string;
  description: string;
  cost_s: number;
}

export interface TestResult {
  unit_id: string;
  test_name: string;
  passed: boolean;
  cost_s: number;
  readings: Readings;
  failures: string[];
  run_index: number;
  unit_total_test_time_s: number;
}

export interface LibraryMatch {
  id: string;
  title: string;
  subsystem: string;
  symptom_summary: string;
  root_cause_code: string;
  root_cause: string;
  rework_action: string | null;
  rework_notes?: string;
  occurrences?: number;
  score: number;
}

export interface ReworkResult {
  unit_id: string;
  action: string;
  target: string;
  suite_passed: boolean;
  failing_tests: string[];
  cost_s: number;
  applied?: boolean;
}

/** A tool result is one of the station responses, or an error from the act node. */
export type StepResult =
  | { unit_id: string; tests: TestSpec[] }
  | TestResult
  | { retriever: string; matches: LibraryMatch[] }
  | ReworkResult
  | { error: string }
  | Record<string, unknown>;

export interface Step {
  step: number;
  thought: string;
  tool: ToolName | string;
  args: Record<string, unknown>;
  result: StepResult;
  test_time_s: number;
  observation: string;
  hypotheses: Hypothesis[];
}

export interface Evidence {
  step: number;
  test_name: string;
  run_index: number;
  passed: boolean;
  failures: string[];
  readings: Readings;
}

export interface FinalAnswer {
  root_cause: string;
  confidence: number;
  recommended_rework: { action: string; target: string | null };
  evidence: Evidence[];
}

export interface Totals {
  tool_calls: number;
  tests_run: number;
  test_time_s: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
}

export interface AgentConfig {
  max_steps: number;
  time_budget_s: number;
  use_library: boolean;
  retriever: string;
  top_k: number;
}

export interface Trace {
  run_id: string;
  unit_id: string;
  agent?: { model: string; config: AgentConfig };
  started_at?: string;
  duration_s?: number;
  stop_reason: StopReason;
  final: FinalAnswer | null;
  rework_result: ReworkResult | null;
  totals: Totals;
  errors: string[];
  steps: Step[];
  // Added by the eval harness only.
  mode?: string;
  scenario_index?: number;
  ground_truth?: { fault_id: string; unit_seed: number; target: string | null; rework_action: string };
  score?: { predicted: string; correct: boolean; rework_fixed_unit: boolean };
}

export interface Stat {
  mean: number;
  median: number;
}

export interface ModeMetrics {
  n: number;
  correct: number;
  accuracy: number;
  rework_fixed_unit_rate: number;
  per_fault: Record<string, { n: number; correct: number; accuracy: number }>;
  confusion_pairs: { truth: string; predicted: string; count: number }[];
  tool_calls: Stat;
  tests_run: Stat;
  test_time_s: Stat;
  stop_reasons: Record<string, number>;
  tokens: { input_total: number; output_total: number; per_run_mean: number };
  cost_usd_estimate: number | null;
}

export interface RunRef {
  run_id: string;
  mode: string;
  path: string;
  truth: string;
  predicted: string;
  correct: boolean;
  rework_fixed_unit: boolean;
  tool_calls: number;
  test_time_s: number;
  stop_reason: StopReason | string;
}

export interface EvalReport {
  created_at: string;
  command: string;
  model: string;
  n: number;
  seed: number;
  concurrency: number;
  config: AgentConfig;
  price_per_mtok: { input: number | null; output: number | null };
  modes: Record<string, ModeMetrics>;
  runs: RunRef[];
}

export interface EvalRow {
  name: string;
  created_at: string | null;
  model: string | null;
  n: number | null;
  seed: number | null;
  is_mock: boolean;
  modes: Record<string, { n: number; accuracy: number; mean_tool_calls: number | null }>;
}

export interface TraceRow {
  run_id: string;
  started_at: string | null;
  model: string | null;
  predicted: string | null;
  tool_calls: number | null;
  test_time_s: number | null;
  stop_reason: string | null;
}
