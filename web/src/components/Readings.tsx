import type { ReactNode } from "react";

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);

function scalar(v: unknown): string {
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(+v.toFixed(3));
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (v == null) return "n/a";
  return String(v);
}

function rowsTable(rows: Obj[], firstCol?: string[]): ReactNode {
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  return (
    <table>
      <thead>
        <tr>
          {firstCol && <th />}
          {keys.map((k) => (
            <th key={k}>{k}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {firstCol && <td className="key">{firstCol[i]}</td>}
            {keys.map((k) => (
              <td key={k} className="mono">
                {scalar(r[k])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function value(v: unknown): ReactNode {
  if (Array.isArray(v)) {
    if (v.length > 0 && v.every(isObj)) return rowsTable(v);
    return <span className="mono">{v.map(scalar).join(", ") || "none"}</span>;
  }
  if (isObj(v)) {
    const entries = Object.entries(v);
    if (entries.length > 0 && entries.every(([, x]) => isObj(x)))
      return rowsTable(
        entries.map(([, x]) => x as Obj),
        entries.map(([k]) => k),
      );
    return <ReadingsView readings={v} />;
  }
  return <span className="mono">{scalar(v)}</span>;
}

/** Render a test's readings: scalars as key/value rows, per-motor or per-bus data as small tables. */
export function ReadingsView({ readings }: { readings: Obj }) {
  return (
    <div className="readings">
      <table>
        <tbody>
          {Object.entries(readings).map(([k, v]) => (
            <tr key={k}>
              <td className="key">{k}</td>
              <td>{value(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
