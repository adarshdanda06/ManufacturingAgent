"""Tests for the read-only results API used by the viewer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from backend.results_api import create_results_app
from eval import run_eval


@pytest.fixture(scope="module")
def results_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("results")
    rc = run_eval.main(["--n", "3", "--llm", "mock", "--concurrency", "1", "--out", str(root / "mock-eval")])
    assert rc == 0
    (root / "runs").mkdir()
    trace = json.loads((root / "mock-eval" / "runs" / "library" / "library-0000.json").read_text())
    for k in ("mode", "scenario_index", "ground_truth", "score"):
        trace.pop(k)
    trace["run_id"] = "cli-run"
    (root / "runs" / "cli-run.json").write_text(json.dumps(trace))
    (root / "broken").mkdir()
    (root / "broken" / "results.json").write_text("{not json")
    return root


@pytest.fixture()
def client(results_dir: Path, tmp_path: Path) -> FlaskClient:
    return create_results_app(results_dir, web_dist=tmp_path / "no-dist").test_client()


def test_list_evals(client: FlaskClient) -> None:
    rows = client.get("/api/evals").get_json()["evals"]
    assert [r["name"] for r in rows] == ["mock-eval"]
    row = rows[0]
    assert row["is_mock"] is True
    assert set(row["modes"]) == {"library", "no_library"}
    assert row["modes"]["library"]["n"] == 3


def test_get_eval_and_run(client: FlaskClient) -> None:
    report = client.get("/api/evals/mock-eval").get_json()
    assert len(report["runs"]) == 6
    ref = report["runs"][0]
    mode, run_id = ref["path"].split("/")[1], ref["run_id"]
    trace = client.get(f"/api/evals/mock-eval/runs/{mode}/{run_id}").get_json()
    assert trace["run_id"] == run_id
    assert trace["ground_truth"]["fault_id"] == ref["truth"]
    assert trace["steps"][0]["tool"] == "list_tests"


def test_traces(client: FlaskClient) -> None:
    rows = client.get("/api/traces").get_json()["traces"]
    assert [r["run_id"] for r in rows] == ["cli-run"]
    assert client.get("/api/traces/cli-run").get_json()["run_id"] == "cli-run"


@pytest.mark.parametrize(
    "url",
    [
        "/api/evals/nope",
        "/api/evals/..%2F..%2Fetc",
        "/api/evals/mock-eval/runs/library/..",
        "/api/evals/mock-eval/runs/library/missing",
        "/api/traces/.hidden",
        "/api/unknown",
    ],
)
def test_not_found_and_traversal(client: FlaskClient, url: str) -> None:
    assert client.get(url).status_code == 404


def test_serves_built_viewer(results_dir: Path, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>viewer</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    c = create_results_app(results_dir, web_dist=dist).test_client()
    assert b"viewer" in c.get("/").data
    assert b"viewer" in c.get("/eval/mock-eval").data
    assert b"console" in c.get("/assets/app.js").data
    assert c.get("/api/unknown").status_code == 404
    assert c.get("/api/evals").status_code == 200
