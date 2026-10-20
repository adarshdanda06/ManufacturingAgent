# Factory Triage Agent evaluation

- Run at: 2026-10-20T07:14:53.141234+00:00
- Model: `gemini-3.5-flash-lite`
- Scenarios: 30 units per mode (balanced over 15 labels), seed 7
- Limits: 12 tool calls, 180 s test time

Command:

```
python -m eval.run_eval --llm gemini --model gemini-3.5-flash-lite --modes no_library --concurrency 2 --rpm 8 --out eval/results/gemini-3.5-flash-lite/no_library
```

## Overall

| Metric | no_library
|---|---|
| Diagnosis accuracy | 83.3% |
| Rework fixed unit | 83.3% |
| Mean tool calls | 7.17 |
| Median tool calls | 7.5 |
| Mean tests run | 5.07 |
| Mean test time (s) | 68.8 |
| Median test time (s) | 67.5 |
| Tokens per run (mean) | 48596 |

## Per-fault accuracy

| Fault | n | no_library |
|---|---|---|
| HEALTHY | 2 | 100.0% |
| MOTOR_DEAD | 2 | 100.0% |
| MOTOR_BEARING_DEGRADED | 2 | 100.0% |
| MOTOR_WINDING_SHORT | 2 | 100.0% |
| ESC_DESYNC | 2 | 100.0% |
| CAN_TERMINATION_MISSING | 2 | 100.0% |
| IMU_GYRO_MISCAL | 2 | 100.0% |
| I2C_CONNECTOR_LOOSE | 2 | 100.0% |
| IMU_SENSOR_FAULT | 2 | 50.0% |
| BATTERY_WEAK_CELL | 2 | 100.0% |
| BATTERY_HIGH_IR | 2 | 0.0% |
| CAMERA_RIBBON_FAULT | 2 | 100.0% |
| CAMERA_SENSOR_DEAD | 2 | 50.0% |
| COMPASS_INTERFERENCE | 2 | 50.0% |
| COMPASS_HARD_IRON | 2 | 100.0% |

## Confusion pairs (no_library)

| Truth | Predicted | Count |
|---|---|---|
| BATTERY_HIGH_IR | HEALTHY | 2 |
| CAMERA_SENSOR_DEAD | CAMERA_RIBBON_FAULT | 1 |
| COMPASS_INTERFERENCE | HEALTHY | 1 |
| IMU_SENSOR_FAULT | UNKNOWN | 1 |

## Stop reasons

- no_library: proposed 30
