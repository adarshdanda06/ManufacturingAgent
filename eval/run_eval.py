"""Batch evaluation of the triage agent against simulator ground truth.

Generates N units balanced across every fault plus HEALTHY, runs the agent on
each one with and without the failure library (same units in both modes), and
scores the diagnosis against the injected fault. Writes per-run traces, a
results JSON, and a markdown summary.

Only this harness knows the ground truth. It creates each unit itself, hands
the agent the unit ID alone, and attaches the truth to the trace afterwards.

Usage:
    python -m eval.run_eval --n 60 --seed 7 --concurrency 4
    python -m eval.run_eval --n 15 --llm mock --modes library   # plumbing check only
"""

from __future__ import annotations

import argparse
import json
import random
import shlex
import threading
import statistics
import sys
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.graph import AgentConfig, TriageAgent, make_llm
from agent.llm import LLM
from agent.tools import FlaskTransport
from backend.app import create_app
from backend.simulator.faults import ALL_FAULT_IDS, FAULTS, HEALTHY

RESULTS_DIR = Path(__file__).resolve().parent / "results"
MODES = {"library": True, "no_library": False}


@dataclass(frozen=True)
class Scenario:
    """One unit to diagnose. ``fault_id`` is ground truth and never reaches the agent."""

    index: int
    fault_id: str
    unit_seed: int


def make_scenarios(n: int, seed: int) -> list[Scenario]:
    """Return ``n`` scenarios cycling through every label, shuffled with ``seed``.

    Labels are balanced to within one unit of each other.
    """
    rng = random.Random(seed)
    labels = [ALL_FAULT_IDS[i % len(ALL_FAULT_IDS)] for i in range(n)]
    rng.shuffle(labels)
    return [Scenario(i, f, rng.randrange(1_000_000)) for i, f in enumerate(labels)]


def _expected_rework(fault_id: str) -> str:
    return "none" if fault_id == HEALTHY else FAULTS[fault_id].rework_action


def run_one(sc: Scenario, mode: str, app: Any, llm: LLM, cfg: AgentConfig) -> dict[str, Any]:
    """Create the unit, run the agent, and return its trace with ground truth and score."""
    transport = FlaskTransport(app)
    status, body = transport.request("POST", "/units", {"fault_id": sc.fault_id, "seed": sc.unit_seed})
    if status != 201:
        raise RuntimeError(f"unit creation failed: {body}")
    unit_id = body["unit_id"]
    unit, _ = app.extensions["unit_store"].get(unit_id)
    truth = {
        "fault_id": sc.fault_id,
        "unit_seed": sc.unit_seed,
        "target": unit.target_label,
        "rework_action": _expected_rework(sc.fault_id),
    }
    run_id = f"{mode}-{sc.index:04d}"
    try:
        trace = TriageAgent(llm, transport, cfg).run(unit_id, run_id=run_id)
    except Exception as exc:  # keep the batch going; the run counts as incorrect
        trace = {
            "run_id": run_id, "unit_id": unit_id, "final": None, "rework_result": None, "steps": [],
            "stop_reason": "crash", "errors": [f"{type(exc).__name__}: {exc}", traceback.format_exc(limit=3)],
            "totals": {"tool_calls": 0, "tests_run": 0, "test_time_s": 0.0, "llm_calls": 0,
                       "input_tokens": 0, "output_tokens": 0},
        }
    final = trace.get("final") or {}
    predicted = final.get("root_cause", "UNKNOWN")
    rework = trace.get("rework_result") or {}
    if sc.fault_id == HEALTHY:
        rework_ok = (final.get("recommended_rework") or {}).get("action") == "none"
    else:
        rework_ok = bool(rework.get("suite_passed"))
    trace["mode"] = mode
    trace["scenario_index"] = sc.index
    trace["ground_truth"] = truth
    trace["score"] = {"predicted": predicted, "correct": predicted == sc.fault_id, "rework_fixed_unit": rework_ok}
    return trace


def _stats(xs: list[float]) -> dict[str, float]:
    if not xs:
        return {"mean": 0.0, "median": 0.0}
    return {"mean": round(statistics.fmean(xs), 3), "median": round(statistics.median(xs), 3)}


def summarize(traces: list[dict[str, Any]], price_in: float | None, price_out: float | None) -> dict[str, Any]:
    """Aggregate metrics for one mode."""
    n = len(traces)
    correct = sum(t["score"]["correct"] for t in traces)
    per_fault: dict[str, dict[str, Any]] = {}
    for fid in ALL_FAULT_IDS:
        ts = [t for t in traces if t["ground_truth"]["fault_id"] == fid]
        if ts:
            c = sum(t["score"]["correct"] for t in ts)
            per_fault[fid] = {"n": len(ts), "correct": c, "accuracy": round(c / len(ts), 4)}
    confusions = Counter(
        (t["ground_truth"]["fault_id"], t["score"]["predicted"]) for t in traces if not t["score"]["correct"]
    )
    tok_in = sum(t["totals"]["input_tokens"] for t in traces)
    tok_out = sum(t["totals"]["output_tokens"] for t in traces)
    cost = None
    if price_in is not None and price_out is not None:
        cost = round((tok_in * price_in + tok_out * price_out) / 1e6, 4)
    return {
        "n": n,
        "correct": correct,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "rework_fixed_unit_rate": round(sum(t["score"]["rework_fixed_unit"] for t in traces) / n, 4) if n else 0.0,
        "per_fault": per_fault,
        "confusion_pairs": [
            {"truth": a, "predicted": b, "count": c} for (a, b), c in sorted(confusions.items(), key=lambda x: (-x[1], x[0]))
        ],
        "tool_calls": _stats([t["totals"]["tool_calls"] for t in traces]),
        "tests_run": _stats([t["totals"]["tests_run"] for t in traces]),
        "test_time_s": _stats([t["totals"]["test_time_s"] for t in traces]),
        "stop_reasons": dict(Counter(t.get("stop_reason") or "none" for t in traces)),
        "tokens": {
            "input_total": tok_in,
            "output_total": tok_out,
            "per_run_mean": round((tok_in + tok_out) / n, 1) if n else 0.0,
        },
        "cost_usd_estimate": cost,
    }


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render_markdown(report: dict[str, Any]) -> str:
    """Render the results JSON as a markdown summary."""
    m = report["modes"]
    lines = [
        "# Factory Triage Agent evaluation",
        "",
        f"- Run at: {report['created_at']}",
        f"- Model: `{report['model']}`",
        f"- Scenarios: {report['n']} units per mode (balanced over {len(ALL_FAULT_IDS)} labels), seed {report['seed']}",
        f"- Limits: {report['config']['max_steps']} tool calls, {report['config']['time_budget_s']:.0f} s test time",
        "",
        "Command:",
        "",
        "```",
        report["command"],
        "```",
        "",
    ]
    if report["model"] == "rule-based-mock":
        lines += ["> Rule-based mock LLM. These numbers check the pipeline only and are not agent results.", ""]
    lines += [
        "## Overall",
        "",
        "| Metric | " + " | ".join(m) + (" | Delta (library minus none) |" if len(m) == 2 else ""),
        "|---|" + "---|" * len(m) + ("---|" if len(m) == 2 else ""),
    ]
    rows = [
        ("Diagnosis accuracy", lambda s: s["accuracy"], _pct),
        ("Rework fixed unit", lambda s: s["rework_fixed_unit_rate"], _pct),
        ("Mean tool calls", lambda s: s["tool_calls"]["mean"], lambda v: f"{v:.2f}"),
        ("Median tool calls", lambda s: s["tool_calls"]["median"], lambda v: f"{v:.1f}"),
        ("Mean tests run", lambda s: s["tests_run"]["mean"], lambda v: f"{v:.2f}"),
        ("Mean test time (s)", lambda s: s["test_time_s"]["mean"], lambda v: f"{v:.1f}"),
        ("Median test time (s)", lambda s: s["test_time_s"]["median"], lambda v: f"{v:.1f}"),
        ("Tokens per run (mean)", lambda s: s["tokens"]["per_run_mean"], lambda v: f"{v:.0f}"),
    ]
    for label, get, fmt in rows:
        vals = [get(s) for s in m.values()]
        row = f"| {label} | " + " | ".join(fmt(v) for v in vals) + " |"
        if len(vals) == 2:
            d = vals[0] - vals[1]
            row += f" {'+' if d >= 0 else ''}{(_pct(d) if fmt is _pct else f'{d:.2f}')} |"
        lines.append(row)
    costs = [s["cost_usd_estimate"] for s in m.values()]
    if all(c is not None for c in costs):
        lines.append("| Token cost estimate (USD, all runs) | " + " | ".join(f"${c:.4f}" for c in costs) + " |" + (" |" if len(m) == 2 else ""))
    lines += ["", "## Per-fault accuracy", "", "| Fault | n | " + " | ".join(m) + " |", "|---|---|" + "---|" * len(m)]
    for fid in ALL_FAULT_IDS:
        cells = [m[k]["per_fault"].get(fid) for k in m]
        if cells[0] is None:
            continue
        lines.append(f"| {fid} | {cells[0]['n']} | " + " | ".join(_pct(c["accuracy"]) for c in cells if c) + " |")
    for mode, s in m.items():
        lines += ["", f"## Confusion pairs ({mode})", ""]
        if not s["confusion_pairs"]:
            lines.append("None.")
            continue
        lines += ["| Truth | Predicted | Count |", "|---|---|---|"]
        lines += [f"| {c['truth']} | {c['predicted']} | {c['count']} |" for c in s["confusion_pairs"]]
    lines += ["", "## Stop reasons", ""]
    lines += [f"- {mode}: " + ", ".join(f"{k} {v}" for k, v in s["stop_reasons"].items()) for mode, s in m.items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=30, help="Units per mode.")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--modes", nargs="+", choices=list(MODES), default=list(MODES))
    ap.add_argument("--llm", choices=["gemini", "mock"], default="gemini")
    ap.add_argument("--model", default=None)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--time-budget", type=float, default=180.0)
    ap.add_argument("--price-in", type=float, default=None, help="USD per 1M input tokens, for the cost estimate.")
    ap.add_argument("--price-out", type=float, default=None, help="USD per 1M output tokens, for the cost estimate.")
    ap.add_argument("--out", type=Path, default=None, help="Output directory (default eval/results/<timestamp>).")
    a = ap.parse_args(argv)

    command = "python -m eval.run_eval " + shlex.join(sys.argv[1:] if argv is None else argv)
    created = datetime.now(timezone.utc)
    out = a.out or RESULTS_DIR / created.strftime("%Y%m%dT%H%M%SZ")
    llm = make_llm(a.llm, a.model)
    scenarios = make_scenarios(a.n, a.seed)
    app = create_app()

    report: dict[str, Any] = {
        "created_at": created.isoformat(),
        "command": command,
        "model": llm.model_name,
        "n": a.n,
        "seed": a.seed,
        "concurrency": a.concurrency,
        "config": asdict(AgentConfig(max_steps=a.max_steps, time_budget_s=a.time_budget)),
        "price_per_mtok": {"input": a.price_in, "output": a.price_out},
        "modes": {},
        "runs": [],
    }
    for mode in a.modes:
        cfg = AgentConfig(max_steps=a.max_steps, time_budget_s=a.time_budget, use_library=MODES[mode])
        runs_dir = out / "runs" / mode
        runs_dir.mkdir(parents=True, exist_ok=True)
        done = 0
        lock = threading.Lock()

        def job(sc: Scenario) -> dict[str, Any]:
            nonlocal done
            t = run_one(sc, mode, app, llm, cfg)
            (runs_dir / f"{t['run_id']}.json").write_text(json.dumps(t, indent=2))
            with lock:
                done += 1
            mark = "ok " if t["score"]["correct"] else "ERR"
            print(f"[{mode} {done}/{len(scenarios)}] {mark} truth={sc.fault_id} pred={t['score']['predicted']} "
                  f"calls={t['totals']['tool_calls']} time={t['totals']['test_time_s']:.0f}s", flush=True)
            return t

        with ThreadPoolExecutor(max_workers=max(1, a.concurrency)) as pool:
            traces = list(pool.map(job, scenarios))
        report["modes"][mode] = summarize(traces, a.price_in, a.price_out)
        report["runs"] += [
            {
                "run_id": t["run_id"],
                "mode": mode,
                "path": str((runs_dir / f"{t['run_id']}.json").relative_to(out)),
                "truth": t["ground_truth"]["fault_id"],
                "predicted": t["score"]["predicted"],
                "correct": t["score"]["correct"],
                "rework_fixed_unit": t["score"]["rework_fixed_unit"],
                "tool_calls": t["totals"]["tool_calls"],
                "test_time_s": t["totals"]["test_time_s"],
                "stop_reason": t.get("stop_reason"),
            }
            for t in traces
        ]
    (out / "results.json").write_text(json.dumps(report, indent=2))
    md = render_markdown(report)
    (out / "summary.md").write_text(md)
    print(md)
    print(f"Wrote {out / 'results.json'} and {out / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
