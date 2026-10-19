"""HTTP API tests for the factory test station."""

from __future__ import annotations

import json

import pytest
from flask.testing import FlaskClient

from backend.app import create_app
from backend.simulator.drone import TEST_SPECS
from backend.simulator.faults import FAULTS


@pytest.fixture()
def client() -> FlaskClient:
    return create_app().test_client()


def make_unit(client: FlaskClient, fault_id: str | None = None, seed: int = 0) -> str:
    resp = client.post("/units", json={"fault_id": fault_id, "seed": seed})
    assert resp.status_code == 201
    return resp.get_json()["unit_id"]


def test_health(client: FlaskClient) -> None:
    assert client.get("/health").get_json() == {"status": "ok"}


def test_create_unit_hides_fault(client: FlaskClient) -> None:
    resp = client.post("/units", json={"fault_id": "MOTOR_DEAD", "seed": 3})
    body = resp.get_json()
    assert set(body) == {"unit_id"}
    status = client.get(f"/units/{body['unit_id']}").get_data(as_text=True)
    assert "MOTOR_DEAD" not in status and "fault" not in status


def test_create_unit_defaults_to_healthy(client: FlaskClient) -> None:
    uid = client.post("/units").get_json()["unit_id"]
    for name in TEST_SPECS:
        assert client.post(f"/units/{uid}/tests/{name}").get_json()["passed"] is True


def test_create_unit_validation(client: FlaskClient) -> None:
    assert client.post("/units", json={"fault_id": "NOPE"}).status_code == 400
    assert client.post("/units", json={"seed": "abc"}).status_code == 400


def test_list_tests(client: FlaskClient) -> None:
    uid = make_unit(client)
    body = client.get(f"/units/{uid}/tests").get_json()
    assert body["unit_id"] == uid
    names = {t["name"] for t in body["tests"]}
    assert names == set(TEST_SPECS)
    assert all(t["cost_s"] > 0 for t in body["tests"])


def test_run_test_shape_and_time(client: FlaskClient) -> None:
    uid = make_unit(client, "MOTOR_WINDING_SHORT", seed=4)
    body = client.post(f"/units/{uid}/tests/motor_spin_test").get_json()
    assert body["test_name"] == "motor_spin_test"
    assert body["passed"] is False
    assert body["cost_s"] == TEST_SPECS["motor_spin_test"].cost_s
    assert len(body["readings"]["motors"]) == 4
    assert body["failures"]
    assert body["run_index"] == 0
    body2 = client.post(f"/units/{uid}/tests/power_on_selftest").get_json()
    assert body2["unit_total_test_time_s"] == 35.0
    status = client.get(f"/units/{uid}").get_json()
    assert status["total_test_time_s"] == 35.0
    assert status["test_runs"] == {"motor_spin_test": 1, "power_on_selftest": 1}


@pytest.mark.parametrize("fault_id", sorted(FAULTS))
def test_no_endpoint_leaks_fault_id(client: FlaskClient, fault_id: str) -> None:
    uid = make_unit(client, fault_id, seed=9)
    payloads = [client.get(f"/units/{uid}/tests").get_data(as_text=True)]
    for name in TEST_SPECS:
        payloads.append(client.post(f"/units/{uid}/tests/{name}").get_data(as_text=True))
    payloads.append(client.get(f"/units/{uid}").get_data(as_text=True))
    payloads.append(client.post(f"/units/{uid}/rework", json={"action": "recalibrate_imu"}).get_data(as_text=True))
    for p in payloads:
        assert fault_id not in p


def test_unknown_unit_and_test(client: FlaskClient) -> None:
    assert client.get("/units/U-missing/tests").status_code == 404
    assert client.post("/units/U-missing/tests/imu_static").status_code == 404
    uid = make_unit(client)
    assert client.post(f"/units/{uid}/tests/not_a_test").status_code == 404


def test_rework_flow(client: FlaskClient) -> None:
    uid = make_unit(client, "CAN_TERMINATION_MISSING", seed=1)
    bad = client.post(f"/units/{uid}/rework", json={"action": "reseat_i2c_connector"}).get_json()
    assert bad["suite_passed"] is False
    assert "esc_telemetry" in bad["failing_tests"]
    good = client.post(f"/units/{uid}/rework", json={"action": "install_can_terminator"}).get_json()
    assert good["suite_passed"] is True and good["failing_tests"] == []
    assert client.get(f"/units/{uid}").get_json()["rework_count"] == 2


def test_rework_with_target(client: FlaskClient) -> None:
    uid = make_unit(client, "ESC_DESYNC", seed=8)
    readings = client.post(f"/units/{uid}/tests/esc_telemetry").get_json()["readings"]
    bad_esc = next(e["esc"] for e in readings["escs"] if e["sync_errors"] > 5)
    out = client.post(f"/units/{uid}/rework", json={"action": "reflash_esc_firmware", "target": bad_esc}).get_json()
    assert out["suite_passed"] is True


def test_rework_validation(client: FlaskClient) -> None:
    uid = make_unit(client)
    assert client.post(f"/units/{uid}/rework", json={"action": "nope"}).status_code == 400
    actions = client.get("/rework/actions").get_json()["actions"]
    assert {a["action"] for a in actions} >= {f.rework_action for f in FAULTS.values()}


def test_same_seed_same_results_over_http(client: FlaskClient) -> None:
    a = make_unit(client, "BATTERY_WEAK_CELL", seed=77)
    b = make_unit(client, "BATTERY_WEAK_CELL", seed=77)
    ra = client.post(f"/units/{a}/tests/battery_load_test").get_json()["readings"]
    rb = client.post(f"/units/{b}/tests/battery_load_test").get_json()["readings"]
    assert json.dumps(ra, sort_keys=True) == json.dumps(rb, sort_keys=True)
