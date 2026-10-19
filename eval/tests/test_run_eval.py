"""Tests for the batch evaluation harness (rule-based mock LLM only)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from backend.simulator.faults import ALL_FAULT_IDS
from eval.run_eval import main, make_scenarios


def test_scenarios_are_balanced_and_reproducible() -> None:
    a = make_scenarios(47, seed=3)
    assert a == make_scenarios(47, seed=3)
    assert a != make_scenarios(47, seed=4)
    counts = Counter(s.fault_id for s in a)
    assert set(counts) == set(ALL_FAULT_IDS)
    assert max(counts.values()) - min(counts.values()) <= 1


def test_eval_writes_results_summary_and_traces(tmp_path: Path) -> None:
    out = tmp_path / "ev"
    assert main(["--n", "15", "--seed", "1", "--llm", "mock", "--concurrency", "3", "--out", str(out)]) == 0
    report = json.loads((out / "results.json").read_text())
    assert set(report["modes"]) == {"library", "no_library"}
    assert report["command"].startswith("python -m eval.run_eval --n 15 --seed 1")
    for s in report["modes"].values():
        assert s["n"] == 15
        assert 0.0 <= s["accuracy"] <= 1.0
        assert sum(f["n"] for f in s["per_fault"].values()) == 15
        assert s["correct"] == sum(f["correct"] for f in s["per_fault"].values())
        wrong = sum(c["count"] for c in s["confusion_pairs"])
        assert wrong == s["n"] - s["correct"]
    # Both modes see the same units.
    by_mode = {m: sorted(r["truth"] for r in report["runs"] if r["mode"] == m) for m in report["modes"]}
    assert by_mode["library"] == by_mode["no_library"]
    run = json.loads((out / report["runs"][0]["path"]).read_text())
    assert run["ground_truth"]["fault_id"] == report["runs"][0]["truth"]
    md = (out / "summary.md").read_text()
    assert "not agent results" in md and "Per-fault accuracy" in md and report["command"] in md
    assert "—" not in md
