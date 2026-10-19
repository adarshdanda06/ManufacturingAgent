"""Tests for the LangGraph triage agent, using scripted and rule-based LLMs."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent.graph import AgentConfig, TriageAgent, write_trace
from agent.llm import GeminiLLM, LLMError, RuleBasedLLM, ScriptedLLM
from agent.tools import FlaskTransport
from backend.app import create_app
from backend.simulator.faults import ALL_FAULT_IDS


class RecordingTransport(FlaskTransport):
    """Flask transport that keeps every request and response."""

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self.log: list[tuple[str, str, Any, Any]] = []

    def request(self, method: str, path: str, json: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        status, body = super().request(method, path, json)
        self.log.append((method, path, json, body))
        return status, body


def new_unit(transport: FlaskTransport, fault_id: str | None, seed: int = 0) -> str:
    status, body = transport.request("POST", "/units", {"fault_id": fault_id, "seed": seed})
    assert status == 201
    return str(body["unit_id"])


def plan(tool: str, **kw: Any) -> dict[str, Any]:
    return {"thought": f"next: {tool}", "tool": tool, **kw}


def obs(code: str, conf: float) -> dict[str, Any]:
    return {"summary": f"looks like {code}", "hypotheses": [{"root_cause_code": code, "confidence": conf, "rationale": "r"}]}


@pytest.fixture()
def transport() -> RecordingTransport:
    return RecordingTransport(create_app())


def test_scripted_run_produces_structured_final_and_trace(transport: RecordingTransport) -> None:
    uid = new_unit(transport, "CAMERA_RIBBON_FAULT", seed=2)
    llm = ScriptedLLM(
        [
            plan("list_tests"),
            plan("run_test", test_name="camera_selftest"),
            obs("CAMERA_RIBBON_FAULT", 0.8),
            plan(
                "propose_rework",
                root_cause="CAMERA_RIBBON_FAULT",
                confidence=0.8,
                rework_action="reseat_camera_ribbon",
                evidence_tests=["camera_selftest", "not_a_test"],
            ),
        ]
    )
    trace = TriageAgent(llm, transport).run(uid)

    final = trace["final"]
    assert set(final) == {"root_cause", "confidence", "recommended_rework", "evidence"}
    assert final["root_cause"] == "CAMERA_RIBBON_FAULT"
    assert final["recommended_rework"] == {"action": "reseat_camera_ribbon", "target": None}
    # Evidence is the recorded test result, and unknown citations are dropped.
    assert [e["test_name"] for e in final["evidence"]] == ["camera_selftest"]
    assert final["evidence"][0]["passed"] is False
    assert final["evidence"][0]["readings"]["csi_crc_errors"] > 5
    assert trace["rework_result"]["suite_passed"] is True
    assert trace["stop_reason"] == "proposed"
    assert trace["totals"]["tool_calls"] == 3
    assert trace["totals"]["test_time_s"] == 15.0
    for s in trace["steps"]:
        assert {"step", "thought", "tool", "args", "result", "observation", "hypotheses", "test_time_s"} <= set(s)
    assert trace["steps"][1]["hypotheses"][0]["root_cause_code"] == "CAMERA_RIBBON_FAULT"
    json.dumps(trace)


def test_step_cap_forces_final_answer(transport: RecordingTransport) -> None:
    uid = new_unit(transport, "MOTOR_DEAD")
    script: list[Any] = []
    for _ in range(3):
        script += [plan("run_test", test_name="power_on_selftest"), obs("UNKNOWN", 0.2)]
    script.append(plan("propose_rework", root_cause="UNKNOWN", confidence=0.2, rework_action="none"))
    llm = ScriptedLLM(script)
    trace = TriageAgent(llm, transport, AgentConfig(max_steps=4)).run(uid)
    assert trace["totals"]["tool_calls"] == 4
    assert trace["stop_reason"] == "budget_forced"
    plan_schemas = [name for name, _ in llm.calls if name != "Observation"]
    assert plan_schemas[-1] == "FinalDecision"
    assert "budget is exhausted" in llm.calls[-1][1][-1].content


def test_time_budget_rejects_expensive_test_and_forces_final(transport: RecordingTransport) -> None:
    uid = new_unit(transport, "BATTERY_HIGH_IR")
    llm = ScriptedLLM(
        [
            plan("run_test", test_name="battery_load_test"),  # 60 s > 30 s budget, rejected
            plan("run_test", test_name="imu_static"),  # 20 s, leaves 10 s
            obs("UNKNOWN", 0.1),
            plan("run_test", test_name="battery_rest_check"),  # 5 s, leaves 5 s
            obs("UNKNOWN", 0.1),
            plan("run_test", test_name="power_on_selftest"),  # 5 s, leaves 0 s
            obs("UNKNOWN", 0.1),
            plan("propose_rework", root_cause="UNKNOWN", confidence=0.1, rework_action="none"),
        ]
    )
    trace = TriageAgent(llm, transport, AgentConfig(time_budget_s=30.0)).run(uid)
    first = trace["steps"][0]
    assert "only 30 s left" in first["result"]["error"]
    assert trace["totals"]["test_time_s"] == 30.0
    assert trace["stop_reason"] == "budget_forced"
    # The rejected test never reached the station.
    assert not any(p.endswith("/battery_load_test") for _, p, _, _ in transport.log)


def test_no_library_mode_hides_search_tool(transport: RecordingTransport) -> None:
    uid = new_unit(transport, None)
    llm = ScriptedLLM([plan("propose_rework", root_cause="HEALTHY", confidence=0.5, rework_action="none")])
    agent = TriageAgent(llm, transport, AgentConfig(use_library=False))
    trace = agent.run(uid)
    assert "search_failure_library" not in agent.tools
    assert "search_failure_library" not in llm.calls[0][1][0].content
    assert trace["agent"]["config"]["use_library"] is False
    bad = ScriptedLLM([plan("search_failure_library", query="x")] * 2 + [plan("propose_rework", rework_action="none")])
    trace = TriageAgent(bad, transport, AgentConfig(use_library=False)).run(new_unit(transport, None))
    # Schema validation rejects the hidden tool; the agent falls back instead of calling it.
    assert trace["stop_reason"] == "llm_error"
    assert all(s["tool"] != "search_failure_library" for s in trace["steps"])


def test_library_search_returns_records(transport: RecordingTransport) -> None:
    uid = new_unit(transport, "COMPASS_INTERFERENCE")
    llm = ScriptedLLM(
        [
            plan("search_failure_library", query="heading deviation grows with throttle"),
            obs("COMPASS_INTERFERENCE", 0.6),
            plan("propose_rework", root_cause="COMPASS_INTERFERENCE", confidence=0.6, rework_action="reroute_compass_wiring"),
        ]
    )
    trace = TriageAgent(llm, transport).run(uid)
    matches = trace["steps"][0]["result"]["matches"]
    assert len(matches) == 3 and matches[0]["root_cause_code"] == "COMPASS_INTERFERENCE"
    assert trace["totals"]["test_time_s"] == 0.0


def test_agent_never_sees_fault_id(transport: RecordingTransport) -> None:
    uid = new_unit(transport, "ESC_DESYNC", seed=5)
    transport.log.clear()
    trace = TriageAgent(RuleBasedLLM(), transport).run(uid)
    for _, _, req, resp in transport.log:
        assert "fault" not in json.dumps(req).lower()
        assert "fault" not in json.dumps(resp).lower()
    assert "ESC_DESYNC" not in json.dumps([s["result"] for s in trace["steps"] if s["tool"] != "search_failure_library"])


def test_llm_error_falls_back_to_top_hypothesis(transport: RecordingTransport) -> None:
    uid = new_unit(transport, "IMU_GYRO_MISCAL")
    llm = ScriptedLLM(
        [
            plan("run_test", test_name="imu_static"),
            obs("IMU_GYRO_MISCAL", 0.7),
            LLMError("boom"),
            LLMError("boom again"),
        ]
    )
    trace = TriageAgent(llm, transport).run(uid)
    assert trace["stop_reason"] == "llm_error"
    assert trace["final"]["root_cause"] == "IMU_GYRO_MISCAL"
    assert trace["final"]["recommended_rework"]["action"] == "none"
    assert trace["errors"] == ["plan: boom again"]


@pytest.mark.parametrize("use_library", [True, False])
def test_rule_based_mock_completes_every_fault_within_caps(transport: RecordingTransport, use_library: bool) -> None:
    cfg = AgentConfig(use_library=use_library)
    for i, fid in enumerate(ALL_FAULT_IDS):
        trace = TriageAgent(RuleBasedLLM(), transport, cfg).run(new_unit(transport, fid, seed=i))
        assert trace["final"] is not None
        assert trace["totals"]["tool_calls"] <= cfg.max_steps
        assert trace["totals"]["test_time_s"] <= cfg.time_budget_s


def test_write_trace(tmp_path: Any, transport: RecordingTransport) -> None:
    trace = TriageAgent(RuleBasedLLM(), transport).run(new_unit(transport, None), run_id="run-test")
    path = write_trace(trace, tmp_path)
    assert json.loads(path.read_text())["run_id"] == "run-test"


def test_gemini_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(LLMError):
        GeminiLLM()
