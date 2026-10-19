"""Fault catalog for the simulated drone test station.

Each fault describes ground truth that only the simulator and the evaluation
harness may see. The agent never receives a fault ID; it has to infer the
root cause from test readings.

The numeric effects of each fault live in ``drone.py``. This module holds the
metadata: which subsystem is affected, which tests are expected to fail, the
root cause label, and the rework action that fixes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HEALTHY = "HEALTHY"


@dataclass(frozen=True)
class Fault:
    """Ground-truth definition of one injectable hardware fault."""

    id: str
    name: str
    subsystem: str
    root_cause: str
    rework_action: str
    # "motor" or "esc" when the rework must name a specific unit position.
    rework_target_kind: str | None
    # Tests that fail on every run while this fault is present.
    always_fails: tuple[str, ...]
    # Tests that fail on some runs only (intermittent symptoms).
    sometimes_fails: tuple[str, ...] = ()
    # Human-readable description of what a technician would observe.
    symptoms: tuple[str, ...] = ()
    # Faults whose symptoms overlap with this one on at least one test.
    confusable_with: tuple[str, ...] = field(default_factory=tuple)


REWORK_ACTIONS: dict[str, str] = {
    "replace_motor": "Replace the motor at the given position (target: motor_1..motor_4).",
    "reflash_esc_firmware": "Reflash ESC firmware and reset commutation timing (target: esc_1..esc_4).",
    "install_can_terminator": "Install the missing 120 ohm CAN bus terminator at the harness end.",
    "recalibrate_imu": "Run the 6-position IMU calibration and store new gyro offsets.",
    "reseat_i2c_connector": "Reseat and latch the I2C sensor harness connector.",
    "replace_imu_board": "Replace the IMU daughterboard.",
    "replace_battery_pack": "Replace the flight battery pack.",
    "reseat_camera_ribbon": "Reseat or replace the camera CSI ribbon cable.",
    "replace_camera_module": "Replace the camera module.",
    "reroute_compass_wiring": "Reroute the power lead away from the compass and twist the pair.",
    "degauss_and_recalibrate_compass": "Degauss nearby fasteners and rerun compass calibration.",
}


FAULTS: dict[str, Fault] = {
    f.id: f
    for f in [
        Fault(
            id="MOTOR_DEAD",
            name="Dead motor (open winding)",
            subsystem="motors",
            root_cause="Open stator winding in one motor; no current flows and the rotor never spins.",
            rework_action="replace_motor",
            rework_target_kind="motor",
            always_fails=("motor_spin_test", "esc_telemetry"),
            symptoms=(
                "One motor reads 0 RPM with near-zero current and ambient temperature.",
                "The matching ESC reports no back-EMF detected but no sync errors.",
            ),
            confusable_with=("ESC_DESYNC",),
        ),
        Fault(
            id="MOTOR_BEARING_DEGRADED",
            name="Degraded motor bearing",
            subsystem="motors",
            root_cause="Worn bearing in one motor adds friction; current rises while RPM holds.",
            rework_action="replace_motor",
            rework_target_kind="motor",
            always_fails=("motor_spin_test",),
            symptoms=(
                "One motor draws about 30 percent more current than its peers.",
                "RPM stays in spec; temperature is mildly elevated.",
            ),
            confusable_with=("MOTOR_WINDING_SHORT",),
        ),
        Fault(
            id="MOTOR_WINDING_SHORT",
            name="Motor winding short (turn-to-turn)",
            subsystem="motors",
            root_cause="Shorted turns in one motor winding; high current, low RPM, overheating.",
            rework_action="replace_motor",
            rework_target_kind="motor",
            always_fails=("motor_spin_test",),
            symptoms=(
                "One motor draws about 50 percent more current, runs hot, and RPM drops well below spec.",
            ),
            confusable_with=("MOTOR_BEARING_DEGRADED",),
        ),
        Fault(
            id="ESC_DESYNC",
            name="ESC commutation desync",
            subsystem="esc",
            root_cause="ESC firmware loses commutation sync on one channel; motor stutters and resyncs.",
            rework_action="reflash_esc_firmware",
            rework_target_kind="esc",
            always_fails=("motor_spin_test", "esc_telemetry"),
            symptoms=(
                "One motor shows low, unstable RPM with very high RPM jitter.",
                "The matching ESC logs many sync errors; back-EMF is detected.",
            ),
            confusable_with=("MOTOR_DEAD", "CAN_TERMINATION_MISSING"),
        ),
        Fault(
            id="CAN_TERMINATION_MISSING",
            name="Missing CAN bus terminator",
            subsystem="harness",
            root_cause="CAN bus is missing its end terminator; reflections corrupt ESC telemetry frames.",
            rework_action="install_can_terminator",
            rework_target_kind=None,
            always_fails=("esc_telemetry", "harness_continuity"),
            sometimes_fails=("power_on_selftest",),
            symptoms=(
                "All four ESCs report elevated telemetry packet loss, with no sync errors.",
                "Harness check measures about 120 ohm CAN termination instead of 60 ohm.",
                "Power-on self test occasionally enumerates only 3 CAN nodes.",
            ),
            confusable_with=("ESC_DESYNC",),
        ),
        Fault(
            id="IMU_GYRO_MISCAL",
            name="Miscalibrated gyro",
            subsystem="imu",
            root_cause="Gyro offsets were not stored after calibration; one axis has a large static bias.",
            rework_action="recalibrate_imu",
            rework_target_kind=None,
            always_fails=("imu_static",),
            symptoms=("One gyro axis shows a static bias around 1 deg/s; no sample dropouts.",),
            confusable_with=(),
        ),
        Fault(
            id="I2C_CONNECTOR_LOOSE",
            name="Loose I2C connector",
            subsystem="harness",
            root_cause="I2C sensor harness connector is not latched; IMU and compass reads drop intermittently.",
            rework_action="reseat_i2c_connector",
            rework_target_kind=None,
            always_fails=("imu_static", "compass_static"),
            sometimes_fails=("harness_continuity", "power_on_selftest"),
            symptoms=(
                "IMU drops tens of samples per 1000 while gyro bias stays normal.",
                "Compass also logs read errors because it shares the I2C bus.",
                "Harness continuity on I2C is intermittent: some runs pass, some show high resistance.",
            ),
            confusable_with=("IMU_SENSOR_FAULT",),
        ),
        Fault(
            id="IMU_SENSOR_FAULT",
            name="Failing IMU sensor",
            subsystem="imu",
            root_cause="IMU MEMS die is failing; it drops samples and its accelerometer noise rises.",
            rework_action="replace_imu_board",
            rework_target_kind=None,
            always_fails=("imu_static",),
            symptoms=(
                "IMU drops tens of samples per 1000 and accel noise is mildly elevated.",
                "Compass and I2C harness are clean, which separates it from a loose connector.",
            ),
            confusable_with=("I2C_CONNECTOR_LOOSE",),
        ),
        Fault(
            id="BATTERY_WEAK_CELL",
            name="Weak battery cell",
            subsystem="battery",
            root_cause="One cell in the pack has lost capacity and sags hard under load.",
            rework_action="replace_battery_pack",
            rework_target_kind=None,
            always_fails=("battery_rest_check", "battery_load_test"),
            symptoms=(
                "At rest one cell sits about 0.07 V below the others.",
                "Under load that cell sags far more, giving a large cell imbalance.",
            ),
            confusable_with=("BATTERY_HIGH_IR",),
        ),
        Fault(
            id="BATTERY_HIGH_IR",
            name="Aged pack with high internal resistance",
            subsystem="battery",
            root_cause="Pack is aged; internal resistance is high across all cells, so voltage sags under load.",
            rework_action="replace_battery_pack",
            rework_target_kind=None,
            always_fails=("battery_load_test",),
            symptoms=(
                "Rest voltages look normal and balanced.",
                "Under load the whole pack sags evenly; internal resistance is high, imbalance stays low.",
            ),
            confusable_with=("BATTERY_WEAK_CELL",),
        ),
        Fault(
            id="CAMERA_RIBBON_FAULT",
            name="Camera ribbon cable fault",
            subsystem="camera",
            root_cause="CSI ribbon cable is damaged or partially seated; data lanes see CRC errors.",
            rework_action="reseat_camera_ribbon",
            rework_target_kind=None,
            always_fails=("camera_selftest",),
            symptoms=(
                "Camera sensor ID reads fine but the self test fails.",
                "Frame rate is reduced and CSI CRC error count is high.",
            ),
            confusable_with=("CAMERA_SENSOR_DEAD",),
        ),
        Fault(
            id="CAMERA_SENSOR_DEAD",
            name="Dead camera sensor",
            subsystem="camera",
            root_cause="Camera image sensor does not respond; no frames are produced.",
            rework_action="replace_camera_module",
            rework_target_kind=None,
            always_fails=("camera_selftest", "power_on_selftest"),
            symptoms=(
                "Camera sensor ID cannot be read at power-on.",
                "Self test fails with 0 fps and no CRC errors (no data at all).",
            ),
            confusable_with=("CAMERA_RIBBON_FAULT",),
        ),
        Fault(
            id="COMPASS_INTERFERENCE",
            name="Compass interference from power wiring",
            subsystem="compass",
            root_cause="A power lead routed next to the compass induces a field that scales with motor current.",
            rework_action="reroute_compass_wiring",
            rework_target_kind=None,
            always_fails=("compass_static", "compass_motor_interference"),
            symptoms=(
                "Static heading error of several degrees with normal field magnitude.",
                "Heading deviation grows roughly linearly with throttle.",
            ),
            confusable_with=("COMPASS_HARD_IRON",),
        ),
        Fault(
            id="COMPASS_HARD_IRON",
            name="Compass hard-iron distortion",
            subsystem="compass",
            root_cause="A magnetized fastener near the compass adds a constant offset field.",
            rework_action="degauss_and_recalibrate_compass",
            rework_target_kind=None,
            always_fails=("compass_static",),
            symptoms=(
                "Static heading error of several degrees, field magnitude slightly high.",
                "Heading deviation does not change with throttle.",
            ),
            confusable_with=("COMPASS_INTERFERENCE",),
        ),
    ]
}

ALL_FAULT_IDS: tuple[str, ...] = (HEALTHY, *FAULTS.keys())


def get_fault(fault_id: str | None) -> Fault | None:
    """Return the fault definition, or None for a healthy unit.

    Raises:
        KeyError: if ``fault_id`` is not a known fault and not HEALTHY.
    """
    if fault_id is None or fault_id == HEALTHY:
        return None
    return FAULTS[fault_id]
