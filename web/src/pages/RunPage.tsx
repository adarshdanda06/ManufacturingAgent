import { useState } from "react";
import { api } from "../api";
import { BudgetBar } from "../components/BudgetBar";
import { Crumbs, Loadable, Outcome, Stat, StopBadge } from "../components/common";
import { StepCard } from "../components/StepCard";
import { modeLabel, openByDefault, pct, secs, shortDate } from "../format";
import { href } from "../router";
import type { Trace } from "../types";
import { useAsync } from "../useAsync";

export type RunSource = { kind: "eval"; name: string; mode: string; runId: string } | { kind: "trace"; runId: string };

export function RunPage({ source }: { source: RunSource }) {
  const key = JSON.stringify(source);
  const state = useAsync(
    () => (source.kind === "eval" ? api.evalRun(source.name, source.mode, source.runId) : api.trace(source.runId)),
    [key],
  );
  const crumbs: [string, string | null][] =
    source.kind === "eval"
      ? [["All runs", href()], [source.name, href("eval", source.name)], [source.runId, null]]
      : [["All runs", href()], [source.runId, null]];
  return (
    <>
      <Crumbs items={crumbs} />
      <Loadable state={state}>{(t) => <RunBody trace={t} />}</Loadable>
    </>
  );
}

function RunBody({ trace }: { trace: Trace }) {
  const [expandAll, setExpandAll] = useState<boolean | null>(null);
  const final = trace.final;
  const truth = trace.ground_truth;
  const evidenceSteps = new Set(final?.evidence.map((e) => e.step) ?? []);
  const rework = trace.rework_result;
  const targetOk = truth && final ? (truth.target ?? null) === (final.recommended_rework.target ?? null) : undefined;
  return (
    <>
      <div className="page-head">
        <h1>
          {trace.run_id} <Outcome correct={trace.score?.correct} /> <StopBadge reason={trace.stop_reason} />
        </h1>
        <div className="sub">
          Unit <code>{trace.unit_id}</code>
          {trace.mode && <> · {modeLabel(trace.mode)}</>}
          {trace.agent && (
            <>
              {" "}
              · <code>{trace.agent.model}</code> · retriever {trace.agent.config.retriever}
            </>
          )}
          {trace.started_at && <> · {shortDate(trace.started_at)}</>}
          {trace.duration_s != null && <> · wall time {trace.duration_s.toFixed(1)} s</>}
        </div>
      </div>

      <div className="grid2">
        <section className="card">
          <h2>Agent diagnosis</h2>
          {final ? (
            <dl className="kv">
              <dt>Root cause</dt>
              <dd className="code-big">{final.root_cause}</dd>
              <dt>Confidence</dt>
              <dd>{pct(final.confidence, 0)}</dd>
              <dt>Rework</dt>
              <dd>
                <code>{final.recommended_rework.action}</code>
                {final.recommended_rework.target && (
                  <>
                    {" "}
                    on <code>{final.recommended_rework.target}</code>
                  </>
                )}
              </dd>
              <dt>Evidence</dt>
              <dd>
                {final.evidence.length === 0
                  ? "none cited"
                  : final.evidence.map((e) => (
                      <span key={e.step} style={{ marginRight: 8 }}>
                        <code>{e.test_name}</code> (step {e.step}, {e.passed ? "pass" : "fail"})
                      </span>
                    ))}
              </dd>
              <dt>After rework</dt>
              <dd>
                {!rework ? (
                  <span className="muted">not applied</span>
                ) : rework.action === "none" ? (
                  "no rework applied"
                ) : rework.suite_passed ? (
                  <span className="badge good">full suite passed</span>
                ) : (
                  <>
                    <span className="badge bad">suite failing</span> <code>{rework.failing_tests.join(", ")}</code>
                  </>
                )}
              </dd>
            </dl>
          ) : (
            <div className="muted">No final answer.</div>
          )}
        </section>
        <section className="card">
          <h2>Ground truth (injected fault)</h2>
          {truth ? (
            <dl className="kv">
              <dt>Fault</dt>
              <dd className="code-big">{truth.fault_id}</dd>
              <dt>Position</dt>
              <dd>
                <code>{truth.target ?? "n/a"}</code>
                {targetOk === false && truth.target && (
                  <span className="badge bad" style={{ marginLeft: 8 }}>
                    agent named {final?.recommended_rework.target ?? "none"}
                  </span>
                )}
              </dd>
              <dt>Expected rework</dt>
              <dd>
                <code>{truth.rework_action}</code>
              </dd>
              <dt>Unit seed</dt>
              <dd>{truth.unit_seed}</dd>
              <dt>Score</dt>
              <dd>
                <Outcome correct={trace.score?.correct} />{" "}
                {trace.score?.rework_fixed_unit ? (
                  <span className="badge good">rework fixed unit</span>
                ) : (
                  <span className="badge bad">rework did not fix unit</span>
                )}
              </dd>
            </dl>
          ) : (
            <div className="muted">
              Single agent run: ground truth is only recorded by the eval harness. The station never reveals the fault.
            </div>
          )}
        </section>
      </div>

      <section className="card">
        <h2>Station time</h2>
        <div className="stats" style={{ marginBottom: 12 }}>
          <Stat value={trace.totals.tool_calls} label={`tool calls (max ${trace.agent?.config.max_steps ?? "?"})`} />
          <Stat value={trace.totals.tests_run} label="tests run" />
          <Stat value={secs(trace.totals.test_time_s)} label="test time" />
          <Stat value={trace.totals.llm_calls} label="LLM calls" />
          <Stat value={(trace.totals.input_tokens + trace.totals.output_tokens).toLocaleString()} label="tokens" />
        </div>
        <BudgetBar trace={trace} />
      </section>

      {trace.errors.length > 0 && (
        <section className="card">
          <h2>Errors</h2>
          <ul>
            {trace.errors.map((e, i) => (
              <li key={i}>
                <code style={{ whiteSpace: "pre-wrap" }}>{e}</code>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "8px 0 12px" }}>
          <h2 style={{ margin: 0 }}>Reasoning trace</h2>
          <span className="muted">plan, act, observe, decide · ringed steps were cited as evidence</span>
          <span style={{ marginLeft: "auto" }}>
            <a href="#" onClick={(e) => (e.preventDefault(), setExpandAll(true))}>
              Expand all
            </a>{" "}
            ·{" "}
            <a href="#" onClick={(e) => (e.preventDefault(), setExpandAll(false))}>
              Collapse all
            </a>
          </span>
        </div>
        <div className="timeline">
          {trace.steps.map((s) => (
            <StepCard
              key={`${s.step}-${expandAll}`}
              step={s}
              evidence={evidenceSteps.has(s.step)}
              truth={truth?.fault_id}
              defaultOpen={expandAll ?? openByDefault(s, evidenceSteps.has(s.step))}
            />
          ))}
        </div>
      </section>
    </>
  );
}
