"""Measure retriever accuracy on queries built from real simulator output.

For each fault and seed, run the full test suite on a simulated unit and turn
the results into a plain query. Two query styles are measured:

- ``failures``: failing tests and their failure messages only.
- ``full_dump``: the same, followed by the names of passing tests.

No LLM is involved, so this isolates the retriever. Reports top-1 and top-3
hit rate per retriever and query style.

Usage:
    python -m eval.retrieval_eval --seeds 50 --out eval/results/retrieval.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.retrieval import RETRIEVERS, get_retriever
from backend.simulator.drone import TEST_SPECS, SimulatedDrone
from backend.simulator.faults import FAULTS

QUERY_STYLES = ("failures", "full_dump")


def suite_query(unit: SimulatedDrone, style: str = "failures") -> str:
    """Summarize one full-suite run as text, the way a simple script would."""
    failed, passed = [], []
    for name in TEST_SPECS:
        out = unit.run_test(name)
        if out.passed:
            passed.append(name)
        else:
            failed.append(f"{name} FAILED: " + "; ".join(out.failures))
    text = " ".join(failed)
    if style == "full_dump":
        text += " PASSED: " + ", ".join(passed)
    return text


def run(seeds: int) -> dict[str, Any]:
    """Return top-1/top-3 rates and per-fault top-1 rates per retriever and query style."""
    report: dict[str, Any] = {"n_queries_per_style": len(FAULTS) * seeds, "seeds_per_fault": seeds, "results": {}}
    for style in QUERY_STYLES:
        queries = [(f, suite_query(SimulatedDrone(f, seed=s), style)) for f in sorted(FAULTS) for s in range(seeds)]
        report["results"][style] = {name: _score(name, queries, seeds) for name in sorted(RETRIEVERS)}
    return report


def _score(name: str, queries: list[tuple[str, str]], seeds: int) -> dict[str, Any]:
    r = get_retriever(name)
    top1 = top3 = 0
    per_fault: dict[str, int] = {f: 0 for f in FAULTS}
    for fid, q in queries:
        codes = [m.record.root_cause_code for m in r.search(q, k=3)]
        if codes[:1] == [fid]:
            top1 += 1
            per_fault[fid] += 1
        top3 += fid in codes
    return {
        "top1": round(top1 / len(queries), 4),
        "top3": round(top3 / len(queries), 4),
        "per_fault_top1": {f: round(c / seeds, 4) for f, c in sorted(per_fault.items())},
    }


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=50)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    report = run(args.seeds)
    report["command"] = "python -m eval.retrieval_eval " + " ".join(sys.argv[1:] if argv is None else argv)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
