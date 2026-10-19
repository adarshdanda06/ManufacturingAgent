import { useMemo, useState } from "react";
import { api } from "../api";
import { Crumbs, Loadable, Outcome, Stat, StopBadge } from "../components/common";
import { PerFaultChart } from "../components/PerFaultChart";
import { invalidRuns, modeLabel, num, pct, secs, shortDate } from "../format";
import { href } from "../router";
import type { EvalReport, ModeMetrics } from "../types";
import { useAsync } from "../useAsync";

export function EvalPage({ name }: { name: string }) {
  const state = useAsync(() => api.evalReport(name), [name]);
  return (
    <>
      <Crumbs items={[["All runs", href()], [name, null]]} />
      <Loadable state={state}>{(r) => <EvalBody name={name} report={r} />}</Loadable>
    </>
  );
}

type Row = [string, (m: ModeMetrics) => number, (v: number) => string, boolean];

const METRICS: Row[] = [
  ["Diagnosis accuracy", (m) => m.accuracy, (v) => pct(v), true],
  ["Rework fixed unit", (m) => m.rework_fixed_unit_rate, (v) => pct(v), true],
  ["Mean tool calls", (m) => m.tool_calls.mean, (v) => num(v), false],
  ["Median tool calls", (m) => m.tool_calls.median, (v) => num(v, 1), false],
  ["Mean tests run", (m) => m.tests_run.mean, (v) => num(v), false],
  ["Mean test time (s)", (m) => m.test_time_s.mean, (v) => num(v, 1), false],
  ["Tokens per run (mean)", (m) => m.tokens.per_run_mean, (v) => v.toFixed(0), false],
];

function EvalBody({ name, report }: { name: string; report: EvalReport }) {
  const modes = Object.keys(report.modes);
  const isMock = report.model === "rule-based-mock";
  const twoModes = modes.length === 2;
  return (
    <>
      <div className="page-head">
        <h1>{name}</h1>
        <div className="sub">
          <code>{report.model}</code> · {report.n} units per mode · seed {report.seed} · limits{" "}
          {report.config.max_steps} tool calls, {secs(report.config.time_budget_s)} test time · {shortDate(report.created_at)}
        </div>
        <pre className="cmd mono">{report.command}</pre>
      </div>

      {isMock && (
        <div className="banner warn">
          Rule-based mock LLM. These numbers check the pipeline only and are not agent results.
        </div>
      )}
      {modes.map((m) => {
        const bad = invalidRuns(report.modes[m]);
        return bad > 0 ? (
          <div className="banner warn" key={m}>
            {modeLabel(m)}: {bad} of {report.modes[m].n} runs ended on an LLM error or crash and are scored as wrong,
            so this accuracy understates the agent. Rerun before quoting it.
          </div>
        ) : null;
      })}

      <div className={twoModes ? "grid2" : ""} style={{ marginBottom: 16 }}>
        {modes.map((m) => {
          const s = report.modes[m];
          return (
            <div className="card" key={m} style={{ marginBottom: 0 }}>
              <h2>{modeLabel(m)}</h2>
              <div className="stats">
                <Stat value={pct(s.accuracy)} label={`accuracy (${s.correct}/${s.n})`} />
                <Stat value={pct(s.rework_fixed_unit_rate)} label="rework fixed unit" />
                <Stat value={num(s.tool_calls.mean)} label="mean tool calls" />
                <Stat value={secs(s.test_time_s.mean)} label="mean test time" />
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid2">
        <section className="card">
          <h2>Overall</h2>
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                {modes.map((m) => (
                  <th className="num" key={m}>
                    {modeLabel(m)}
                  </th>
                ))}
                {twoModes && <th className="num">Delta</th>}
              </tr>
            </thead>
            <tbody>
              {METRICS.map(([label, get, fmt, isPct]) => {
                const vals = modes.map((m) => get(report.modes[m]));
                const d = twoModes ? vals[0] - vals[1] : 0;
                return (
                  <tr key={label}>
                    <td>{label}</td>
                    {vals.map((v, i) => (
                      <td className="num" key={i}>
                        {fmt(v)}
                      </td>
                    ))}
                    {twoModes && (
                      <td className="num">
                        {d >= 0 ? "+" : ""}
                        {isPct ? pct(d) : fmt(d)}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {twoModes && <div className="muted" style={{ marginTop: 6 }}>Delta is {modeLabel(modes[0])} minus {modeLabel(modes[1])}.</div>}
          <h3 style={{ marginTop: 16 }}>Stop reasons</h3>
          {modes.map((m) => (
            <div key={m} style={{ marginBottom: 4 }}>
              {modeLabel(m)}:{" "}
              {Object.entries(report.modes[m].stop_reasons).map(([k, v]) => (
                <span key={k} style={{ marginRight: 8 }}>
                  <StopBadge reason={k} /> {v}
                </span>
              ))}
            </div>
          ))}
        </section>
        <section className="card">
          <h2>Per-fault accuracy</h2>
          <PerFaultChart modes={report.modes} />
        </section>
      </div>

      <section className="card">
        <h2>Confusions</h2>
        <div className={twoModes ? "grid2" : ""}>
          {modes.map((m) => (
            <div key={m}>
              <h3>{modeLabel(m)}</h3>
              {report.modes[m].confusion_pairs.length === 0 ? (
                <div className="muted">None.</div>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Truth</th>
                      <th>Predicted</th>
                      <th className="num">Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.modes[m].confusion_pairs.map((c) => (
                      <tr key={c.truth + c.predicted}>
                        <td className="mono">{c.truth}</td>
                        <td className="mono">{c.predicted}</td>
                        <td className="num">{c.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      </section>

      <RunTable name={name} report={report} />
    </>
  );
}

function RunTable({ name, report }: { name: string; report: EvalReport }) {
  const [mode, setMode] = useState("all");
  const [outcome, setOutcome] = useState("all");
  const [fault, setFault] = useState("all");
  const faults = useMemo(() => [...new Set(report.runs.map((r) => r.truth))].sort(), [report]);
  const rows = report.runs.filter(
    (r) =>
      (mode === "all" || r.mode === mode) &&
      (fault === "all" || r.truth === fault) &&
      (outcome === "all" || (outcome === "correct") === r.correct),
  );
  return (
    <section className="card">
      <h2>Runs</h2>
      <div className="filters">
        <select value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Mode">
          <option value="all">All modes</option>
          {Object.keys(report.modes).map((m) => (
            <option key={m} value={m}>
              {modeLabel(m)}
            </option>
          ))}
        </select>
        <select value={outcome} onChange={(e) => setOutcome(e.target.value)} aria-label="Outcome">
          <option value="all">All outcomes</option>
          <option value="correct">Correct</option>
          <option value="wrong">Wrong</option>
        </select>
        <select value={fault} onChange={(e) => setFault(e.target.value)} aria-label="Injected fault">
          <option value="all">All injected faults</option>
          {faults.map((f) => (
            <option key={f}>{f}</option>
          ))}
        </select>
        <span className="muted">
          {rows.length} of {report.runs.length}
        </span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Mode</th>
            <th>Injected fault</th>
            <th>Diagnosis</th>
            <th>Outcome</th>
            <th>Rework</th>
            <th className="num">Tool calls</th>
            <th className="num">Test time</th>
            <th>Stop</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const link = href("eval", name, r.mode, r.run_id);
            return (
              <tr key={r.mode + r.run_id} className="clickable" onClick={() => (window.location.hash = link)}>
                <td>
                  <a href={link}>{r.run_id}</a>
                </td>
                <td>{modeLabel(r.mode)}</td>
                <td className="mono">{r.truth}</td>
                <td className="mono">{r.predicted}</td>
                <td>
                  <Outcome correct={r.correct} />
                </td>
                <td>{r.rework_fixed_unit ? <span className="badge good">fixed</span> : <span className="badge bad">not fixed</span>}</td>
                <td className="num">{r.tool_calls}</td>
                <td className="num">{secs(r.test_time_s)}</td>
                <td>
                  <StopBadge reason={r.stop_reason} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
