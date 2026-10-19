"""Simulator tests: every fault produces its expected symptoms, healthy units pass."""

from __future__ import annotations

import pytest

from backend.simulator.drone import TEST_SPECS, SimulatedDrone
from backend.simulator.faults import FAULTS, HEALTHY, REWORK_ACTIONS

SEEDS = range(60)


def failing_tests(unit: SimulatedDrone) -> set[str]:
    return {name for name in TEST_SPECS if not unit.run_test(name).passed}


def motor(unit: SimulatedDrone, idx: int) -> dict:
    return unit.run_test("motor_spin_test").readings["motors"][idx]


# --------------------------------------------------------------------- catalog


def test_catalog_has_at_least_12_faults_with_valid_metadata() -> None:
    assert len(FAULTS) >= 12
    for f in FAULTS.values():
        assert f.rework_action in REWORK_ACTIONS
        assert set(f.always_fails) <= set(TEST_SPECS)
        assert set(f.sometimes_fails) <= set(TEST_SPECS)
        for other in f.confusable_with:
            assert other in FAULTS


def test_faults_span_multiple_endpoints() -> None:
    multi = [f for f in FAULTS.values() if len(f.always_fails) + len(f.sometimes_fails) >= 2]
    assert len(multi) >= 6


def test_at_least_two_confusable_pairs() -> None:
    pairs = {tuple(sorted((f.id, o))) for f in FAULTS.values() for o in f.confusable_with}
    assert len(pairs) >= 2


# --------------------------------------------------------------------- healthy


@pytest.mark.parametrize("seed", SEEDS)
def test_healthy_unit_passes_everything(seed: int) -> None:
    unit = SimulatedDrone(HEALTHY, seed=seed)
    for _ in range(3):  # repeated runs give fresh noise and must still pass
        assert failing_tests(unit) == set()


def test_none_fault_is_healthy() -> None:
    assert SimulatedDrone(None, seed=1).active_fault == HEALTHY


# ------------------------------------------------------------- fault signatures


@pytest.mark.parametrize("fault_id", sorted(FAULTS))
def test_fault_failing_tests_match_catalog(fault_id: str) -> None:
    f = FAULTS[fault_id]
    for seed in SEEDS:
        failed = failing_tests(SimulatedDrone(fault_id, seed=seed))
        assert set(f.always_fails) <= failed, (seed, failed)
        assert failed <= set(f.always_fails) | set(f.sometimes_fails), (seed, failed)


@pytest.mark.parametrize("fault_id", sorted(f.id for f in FAULTS.values() if f.sometimes_fails))
def test_intermittent_symptoms_are_intermittent(fault_id: str) -> None:
    unit = SimulatedDrone(fault_id, seed=7)
    for test_name in FAULTS[fault_id].sometimes_fails:
        results = {unit.run_test(test_name).passed for _ in range(40)}
        assert results == {True, False}, test_name


def test_dead_motor() -> None:
    for seed in SEEDS:
        u = SimulatedDrone("MOTOR_DEAD", seed=seed)
        m = motor(u, u.target_index)
        assert m["rpm"] == 0 and m["current_a"] < 0.2
        esc = u.run_test("esc_telemetry").readings["escs"][u.target_index]
        assert esc["back_emf_detected"] is False and esc["sync_errors"] == 0


def test_bearing_high_current_normal_rpm() -> None:
    for seed in SEEDS:
        u = SimulatedDrone("MOTOR_BEARING_DEGRADED", seed=seed)
        out = u.run_test("motor_spin_test")
        m = out.readings["motors"][u.target_index]
        assert m["current_a"] > 5.0
        assert 8600 <= m["rpm"] <= 9800
        assert all(u.target_label in msg for msg in out.failures)


def test_winding_short_high_current_low_rpm_hot() -> None:
    for seed in SEEDS:
        u = SimulatedDrone("MOTOR_WINDING_SHORT", seed=seed)
        m = motor(u, u.target_index)
        assert m["current_a"] > 5.5 and m["rpm"] < 8600 and m["temp_c"] > 58


def test_esc_desync() -> None:
    for seed in SEEDS:
        u = SimulatedDrone("ESC_DESYNC", seed=seed)
        m = motor(u, u.target_index)
        assert m["rpm_jitter"] > 150
        escs = u.run_test("esc_telemetry").readings["escs"]
        assert escs[u.target_index]["sync_errors"] > 5
        assert escs[u.target_index]["back_emf_detected"] is True
        assert all(e["packet_loss_pct"] < 1.0 for e in escs)


def test_can_termination_missing() -> None:
    for seed in SEEDS:
        u = SimulatedDrone("CAN_TERMINATION_MISSING", seed=seed)
        escs = u.run_test("esc_telemetry").readings["escs"]
        assert all(e["packet_loss_pct"] > 1.0 and e["sync_errors"] <= 1 for e in escs)
        assert u.run_test("harness_continuity").readings["can_termination_ohm"] > 100
        assert u.run_test("motor_spin_test").passed


def test_gyro_miscal_single_axis_bias_no_dropouts() -> None:
    for seed in SEEDS:
        u = SimulatedDrone("IMU_GYRO_MISCAL", seed=seed)
        r = u.run_test("imu_static").readings
        big = [ax for ax, v in r["gyro_bias_dps"].items() if abs(v) > 0.3]
        assert big == [u.gyro_axis]
        assert r["samples_dropped"] <= 5


def test_loose_i2c_vs_imu_sensor_need_compass_to_separate() -> None:
    for seed in SEEDS:
        loose = SimulatedDrone("I2C_CONNECTOR_LOOSE", seed=seed)
        imu = SimulatedDrone("IMU_SENSOR_FAULT", seed=seed)
        # Both drop IMU samples with normal gyro bias.
        for u in (loose, imu):
            r = u.run_test("imu_static").readings
            assert r["samples_dropped"] > 5
            assert all(abs(v) < 0.3 for v in r["gyro_bias_dps"].values())
        # Only the shared-bus fault shows compass read errors.
        assert loose.run_test("compass_static").readings["read_errors"] > 2
        assert imu.run_test("compass_static").readings["read_errors"] == 0
        assert imu.run_test("harness_continuity").passed


def test_weak_cell_vs_high_ir() -> None:
    for seed in SEEDS:
        weak = SimulatedDrone("BATTERY_WEAK_CELL", seed=seed)
        aged = SimulatedDrone("BATTERY_HIGH_IR", seed=seed)
        rw = weak.run_test("battery_load_test").readings
        ra = aged.run_test("battery_load_test").readings
        assert rw["cell_imbalance_loaded_v"] > 0.2 and rw["internal_resistance_mohm"] < 60
        assert ra["cell_imbalance_loaded_v"] < 0.06 and ra["internal_resistance_mohm"] > 60
        # Cheap rest check only catches the weak cell.
        assert not weak.run_test("battery_rest_check").passed
        assert aged.run_test("battery_rest_check").passed


def test_camera_ribbon_vs_dead_sensor() -> None:
    for seed in SEEDS:
        rib = SimulatedDrone("CAMERA_RIBBON_FAULT", seed=seed)
        dead = SimulatedDrone("CAMERA_SENSOR_DEAD", seed=seed)
        rr = rib.run_test("camera_selftest").readings
        rd = dead.run_test("camera_selftest").readings
        assert rr["sensor_id_ok"] and rr["csi_crc_errors"] > 5 and not rr["self_test_pass"]
        assert not rd["sensor_id_ok"] and rd["frame_rate_fps"] == 0 and rd["csi_crc_errors"] == 0
        assert rib.run_test("power_on_selftest").readings["camera_sensor_id_read"] is True
        assert dead.run_test("power_on_selftest").readings["camera_sensor_id_read"] is False


def test_compass_interference_vs_hard_iron_need_throttle_sweep() -> None:
    for seed in SEEDS:
        intf = SimulatedDrone("COMPASS_INTERFERENCE", seed=seed)
        iron = SimulatedDrone("COMPASS_HARD_IRON", seed=seed)
        # Both fail the static heading check with field magnitude in limits.
        for u in (intf, iron):
            out = u.run_test("compass_static")
            assert abs(out.readings["heading_error_deg"]) > 5
            assert 40 <= out.readings["field_magnitude_ut"] <= 60
        # Only interference scales with throttle.
        assert intf.run_test("compass_motor_interference").readings["max_deviation_change_deg"] > 10
        assert iron.run_test("compass_motor_interference").passed


@pytest.mark.parametrize("fault_id", sorted(FAULTS))
def test_confusable_pairs_share_a_failing_test(fault_id: str) -> None:
    mine = set(FAULTS[fault_id].always_fails) | set(FAULTS[fault_id].sometimes_fails)
    for other in FAULTS[fault_id].confusable_with:
        theirs = set(FAULTS[other].always_fails) | set(FAULTS[other].sometimes_fails)
        assert mine & theirs, other


# ------------------------------------------------------------ reproducibility


def test_same_seed_same_readings_regardless_of_order() -> None:
    a = SimulatedDrone("ESC_DESYNC", seed=42)
    b = SimulatedDrone("ESC_DESYNC", seed=42)
    a_esc = a.run_test("esc_telemetry").readings
    a_mot = a.run_test("motor_spin_test").readings
    b_mot = b.run_test("motor_spin_test").readings
    b_esc = b.run_test("esc_telemetry").readings
    assert a_esc == b_esc and a_mot == b_mot


def test_repeat_runs_give_fresh_noise() -> None:
    u = SimulatedDrone(HEALTHY, seed=3)
    r1 = u.run_test("imu_static")
    r2 = u.run_test("imu_static")
    assert r1.readings != r2.readings
    assert (r1.run_index, r2.run_index) == (0, 1)


def test_test_time_accumulates() -> None:
    u = SimulatedDrone(HEALTHY, seed=0)
    u.run_test("battery_load_test")
    u.run_test("power_on_selftest")
    assert u.total_test_time_s == TEST_SPECS["battery_load_test"].cost_s + TEST_SPECS["power_on_selftest"].cost_s


# --------------------------------------------------------------------- rework


@pytest.mark.parametrize("fault_id", sorted(FAULTS))
def test_correct_rework_fixes_unit(fault_id: str) -> None:
    u = SimulatedDrone(fault_id, seed=11)
    out = u.apply_rework(FAULTS[fault_id].rework_action, u.target_label)
    assert out.fault_cleared and out.suite_passed and out.failing_tests == []
    assert u.active_fault == HEALTHY


@pytest.mark.parametrize("fault_id", sorted(FAULTS))
def test_wrong_rework_leaves_unit_failing(fault_id: str) -> None:
    u = SimulatedDrone(fault_id, seed=11)
    wrong = next(a for a in REWORK_ACTIONS if a != FAULTS[fault_id].rework_action)
    out = u.apply_rework(wrong, None)
    assert not out.fault_cleared and not out.suite_passed
    assert set(FAULTS[fault_id].always_fails) <= set(out.failing_tests)


def test_positional_rework_needs_correct_target() -> None:
    u = SimulatedDrone("MOTOR_BEARING_DEGRADED", seed=5)
    wrong_target = f"motor_{(u.target_index + 1) % 4 + 1}"
    assert not u.apply_rework("replace_motor", wrong_target).suite_passed
    assert u.apply_rework("replace_motor", u.target_label).suite_passed


def test_rework_on_healthy_unit_still_passes() -> None:
    u = SimulatedDrone(HEALTHY, seed=2)
    out = u.apply_rework("recalibrate_imu")
    assert out.suite_passed and not out.fault_cleared


def test_unknown_rework_rejected() -> None:
    with pytest.raises(ValueError):
        SimulatedDrone(HEALTHY).apply_rework("hit_it_with_hammer")


def test_unknown_fault_rejected() -> None:
    with pytest.raises(KeyError):
        SimulatedDrone("NOT_A_FAULT")
