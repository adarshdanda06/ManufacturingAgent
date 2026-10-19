"""Failure library and retriever tests."""

from __future__ import annotations

import json

import pytest

from agent.retrieval import (
    LIBRARY_PATH,
    RETRIEVERS,
    Bm25Retriever,
    Retriever,
    TfidfRetriever,
    get_retriever,
    load_library,
    tokenize,
)
from backend.simulator.faults import FAULTS, REWORK_ACTIONS

# Agent-style observation summaries, deliberately worded differently from the library.
QUERIES: dict[str, list[str]] = {
    "MOTOR_DEAD": [
        "motor_2 rpm 0 and current 0.04 A, cold. esc_2 back_emf_detected false, no sync errors.",
    ],
    "MOTOR_BEARING_DEGRADED": [
        "motor_3 current 5.6 A, others 4.2 A. rpm 9100 normal. temp 52 C below limit.",
    ],
    "MOTOR_WINDING_SHORT": [
        "motor_1 current 6.5 A, rpm 7600 below spec, temperature 70 C over limit.",
    ],
    "ESC_DESYNC": [
        "motor_4 rpm unstable around 5000 with huge rpm jitter. esc_4 sync errors 40, back-EMF detected. packet loss normal.",
    ],
    "CAN_TERMINATION_MISSING": [
        "packet loss 10 percent on all four ESCs, sync errors zero, motors spin fine. CAN termination 120 ohm.",
    ],
    "IMU_GYRO_MISCAL": [
        "imu_static gyro z bias 1.2 dps, no dropped samples, accel noise normal.",
    ],
    "I2C_CONNECTOR_LOOSE": [
        "imu dropped 45 of 1000 samples, gyro bias normal. compass read errors 8. I2C continuity intermittent.",
    ],
    "IMU_SENSOR_FAULT": [
        "imu dropped 30 samples, accel noise 3.4 mg elevated. compass read errors 0, harness I2C clean.",
    ],
    "BATTERY_WEAK_CELL": [
        "rest check cell 3 at 4.07 V vs 4.15, imbalance 0.08. under load cell imbalance 0.37 V.",
    ],
    "BATTERY_HIGH_IR": [
        "rest voltages balanced and normal. under 20 A load pack voltage 14.9 V low, internal resistance 84 mohm, cells balanced.",
    ],
    "CAMERA_RIBBON_FAULT": [
        "camera self test fail, sensor id ok, frame rate 21 fps, CSI CRC errors 150.",
    ],
    "CAMERA_SENSOR_DEAD": [
        "camera sensor id read failed at power on. camera frame rate 0, crc errors 0.",
    ],
    "COMPASS_INTERFERENCE": [
        "compass heading error 8 deg, field magnitude 52 uT. heading deviation increases with throttle to 26 deg at 75 percent.",
    ],
    "COMPASS_HARD_IRON": [
        "compass heading error 10 deg, field 56 uT. interference sweep passes, deviation constant with throttle.",
    ],
}


@pytest.fixture(scope="module", params=sorted(RETRIEVERS))
def retriever(request: pytest.FixtureRequest) -> Retriever:
    return get_retriever(request.param)


def test_library_size_and_schema() -> None:
    records = load_library()
    assert len(records) >= 20
    assert len({r.id for r in records}) == len(records)
    for r in records:
        assert r.symptom_summary and r.root_cause and r.occurrences > 0
        assert r.rework_action is None or r.rework_action in REWORK_ACTIONS


def test_library_covers_every_simulator_fault() -> None:
    codes = {r.root_cause_code for r in load_library()}
    assert set(FAULTS) <= codes


def test_library_has_decoys() -> None:
    decoys = {r.root_cause_code for r in load_library()} - set(FAULTS)
    assert len(decoys) >= 4


def test_library_is_valid_json_without_em_dashes() -> None:
    text = LIBRARY_PATH.read_text()
    json.loads(text)
    assert "—" not in text


def test_tokenize() -> None:
    toks = tokenize("Motor_3 draws HIGH current; RPM 9100 normal")
    assert "motor" in toks and "current" in toks and "rpm" in toks
    assert "9100" not in toks
    assert "rpm__normal" in toks


@pytest.mark.parametrize("fault_id", sorted(QUERIES))
def test_correct_record_in_top3(retriever: Retriever, fault_id: str) -> None:
    for q in QUERIES[fault_id]:
        top = [m.record.root_cause_code for m in retriever.search(q, k=3)]
        assert fault_id in top, (retriever.name, top)


def test_top1_accuracy_on_handwritten_queries(retriever: Retriever) -> None:
    hits = total = 0
    for fault_id, qs in QUERIES.items():
        for q in qs:
            total += 1
            hits += retriever.search(q, k=1)[0].record.root_cause_code == fault_id
    assert hits / total >= 0.85, (retriever.name, hits, total)


def test_search_respects_k_and_ordering(retriever: Retriever) -> None:
    res = retriever.search("motor current high rpm low temperature", k=5)
    assert 0 < len(res) <= 5
    scores = [m.score for m in res]
    assert scores == sorted(scores, reverse=True)


def test_empty_or_unrelated_query_returns_nothing(retriever: Retriever) -> None:
    assert retriever.search("", k=3) == []
    assert retriever.search("banana smoothie recipe", k=3) == []


def test_retrievers_are_swappable() -> None:
    recs = load_library()
    for impl in (TfidfRetriever(recs), Bm25Retriever(recs)):
        r: Retriever = impl
        res = r.search("camera self test fail, sensor id ok, frame rate low, csi crc errors high", k=2)
        assert res and res[0].record.subsystem == "camera"
        assert res[0].record.to_dict()["id"] == res[0].record.id


def test_unknown_retriever() -> None:
    with pytest.raises(KeyError):
        get_retriever("nope")


def test_benchmark_on_simulator_output_regression() -> None:
    """Failure-only queries built from real simulator runs keep the right record in the top 3."""
    from eval.retrieval_eval import run

    report = run(seeds=5)
    for name, res in report["results"]["failures"].items():
        assert res["top3"] >= 0.85, (name, res)
