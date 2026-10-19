"""Read-only API over eval output, for the React run viewer.

This is a separate app from the factory test station on purpose: eval output
contains ground truth (the injected fault), and the station API must never
expose it. The agent only ever talks to the station.

Layout it reads (see ``eval/run_eval.py`` and ``agent/graph.py``)::

    <results_dir>/<eval name>/results.json
    <results_dir>/<eval name>/runs/<mode>/<run_id>.json
    <results_dir>/runs/<run_id>.json          single agent CLI runs

If ``web/dist`` exists (``npm run build``), the app also serves the viewer.

Usage:
    python -m backend.results_api --results eval/results --port 5001
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from flask import Blueprint, Flask, abort, current_app, jsonify, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_DIR = ROOT / "eval" / "results"
DEFAULT_WEB_DIST = ROOT / "web" / "dist"
CLI_RUNS = "runs"

# Names come from URLs; allow only plain file names so nothing escapes the results dir.
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

bp = Blueprint("results", __name__, url_prefix="/api")


def _results_dir() -> Path:
    path: Path = current_app.config["RESULTS_DIR"]
    return path


def _safe(name: str) -> str:
    if not _SAFE.match(name) or ".." in name:
        abort(404)
    return name


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        abort(404)
    except json.JSONDecodeError:
        abort(422, description=f"invalid JSON: {path.name}")


def eval_summary(name: str, report: dict[str, Any]) -> dict[str, Any]:
    """Condense one ``results.json`` into a row for the eval list."""
    return {
        "name": name,
        "created_at": report.get("created_at"),
        "model": report.get("model"),
        "n": report.get("n"),
        "seed": report.get("seed"),
        "is_mock": report.get("model") == "rule-based-mock",
        "modes": {
            mode: {"n": m.get("n"), "accuracy": m.get("accuracy"), "mean_tool_calls": m.get("tool_calls", {}).get("mean")}
            for mode, m in (report.get("modes") or {}).items()
        },
    }


@bp.get("/evals")
def list_evals() -> Any:
    """List eval result directories that contain a ``results.json``, newest first."""
    rows = []
    root = _results_dir()
    if root.is_dir():
        for d in root.iterdir():
            f = d / "results.json"
            if d.is_dir() and _SAFE.match(d.name) and f.is_file():
                try:
                    rows.append(eval_summary(d.name, json.loads(f.read_text())))
                except json.JSONDecodeError:
                    continue
    rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return jsonify({"evals": rows})


@bp.get("/evals/<name>")
def get_eval(name: str) -> Any:
    """Return one eval's full ``results.json``."""
    return jsonify(_read_json(_results_dir() / _safe(name) / "results.json"))


@bp.get("/evals/<name>/runs/<mode>/<run_id>")
def get_eval_run(name: str, mode: str, run_id: str) -> Any:
    """Return one run trace from an eval, including ground truth and score."""
    path = _results_dir() / _safe(name) / "runs" / _safe(mode) / f"{_safe(run_id)}.json"
    return jsonify(_read_json(path))


@bp.get("/traces")
def list_traces() -> Any:
    """List single agent runs written by ``python -m agent.graph`` (no ground truth)."""
    rows = []
    d = _results_dir() / CLI_RUNS
    if d.is_dir():
        for f in d.glob("*.json"):
            try:
                t = json.loads(f.read_text())
            except json.JSONDecodeError:
                continue
            final = t.get("final") or {}
            rows.append(
                {
                    "run_id": t.get("run_id", f.stem),
                    "started_at": t.get("started_at"),
                    "model": (t.get("agent") or {}).get("model"),
                    "predicted": final.get("root_cause"),
                    "tool_calls": (t.get("totals") or {}).get("tool_calls"),
                    "test_time_s": (t.get("totals") or {}).get("test_time_s"),
                    "stop_reason": t.get("stop_reason"),
                }
            )
    rows.sort(key=lambda r: r["started_at"] or "", reverse=True)
    return jsonify({"traces": rows})


@bp.get("/traces/<run_id>")
def get_trace(run_id: str) -> Any:
    """Return one single-run trace."""
    return jsonify(_read_json(_results_dir() / CLI_RUNS / f"{_safe(run_id)}.json"))


def create_results_app(results_dir: Path | None = None, web_dist: Path | None = None) -> Flask:
    """Build the viewer backend over ``results_dir`` (default ``EVAL_RESULTS_DIR`` or ``eval/results``)."""
    app = Flask(__name__, static_folder=None)
    app.json.sort_keys = False  # type: ignore[attr-defined]
    app.config["RESULTS_DIR"] = Path(results_dir or os.environ.get("EVAL_RESULTS_DIR") or DEFAULT_RESULTS_DIR)
    app.register_blueprint(bp)

    @app.errorhandler(404)
    def not_found(err: Any) -> Any:
        return jsonify({"error": "not found"}), 404

    dist = Path(web_dist or DEFAULT_WEB_DIST)
    if dist.is_dir():

        @app.get("/")
        @app.get("/<path:path>")
        def static_files(path: str = "index.html") -> Any:
            if path.startswith("api/"):
                abort(404)
            if not (dist / path).is_file():
                path = "index.html"
            return send_from_directory(dist, path)

    return app


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--results", type=Path, default=None, help="Eval results directory.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5001)
    a = p.parse_args(argv)
    create_results_app(a.results).run(host=a.host, port=a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
