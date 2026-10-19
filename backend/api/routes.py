"""HTTP routes for the simulated factory test station.

Test and rework results are built as protobuf messages (see
``backend/proto/test_result.proto``) and serialized to JSON at the boundary.
No response ever includes the injected fault ID: the agent must diagnose it.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from flask import Blueprint, Flask, current_app, jsonify, request
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message

from backend.proto import test_result_pb2 as pb
from backend.simulator.drone import TEST_SPECS, SimulatedDrone
from backend.simulator.faults import ALL_FAULT_IDS, REWORK_ACTIONS

bp = Blueprint("factory", __name__)


class UnitStore:
    """Thread-safe in-memory registry of simulated units."""

    def __init__(self) -> None:
        self._units: dict[str, SimulatedDrone] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def create(self, fault_id: str | None, seed: int) -> str:
        """Create a unit and return its opaque ID."""
        unit = SimulatedDrone(fault_id=fault_id, seed=seed)
        unit_id = f"U-{uuid.uuid4().hex[:10]}"
        with self._lock:
            self._units[unit_id] = unit
            self._locks[unit_id] = threading.Lock()
        return unit_id

    def get(self, unit_id: str) -> tuple[SimulatedDrone, threading.Lock] | None:
        """Return the unit and its lock, or None if unknown."""
        with self._lock:
            u = self._units.get(unit_id)
            return (u, self._locks[unit_id]) if u is not None else None


def _store() -> UnitStore:
    store: UnitStore = current_app.extensions["unit_store"]
    return store


def _to_json(msg: Message) -> dict[str, Any]:
    return MessageToDict(msg, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)


def _err(msg: str, code: int) -> tuple[Any, int]:
    return jsonify({"error": msg}), code


@bp.get("/health")
def health() -> Any:
    """Liveness probe."""
    return jsonify({"status": "ok"})


@bp.post("/units")
def create_unit() -> Any:
    """Create a unit. Body: ``{"fault_id": str | null, "seed": int}`` (both optional)."""
    body = request.get_json(silent=True) or {}
    fault_id = body.get("fault_id")
    seed = body.get("seed", 0)
    if fault_id is not None and fault_id not in ALL_FAULT_IDS:
        return _err(f"unknown fault_id: {fault_id}", 400)
    if not isinstance(seed, int) or isinstance(seed, bool):
        return _err("seed must be an integer", 400)
    unit_id = _store().create(fault_id, seed)
    return jsonify({"unit_id": unit_id}), 201


@bp.get("/units/<unit_id>")
def get_unit(unit_id: str) -> Any:
    """Return station-visible unit status (never the fault)."""
    found = _store().get(unit_id)
    if found is None:
        return _err("unit not found", 404)
    unit, lock = found
    with lock:
        return jsonify(
            {
                "unit_id": unit_id,
                "total_test_time_s": unit.total_test_time_s,
                "test_runs": dict(unit.run_counts),
                "rework_count": len(unit.rework_history),
            }
        )


@bp.get("/units/<unit_id>/tests")
def list_tests(unit_id: str) -> Any:
    """List tests available on the station, with their simulated cost."""
    if _store().get(unit_id) is None:
        return _err("unit not found", 404)
    catalog = pb.TestCatalog(
        unit_id=unit_id,
        tests=[
            pb.TestSpec(name=s.name, subsystem=s.subsystem, description=s.description, cost_s=s.cost_s)
            for s in TEST_SPECS.values()
        ],
    )
    return jsonify(_to_json(catalog))


@bp.post("/units/<unit_id>/tests/<test_name>")
def run_test(unit_id: str, test_name: str) -> Any:
    """Run one test and return a ``TestResult`` as JSON."""
    found = _store().get(unit_id)
    if found is None:
        return _err("unit not found", 404)
    if test_name not in TEST_SPECS:
        return _err(f"unknown test: {test_name}", 404)
    unit, lock = found
    with lock:
        out = unit.run_test(test_name)
        total = unit.total_test_time_s
    msg = pb.TestResult(
        unit_id=unit_id,
        test_name=out.test_name,
        passed=out.passed,
        cost_s=out.cost_s,
        failures=out.failures,
        run_index=out.run_index,
        unit_total_test_time_s=total,
    )
    msg.readings.update(out.readings)
    return jsonify(_to_json(msg))


@bp.get("/rework/actions")
def rework_actions() -> Any:
    """List rework actions the station supports."""
    return jsonify({"actions": [{"action": k, "description": v} for k, v in REWORK_ACTIONS.items()]})


@bp.post("/units/<unit_id>/rework")
def rework(unit_id: str) -> Any:
    """Apply a rework action. Body: ``{"action": str, "target": str | null}``."""
    found = _store().get(unit_id)
    if found is None:
        return _err("unit not found", 404)
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    target = body.get("target")
    if action not in REWORK_ACTIONS:
        return _err(f"unknown rework action: {action}", 400)
    unit, lock = found
    with lock:
        out = unit.apply_rework(action, target)
    msg = pb.ReworkResult(
        unit_id=unit_id,
        action=out.action,
        target=out.target or "",
        suite_passed=out.suite_passed,
        failing_tests=out.failing_tests,
        cost_s=out.cost_s,
    )
    return jsonify(_to_json(msg))


def register(app: Flask) -> None:
    """Attach the blueprint and a fresh unit store to ``app``."""
    app.extensions["unit_store"] = UnitStore()
    app.register_blueprint(bp)
