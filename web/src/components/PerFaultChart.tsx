import { modeLabel, pct } from "../format";
import type { ModeMetrics } from "../types";

const SERIES = ["var(--series-1)", "var(--series-2)"];

/** Horizontal bars of per-fault accuracy, one bar per mode, faults in catalog order. */
export function PerFaultChart({ modes }: { modes: Record<string, ModeMetrics> }) {
  const names = Object.keys(modes);
  const faults = Object.keys(modes[names[0]]?.per_fault ?? {});
  return (
    <div>
      {names.length > 1 && (
        <div className="legend">
          {names.map((m, i) => (
            <span key={m}>
              <span className="swatch" style={{ background: SERIES[i % SERIES.length] }} />
              {modeLabel(m)}
            </span>
          ))}
        </div>
      )}
      {faults.map((f) => (
        <div className="pf-row" key={f}>
          <div className="pf-label">{f}</div>
          <div className="pf-bars">
            {names.map((m, i) => {
              const cell = modes[m].per_fault[f];
              if (!cell) return null;
              return (
                <div
                  className="pf-bar"
                  key={m}
                  title={`${f}, ${modeLabel(m)}: ${cell.correct} of ${cell.n} correct (${pct(cell.accuracy)})`}
                >
                  <div className="pf-track">
                    <div
                      className="pf-fill"
                      style={{ width: `${100 * cell.accuracy}%`, background: SERIES[i % SERIES.length] }}
                    />
                  </div>
                  <div className="pf-val">
                    {cell.correct}/{cell.n}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
      <div className="pf-axis">
        <span />
        <div className="ticks">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
      </div>
    </div>
  );
}
