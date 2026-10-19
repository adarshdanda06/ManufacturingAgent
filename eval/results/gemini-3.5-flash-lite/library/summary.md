# Factory Triage Agent evaluation

- Run at: 2026-10-19T17:59:10.111144+00:00
- Model: `gemini-3.5-flash-lite`
- Scenarios: 30 units per mode (balanced over 15 labels), seed 7
- Limits: 12 tool calls, 180 s test time

Command:

```
python -m eval.run_eval --llm gemini --model gemini-3.5-flash-lite --modes library --concurrency 2 --rpm 8 --out eval/results/lite-library
```

## Overall

| Metric | library
|---|---|
| Diagnosis accuracy | 83.3% |
| Rework fixed unit | 83.3% |
| Mean tool calls | 7.40 |
| Median tool calls | 7.0 |
| Mean tests run | 4.97 |
| Mean test time (s) | 65.0 |
| Median test time (s) | 65.0 |
| Tokens per run (mean) | 44679 |

## Per-fault accuracy

| Fault | n | library |
|---|---|---|
| HEALTHY | 2 | 100.0% |
| MOTOR_DEAD | 2 | 100.0% |
| MOTOR_BEARING_DEGRADED | 2 | 50.0% |
| MOTOR_WINDING_SHORT | 2 | 50.0% |
| ESC_DESYNC | 2 | 100.0% |
| CAN_TERMINATION_MISSING | 2 | 100.0% |
| IMU_GYRO_MISCAL | 2 | 100.0% |
| I2C_CONNECTOR_LOOSE | 2 | 100.0% |
| IMU_SENSOR_FAULT | 2 | 100.0% |
| BATTERY_WEAK_CELL | 2 | 100.0% |
| BATTERY_HIGH_IR | 2 | 0.0% |
| CAMERA_RIBBON_FAULT | 2 | 100.0% |
| CAMERA_SENSOR_DEAD | 2 | 50.0% |
| COMPASS_INTERFERENCE | 2 | 100.0% |
| COMPASS_HARD_IRON | 2 | 100.0% |

## Confusion pairs (library)

| Truth | Predicted | Count |
|---|---|---|
| BATTERY_HIGH_IR | HEALTHY | 2 |
| CAMERA_SENSOR_DEAD | CAMERA_RIBBON_FAULT | 1 |
| MOTOR_BEARING_DEGRADED | HEALTHY | 1 |
| MOTOR_WINDING_SHORT | HEALTHY | 1 |

## Stop reasons

- library: proposed 30
