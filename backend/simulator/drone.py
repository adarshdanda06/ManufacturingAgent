"""Simulated drone on a factory end-of-line test station.

A ``SimulatedDrone`` holds one (or zero) injected fault and answers test
requests with noisy readings. Noise is seeded so that the same unit seed,
test name and run index always produce the same readings, independent of the
order in which tests are run. Repeating a test gives a fresh, but still
reproducible, sample, which is how intermittent faults show up.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.simulator.faults import HEALTHY, REWORK_ACTIONS, Fault, get_fault

NUM_MOTORS = 4
CELLS = 4


@dataclass(frozen=True)
class TestSpec:
    """Static description of a test the station can run."""

    name: str
    subsystem: str
    description: str
    cost_s: float


TEST_SPECS: dict[str, TestSpec] = {
    s.name: s
    for s in [
        TestSpec("power_on_selftest", "system", "Boot the unit and enumerate devices on I2C, UART and CAN.", 5.0),
        TestSpec("battery_rest_check", "battery", "Read pack and per-cell voltages at rest.", 5.0),
        TestSpec("esc_telemetry", "esc", "Read ESC telemetry: sync errors, packet loss, back-EMF detection.", 10.0),
        TestSpec("compass_static", "compass", "Compare compass heading to the fixture reference with motors off.", 10.0),
        TestSpec("harness_continuity", "harness", "Measure per-bus continuity resistance and CAN termination.", 15.0),
        TestSpec("camera_selftest", "camera", "Run camera built-in self test and measure frame rate and CSI errors.", 15.0),
        TestSpec("imu_static", "imu", "Log 1000 IMU samples on the static fixture: gyro bias, accel noise, dropouts.", 20.0),
        TestSpec("motor_spin_test", "motors", "Spin all motors at 50 percent throttle: current, RPM, RPM jitter, temp.", 30.0),
        TestSpec("compass_motor_interference", "compass", "Sweep throttle 0-75 percent and log compass heading deviation.", 40.0),
        TestSpec("battery_load_test", "battery", "Apply a 20 A load and measure sag, cell imbalance, internal resistance.", 60.0),
    ]
}

REWORK_COST_S = 300.0


@dataclass
class TestOutcome:
    """Result of one test run, before conversion to the protobuf message."""

    test_name: str
    passed: bool
    cost_s: float
    readings: dict[str, Any]
    failures: list[str]
    run_index: int


@dataclass
class ReworkOutcome:
    """Result of applying a rework action and re-running the full suite."""

    action: str
    target: str | None
    fault_cleared: bool
    suite_passed: bool
    failing_tests: list[str]
    cost_s: float


def _r(x: float, nd: int = 2) -> float:
    return round(x, nd)


@dataclass
class SimulatedDrone:
    """One drone unit with an optional injected fault.

    Args:
        fault_id: A key of ``FAULTS``, ``"HEALTHY"`` or None.
        seed: Seed for all noise and fault parameters on this unit.
    """

    fault_id: str | None = None
    seed: int = 0
    run_counts: dict[str, int] = field(default_factory=dict)
    total_test_time_s: float = 0.0
    rework_history: list[ReworkOutcome] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._fault: Fault | None = get_fault(self.fault_id)
        self.fault_id = self._fault.id if self._fault else HEALTHY
        prng = random.Random(f"{self.seed}:fault-params")
        # Which motor / ESC position is affected, 0-based. Unused if not applicable.
        self.target_index = prng.randrange(NUM_MOTORS)
        self.gyro_axis = prng.choice("xyz")
        self.gyro_bias_sign = prng.choice((-1.0, 1.0))
        self.compass_sign = prng.choice((-1.0, 1.0))
        self.weak_cell = prng.randrange(CELLS)
        # Per-unit manufacturing spread so healthy units are not identical.
        self.motor_spread = [prng.gauss(0.0, 0.04) for _ in range(NUM_MOTORS)]

    # ------------------------------------------------------------------ public

    @property
    def active_fault(self) -> str:
        """Current fault ID (``HEALTHY`` once a correct rework is applied)."""
        return self._fault.id if self._fault else HEALTHY

    @property
    def target_label(self) -> str | None:
        """Position label of the affected motor or ESC, if the fault has one."""
        if self._fault is None or self._fault.rework_target_kind is None:
            return None
        return f"{self._fault.rework_target_kind}_{self.target_index + 1}"

    def run_test(self, test_name: str, *, count_time: bool = True) -> TestOutcome:
        """Run one test and return its readings and verdict.

        Raises:
            KeyError: if ``test_name`` is not in ``TEST_SPECS``.
        """
        spec = TEST_SPECS[test_name]
        idx = self.run_counts.get(test_name, 0)
        self.run_counts[test_name] = idx + 1
        rng = random.Random(f"{self.seed}:{test_name}:{idx}:{len(self.rework_history)}")
        fn: Callable[[random.Random], tuple[dict[str, Any], list[str]]] = getattr(self, f"_t_{test_name}")
        readings, failures = fn(rng)
        if count_time:
            self.total_test_time_s += spec.cost_s
        return TestOutcome(test_name, not failures, spec.cost_s, readings, failures, idx)

    def run_full_suite(self) -> dict[str, TestOutcome]:
        """Run every test once. Used after rework; time is not charged to the diagnosis."""
        return {name: self.run_test(name, count_time=False) for name in TEST_SPECS}

    def apply_rework(self, action: str, target: str | None = None) -> ReworkOutcome:
        """Apply a rework action, then re-run the full suite.

        The fault is cleared only if the action matches the fault's rework
        action and, for positional faults, the target matches the affected
        position.

        Raises:
            ValueError: if ``action`` is not a known rework action.
        """
        if action not in REWORK_ACTIONS:
            raise ValueError(f"unknown rework action: {action}")
        cleared = False
        if self._fault is not None and action == self._fault.rework_action:
            if self._fault.rework_target_kind is None or target == self.target_label:
                cleared = True
                self._fault = None
        suite = self.run_full_suite()
        failing = [n for n, o in suite.items() if not o.passed]
        out = ReworkOutcome(action, target, cleared, not failing, failing, REWORK_COST_S)
        self.rework_history.append(out)
        return out

    # ------------------------------------------------------------------ helpers

    def _is(self, fault_id: str) -> bool:
        return self._fault is not None and self._fault.id == fault_id

    # ------------------------------------------------------------------ tests

    def _t_power_on_selftest(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        i2c = ["imu", "compass"]
        if self._is("I2C_CONNECTOR_LOOSE"):
            i2c = [d for d in i2c if rng.random() > 0.35]
        can_nodes = NUM_MOTORS
        if self._is("CAN_TERMINATION_MISSING") and rng.random() < 0.3:
            can_nodes = NUM_MOTORS - 1
        cam_id_ok = not self._is("CAMERA_SENSOR_DEAD")
        readings = {
            "boot_ok": True,
            "boot_time_ms": round(rng.gauss(1850, 40)),
            "i2c_devices_found": i2c,
            "uart_devices_found": ["camera_ctrl"],
            "can_nodes_found": can_nodes,
            "camera_sensor_id_read": cam_id_ok,
        }
        failures = []
        for dev in ("imu", "compass"):
            if dev not in i2c:
                failures.append(f"I2C device '{dev}' not found")
        if can_nodes != NUM_MOTORS:
            failures.append(f"CAN enumerated {can_nodes} of {NUM_MOTORS} nodes")
        if not cam_id_ok:
            failures.append("camera sensor ID read failed")
        return readings, failures

    def _t_harness_continuity(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        buses: dict[str, dict[str, Any]] = {}
        for bus in ("I2C", "UART", "CAN"):
            res = max(0.05, rng.gauss(0.25, 0.03))
            cont = "ok"
            if bus == "I2C" and self._is("I2C_CONNECTOR_LOOSE") and rng.random() < 0.5:
                res = rng.uniform(2.0, 12.0)
                cont = "intermittent"
            buses[bus] = {"resistance_ohm": _r(res, 3), "continuity": cont}
        term = rng.gauss(120.0 if self._is("CAN_TERMINATION_MISSING") else 60.0, 1.2)
        readings = {"buses": buses, "can_termination_ohm": _r(term, 1)}
        failures = []
        for bus, b in buses.items():
            if b["continuity"] != "ok" or b["resistance_ohm"] > 1.0:
                failures.append(f"{bus} continuity {b['continuity']}, {b['resistance_ohm']} ohm (limit 1.0)")
        if not 54.0 <= term <= 66.0:
            failures.append(f"CAN termination {term:.1f} ohm outside 54-66")
        return readings, failures

    def _t_motor_spin_test(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        motors = []
        failures = []
        for i in range(NUM_MOTORS):
            k = 1.0 + self.motor_spread[i] * 0.5
            cur = rng.gauss(4.2 * k, 0.12)
            rpm = rng.gauss(9200 * (1 + self.motor_spread[i] * 0.1), 90)
            jit = abs(rng.gauss(25, 5))
            temp = rng.gauss(41.0, 1.2)
            if i == self.target_index:
                if self._is("MOTOR_DEAD"):
                    cur, rpm, jit, temp = abs(rng.gauss(0.04, 0.01)), 0.0, 0.0, rng.gauss(24.0, 0.5)
                elif self._is("MOTOR_BEARING_DEGRADED"):
                    cur = rng.gauss(4.2 * 1.32, 0.15)
                    rpm = rng.gauss(9120, 90)
                    jit = abs(rng.gauss(60, 10))
                    temp = rng.gauss(52.0, 1.5)
                elif self._is("MOTOR_WINDING_SHORT"):
                    cur = rng.gauss(4.2 * 1.55, 0.2)
                    rpm = rng.gauss(7600, 150)
                    jit = abs(rng.gauss(45, 10))
                    temp = rng.gauss(70.0, 2.5)
                elif self._is("ESC_DESYNC"):
                    cur = rng.gauss(4.6, 0.5)
                    rpm = max(0.0, rng.gauss(5200, 900))
                    jit = abs(rng.gauss(1400, 200))
                    temp = rng.gauss(44.0, 1.5)
            m = {
                "motor": f"motor_{i + 1}",
                "current_a": _r(cur),
                "rpm": round(rpm),
                "rpm_jitter": round(jit),
                "temp_c": _r(temp, 1),
            }
            motors.append(m)
            name = m["motor"]
            if not 3.4 <= cur <= 5.0:
                failures.append(f"{name} current {cur:.2f} A outside 3.4-5.0")
            if not 8600 <= rpm <= 9800:
                failures.append(f"{name} rpm {rpm:.0f} outside 8600-9800")
            if jit > 150:
                failures.append(f"{name} rpm jitter {jit:.0f} > 150")
            if temp > 58.0:
                failures.append(f"{name} temp {temp:.1f} C > 58")
        return {"throttle_pct": 50, "motors": motors}, failures

    def _t_esc_telemetry(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        escs = []
        failures = []
        for i in range(NUM_MOTORS):
            sync = 1 if rng.random() < 0.1 else 0
            loss = abs(rng.gauss(0.05, 0.05))
            bemf = True
            if self._is("CAN_TERMINATION_MISSING"):
                loss = rng.uniform(6.0, 20.0)
            if i == self.target_index:
                if self._is("ESC_DESYNC"):
                    sync = max(12, round(rng.gauss(40, 10)))
                elif self._is("MOTOR_DEAD"):
                    sync, bemf = 0, False
            e = {
                "esc": f"esc_{i + 1}",
                "sync_errors": sync,
                "packet_loss_pct": _r(loss),
                "back_emf_detected": bemf,
                "temp_c": _r(rng.gauss(35.0, 1.0), 1),
            }
            escs.append(e)
            if sync > 5:
                failures.append(f"{e['esc']} sync errors {sync} > 5")
            if loss > 1.0:
                failures.append(f"{e['esc']} packet loss {loss:.2f}% > 1.0%")
            if not bemf:
                failures.append(f"{e['esc']} no back-EMF detected")
        return {"escs": escs}, failures

    def _t_imu_static(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        bias = {ax: rng.gauss(0.0, 0.03) for ax in "xyz"}
        noise = rng.gauss(2.0, 0.25)
        dropped = 1 if rng.random() < 0.15 else 0
        if self._is("IMU_GYRO_MISCAL"):
            bias[self.gyro_axis] = self.gyro_bias_sign * rng.uniform(0.9, 1.6)
        elif self._is("I2C_CONNECTOR_LOOSE"):
            dropped = rng.randint(20, 80)
        elif self._is("IMU_SENSOR_FAULT"):
            dropped = rng.randint(15, 60)
            noise = rng.gauss(3.0, 0.5)
        readings = {
            "samples_expected": 1000,
            "samples_dropped": dropped,
            "gyro_bias_dps": {ax: _r(v, 3) for ax, v in bias.items()},
            "accel_noise_mg": _r(noise),
        }
        failures = []
        for ax, v in bias.items():
            if abs(v) > 0.3:
                failures.append(f"gyro {ax} bias {v:.3f} dps exceeds 0.3")
        if noise > 4.0:
            failures.append(f"accel noise {noise:.2f} mg > 4.0")
        if dropped > 5:
            failures.append(f"{dropped} of 1000 samples dropped (limit 5)")
        return readings, failures

    def _t_compass_static(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        err = rng.gauss(0.0, 1.2)
        field_ut = rng.gauss(50.0, 1.0)
        read_errors = 0
        if self._is("COMPASS_INTERFERENCE"):
            err = self.compass_sign * rng.gauss(8.5, 0.8)
            field_ut = rng.gauss(52.0, 1.0)
        elif self._is("COMPASS_HARD_IRON"):
            err = self.compass_sign * rng.gauss(10.0, 1.2)
            field_ut = rng.gauss(56.0, 1.5)
        elif self._is("I2C_CONNECTOR_LOOSE"):
            read_errors = rng.randint(3, 15)
        readings = {
            "heading_error_deg": _r(err),
            "field_magnitude_ut": _r(field_ut),
            "read_errors": read_errors,
        }
        failures = []
        if abs(err) > 5.0:
            failures.append(f"heading error {err:.2f} deg exceeds 5.0")
        if not 40.0 <= field_ut <= 60.0:
            failures.append(f"field magnitude {field_ut:.1f} uT outside 40-60")
        if read_errors > 2:
            failures.append(f"{read_errors} compass read errors (limit 2)")
        return readings, failures

    def _t_compass_motor_interference(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        slope = 0.35 * self.compass_sign if self._is("COMPASS_INTERFERENCE") else 0.0
        sweep = []
        for thr in (0, 25, 50, 75):
            dev = slope * thr + 0.005 * thr + rng.gauss(0.0, 0.5)
            sweep.append({"throttle_pct": thr, "deviation_deg": _r(dev)})
        base = sweep[0]["deviation_deg"]
        max_delta = max(abs(s["deviation_deg"] - base) for s in sweep)
        readings = {"sweep": sweep, "max_deviation_change_deg": _r(max_delta)}
        failures = []
        if max_delta > 4.0:
            failures.append(f"heading deviation changes {max_delta:.2f} deg with throttle (limit 4.0)")
        return readings, failures

    def _t_battery_rest_check(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        cells = [rng.gauss(4.15, 0.005) for _ in range(CELLS)]
        if self._is("BATTERY_WEAK_CELL"):
            cells[self.weak_cell] = rng.gauss(4.07, 0.008)
        pack = sum(cells)
        imb = max(cells) - min(cells)
        readings = {
            "pack_voltage_v": _r(pack, 3),
            "cell_voltages_v": [_r(c, 3) for c in cells],
            "cell_imbalance_v": _r(imb, 3),
        }
        failures = []
        if imb > 0.03:
            failures.append(f"rest cell imbalance {imb:.3f} V > 0.030")
        if pack < 15.6:
            failures.append(f"rest pack voltage {pack:.2f} V < 15.6")
        return readings, failures

    def _t_battery_load_test(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        load_a = 20.0
        rest = [rng.gauss(4.15, 0.005) for _ in range(CELLS)]
        cell_ir = [rng.gauss(0.009, 0.0003) for _ in range(CELLS)]  # ohm per cell, matched pack
        if self._is("BATTERY_WEAK_CELL"):
            rest[self.weak_cell] = rng.gauss(4.07, 0.008)
            cell_ir[self.weak_cell] = rng.gauss(0.024, 0.002)
        elif self._is("BATTERY_HIGH_IR"):
            cell_ir = [rng.gauss(0.021, 0.0004) for _ in range(CELLS)]
        loaded = [v - load_a * r for v, r in zip(rest, cell_ir)]
        pack_rest = sum(rest)
        pack_loaded = sum(loaded) + rng.gauss(0.0, 0.01)
        ir_mohm = (pack_rest - pack_loaded) / load_a * 1000.0
        imb = max(loaded) - min(loaded)
        readings = {
            "load_a": load_a,
            "pack_voltage_rest_v": _r(pack_rest, 3),
            "pack_voltage_loaded_v": _r(pack_loaded, 3),
            "cell_voltages_loaded_v": [_r(c, 3) for c in loaded],
            "cell_imbalance_loaded_v": _r(imb, 3),
            "internal_resistance_mohm": _r(ir_mohm, 1),
        }
        failures = []
        if pack_loaded < 15.2:
            failures.append(f"loaded pack voltage {pack_loaded:.2f} V < 15.2")
        if imb > 0.06:
            failures.append(f"loaded cell imbalance {imb:.3f} V > 0.060")
        if ir_mohm > 60.0:
            failures.append(f"internal resistance {ir_mohm:.1f} mohm > 60")
        return readings, failures

    def _t_camera_selftest(self, rng: random.Random) -> tuple[dict[str, Any], list[str]]:
        sensor_ok = True
        fps = rng.gauss(30.0, 0.2)
        crc = 1 if rng.random() < 0.1 else 0
        if self._is("CAMERA_RIBBON_FAULT"):
            fps = rng.gauss(22.0, 2.5)
            crc = rng.randint(40, 300)
        elif self._is("CAMERA_SENSOR_DEAD"):
            sensor_ok, fps, crc = False, 0.0, 0
        failures = []
        if not sensor_ok:
            failures.append("sensor ID not readable")
        if fps < 28.0:
            failures.append(f"frame rate {fps:.1f} fps < 28")
        if crc > 5:
            failures.append(f"{crc} CSI CRC errors (limit 5)")
        readings = {
            "sensor_id_ok": sensor_ok,
            "self_test_pass": not failures,
            "frame_rate_fps": _r(fps, 1),
            "csi_crc_errors": crc,
        }
        return readings, failures
