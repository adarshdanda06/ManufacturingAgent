import { api } from "../api";
import { Loadable, StopBadge } from "../components/common";
import { modeLabel, num, pct, secs, shortDate } from "../format";
import { href } from "../router";
import { useAsync } from "../useAsync";

export function HomePage() {
  const evals = useAsync(api.evals, []);
  const traces = useAsync(api.traces, []);
  return (
    <>
      <div className="page-head">
        <h1>Runs</h1>
        <div className="sub">
          Eval batches from <code>python -m eval.run_eval</code> and single runs from <code>python -m agent.graph</code>.
        </div>
      </div>
      <section className="card">
        <h2>Eval batches</h2>
        <Loadable state={evals}>
          {(rows) =>
            rows.length === 0 ? (
              <div className="empty">
                No eval results yet. Run <code>python -m eval.run_eval --n 15 --llm mock</code> for a plumbing check.
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Run at</th>
                    <th>Model</th>
                    <th className="num">Units per mode</th>
                    <th>Accuracy by mode</th>
                    <th className="num">Mean tool calls</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.name} className="clickable" onClick={() => (window.location.hash = href("eval", r.name))}>
                      <td>
                        <a href={href("eval", r.name)}>{r.name}</a>
                      </td>
                      <td>{shortDate(r.created_at)}</td>
                      <td>
                        <code>{r.model}</code> {r.is_mock && <span className="badge warn">mock, not agent results</span>}
                      </td>
                      <td className="num">{r.n}</td>
                      <td>
                        {Object.entries(r.modes).map(([mode, m]) => (
                          <div key={mode}>
                            {modeLabel(mode)}: <strong>{pct(m.accuracy)}</strong> <span className="muted">(n={m.n})</span>
                          </div>
                        ))}
                      </td>
                      <td className="num">
                        {Object.entries(r.modes).map(([mode, m]) => (
                          <div key={mode}>{num(m.mean_tool_calls)}</div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          }
        </Loadable>
      </section>
      <section className="card">
        <h2>Single agent runs</h2>
        <Loadable state={traces}>
          {(rows) =>
            rows.length === 0 ? (
              <div className="empty">
                None yet. Try <code>python -m agent.graph --fault MOTOR_BEARING_DEGRADED --seed 4 --llm mock</code>.
              </div>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Started</th>
                    <th>Model</th>
                    <th>Diagnosis</th>
                    <th className="num">Tool calls</th>
                    <th className="num">Test time</th>
                    <th>Stop</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.run_id} className="clickable" onClick={() => (window.location.hash = href("trace", r.run_id))}>
                      <td>
                        <a href={href("trace", r.run_id)}>{r.run_id}</a>
                      </td>
                      <td>{shortDate(r.started_at)}</td>
                      <td>
                        <code>{r.model}</code>
                      </td>
                      <td>
                        <code>{r.predicted ?? "none"}</code>
                      </td>
                      <td className="num">{r.tool_calls}</td>
                      <td className="num">{secs(r.test_time_s)}</td>
                      <td>
                        <StopBadge reason={r.stop_reason} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          }
        </Loadable>
      </section>
    </>
  );
}
