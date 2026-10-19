import { useState } from "react";
import { isTestResult, stepError, summarizeStep } from "../format";
import type { LibraryMatch, ReworkResult, Step, TestSpec } from "../types";
import { Hypotheses } from "./Hypotheses";
import { ReadingsView } from "./Readings";

const TOOL_LABEL: Record<string, string> = {
  list_tests: "list_tests",
  run_test: "run_test",
  search_failure_library: "search_library",
  propose_rework: "propose_rework",
};

export function StepCard({
  step,
  evidence,
  truth,
  defaultOpen,
}: {
  step: Step;
  evidence: boolean;
  truth?: string;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const err = stepError(step);
  const r = step.result;
  const failed = isTestResult(r) && !r.passed;
  return (
    <div className="step">
      <div className={"step-num" + (evidence ? " evidence" : "")} title={evidence ? "Cited as evidence" : undefined}>
        {step.step}
      </div>
      <div className="step-body">
        <div className="step-head" onClick={() => setOpen(!open)}>
          <span className="badge tool">{TOOL_LABEL[step.tool] ?? step.tool}</span>
          {err && <span className="badge bad">error</span>}
          {isTestResult(r) && (r.passed ? <span className="badge good">pass</span> : <span className="badge bad">fail</span>)}
          {evidence && <span className="badge">evidence</span>}
          <span className="summary">{summarizeStep(step)}</span>
          <span className="time">
            station time {Math.round(step.test_time_s)} s {open ? "▾" : "▸"}
          </span>
        </div>
        {step.thought && <p className="thought">{step.thought}</p>}
        {open && (
          <div className="step-detail">
            {Object.keys(step.args).length > 0 && (
              <div>
                <div className="section-label">Arguments</div>
                <code>{JSON.stringify(step.args)}</code>
              </div>
            )}
            {failed && (
              <div>
                <div className="section-label">Failures</div>
                <ul className="failures">
                  {r.failures.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </div>
            )}
            {isTestResult(r) && (
              <div>
                <div className="section-label">Readings (run {r.run_index})</div>
                <ReadingsView readings={r.readings} />
              </div>
            )}
            {step.tool === "list_tests" && Array.isArray((r as { tests?: TestSpec[] }).tests) && (
              <TestCatalog tests={(r as { tests: TestSpec[] }).tests} />
            )}
            {step.tool === "search_failure_library" && Array.isArray((r as { matches?: LibraryMatch[] }).matches) && (
              <Matches matches={(r as { matches: LibraryMatch[] }).matches} truth={truth} />
            )}
            {step.tool === "propose_rework" && !err && <Rework r={r as ReworkResult} />}
            {step.observation && (
              <div>
                <div className="section-label">Observation</div>
                <p className="observation">{step.observation}</p>
              </div>
            )}
            {step.hypotheses.length > 0 && (
              <div>
                <div className="section-label">Hypotheses after this step</div>
                <Hypotheses items={step.hypotheses} truth={truth} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function TestCatalog({ tests }: { tests: TestSpec[] }) {
  return (
    <table className="readings">
      <thead>
        <tr>
          <th>Test</th>
          <th>Subsystem</th>
          <th className="num">Cost</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
        {tests.map((t) => (
          <tr key={t.name}>
            <td className="mono">{t.name}</td>
            <td>{t.subsystem}</td>
            <td className="num">{t.cost_s} s</td>
            <td>{t.description}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Matches({ matches, truth }: { matches: LibraryMatch[]; truth?: string }) {
  return (
    <div>
      <div className="section-label">Library matches</div>
      <table className="readings">
        <thead>
          <tr>
            <th>Record</th>
            <th>Title</th>
            <th>Root cause</th>
            <th className="num">Score</th>
          </tr>
        </thead>
        <tbody>
          {matches.map((m) => (
            <tr key={m.id} title={m.symptom_summary}>
              <td className="mono">{m.id}</td>
              <td>{m.title}</td>
              <td className="mono">
                {m.root_cause_code}
                {m.root_cause_code === truth && <span className="muted"> (truth)</span>}
              </td>
              <td className="num">{m.score.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Rework({ r }: { r: ReworkResult }) {
  return (
    <div>
      <div className="section-label">Rework result</div>
      {r.action === "none" ? (
        <span>No rework applied.</span>
      ) : (
        <span>
          {r.suite_passed ? <span className="badge good">suite passed</span> : <span className="badge bad">suite failing</span>}{" "}
          {r.failing_tests.length > 0 && (
            <>
              still failing: <code>{r.failing_tests.join(", ")}</code>
            </>
          )}
        </span>
      )}
    </div>
  );
}
