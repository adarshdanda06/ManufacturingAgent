import type { EvalReport, EvalRow, Trace, TraceRow } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new ApiError(`${res.status} ${res.statusText} for ${path}`, res.status);
  return (await res.json()) as T;
}

const enc = encodeURIComponent;
// Eval names can be nested (model/mode); keep the slashes as path separators.
const encName = (name: string) => name.split("/").map(enc).join("/");

export const api = {
  evals: () => get<{ evals: EvalRow[] }>("/api/evals").then((r) => r.evals),
  evalReport: (name: string) => get<EvalReport>(`/api/evals/${encName(name)}`),
  evalRun: (name: string, mode: string, runId: string) =>
    get<Trace>(`/api/evals/${encName(name)}/runs/${enc(mode)}/${enc(runId)}`),
  traces: () => get<{ traces: TraceRow[] }>("/api/traces").then((r) => r.traces),
  trace: (runId: string) => get<Trace>(`/api/traces/${enc(runId)}`),
};
