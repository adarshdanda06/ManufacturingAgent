# Factory Triage Agent: project context

Last updated: 2026-10-19. Repo: `adarshdanda06/ManufacturingAgent`, branch `claude/sleepy-archimedes-7avh7q` (Stages 1 to 4 committed and pushed; latest commit `264414f`).

## 1. Goal

A portfolio project for a Manufacturing Software internship at a drone company. It simulates a drone factory end-of-line test station and uses an LLM agent loop to diagnose injected hardware faults and recommend rework. It has to show hardware-software manufacturing skills: a Flask backend simulating a factory test API, a LangGraph agent that calls it in a loop to isolate faults, a failure library the agent retrieves from, and a React + TypeScript viewer that replays the agent's reasoning trace. It must produce real, reproducible measurements (diagnosis accuracy, average tool calls per diagnosis) for a resume. Results are never hardcoded or invented.

## 2. Stage status

| Stage | Status |
|---|---|
| 1. Simulated factory API (Flask) | Done, tested |
| 2. Failure library and retrieval | Done, tested |
| 3. LangGraph agent (Gemini) | Done, tested with mock LLMs only. Not yet run against real Gemini. |
| 4. Evaluation harness | Done, tested with the mock LLM. No real eval run yet. |
| 5. React + TypeScript viewer | Done: `web/` (Vite, React 19, TS) over `backend/results_api.py`, tested |
| 6. Polish (README, CI, Docker, lint) | Done: README, ruff + mypy config, GitHub Actions, Docker Compose. README results need the no-library rerun. |

Test suite: `python -m pytest -q` gives `219 passed`.

**Immediate next step:** in an environment with `GOOGLE_API_KEY` set, run one unit to confirm the Gemini path works (model name `gemini-3.5-flash` and structured output are unverified), then run the real eval:

```
python -m agent.graph --fault MOTOR_BEARING_DEGRADED --seed 4
python -m eval.run_eval --n 60 --seed 7 --concurrency 4
```

## 3. Tech stack (as built)

- Python 3.11+ (developed on 3.13), Flask 3, pytest, protobuf 7 (`grpcio-tools` for codegen)
- Agent: LangGraph 1.2, langchain-core 1.6, langchain-google-genai 4.4 (Gemini). The original spec said langchain-anthropic; I switched to Gemini.
- Retrieval: pure Python BM25 and TF-IDF, no downloads or paid APIs
- Planned: React + TypeScript (Vite), plain CSS or Tailwind, Docker Compose (api+agent, web), ruff, mypy, GitHub Actions

## 4. Repo layout (current)

```
.env.example                 GOOGLE_API_KEY, GEMINI_MODEL, FACTORY_API_URL
pyproject.toml               pytest testpaths: backend/tests, agent/tests, eval/tests
backend/
  app.py                     create_app() Flask factory
  api/routes.py              endpoints + in-memory thread-safe UnitStore
  simulator/drone.py         SimulatedDrone, TEST_SPECS, fault effects, noise
  simulator/faults.py        Fault dataclass, FAULTS catalog, REWORK_ACTIONS
  proto/test_result.proto    TestSpec, TestCatalog, TestResult, ReworkResult (+ generated pb2)
  requirements.txt, requirements-dev.txt
  tests/test_simulator.py, tests/test_api.py
agent/
  failure_library.json       26 historical records
  defect_codes.json          25 root cause codes the agent must report from
  retrieval.py               Retriever protocol, TfidfRetriever, Bm25Retriever, get_retriever()
  llm.py                     LLM protocol, GeminiLLM, ScriptedLLM, RuleBasedLLM
  tools.py                   FactoryClient, HttpTransport, FlaskTransport, build_tools()
  prompts.py                 system prompt, tool docs, history rendering
  graph.py                   TriageAgent (plan/act/observe/decide), CLI
  requirements.txt
  tests/test_retrieval.py, tests/test_graph.py
eval/
  retrieval_eval.py          retriever-only benchmark (no LLM)
  run_eval.py                full agent batch eval
  results/sample/retrieval.json   committed sample; everything else in results/ is gitignored
  tests/test_run_eval.py
scripts/gen_proto.sh         regenerates protobuf bindings
```

Not yet created: `README.md`, `docker-compose.yml`, `web/`, CI workflow, ruff/mypy config.

## 5. Stage 1: simulator and API

### Station tests (cost in simulated seconds)

| Test | Subsystem | Cost | Measures |
|---|---|---|---|
| power_on_selftest | system | 5 | I2C/UART/CAN enumeration, camera sensor ID |
| battery_rest_check | battery | 5 | pack and per-cell voltage at rest |
| esc_telemetry | esc | 10 | sync errors, packet loss, back-EMF per ESC |
| compass_static | compass | 10 | heading error, field magnitude, read errors |
| harness_continuity | harness | 15 | per-bus resistance (I2C, UART, CAN), CAN termination |
| camera_selftest | camera | 15 | sensor ID, frame rate, CSI CRC errors |
| imu_static | imu | 20 | gyro bias per axis, accel noise, dropped samples |
| motor_spin_test | motors | 30 | per motor current, RPM, RPM jitter, temp |
| compass_motor_interference | compass | 40 | heading deviation vs throttle sweep |
| battery_load_test | battery | 60 | loaded sag, cell imbalance, internal resistance |

Full suite: 210 s. Rework costs 300 s and re-runs the full suite (not charged to diagnosis time).

### Fault catalog (14 faults + HEALTHY)

| Fault ID | Fails always | Rework | Confusable with |
|---|---|---|---|
| MOTOR_DEAD | motor_spin, esc_telemetry (no back-EMF) | replace_motor (target motor_N) | ESC_DESYNC |
| MOTOR_BEARING_DEGRADED | motor_spin (high current, normal RPM) | replace_motor | MOTOR_WINDING_SHORT |
| MOTOR_WINDING_SHORT | motor_spin (high current, low RPM, hot) | replace_motor | MOTOR_BEARING_DEGRADED |
| ESC_DESYNC | motor_spin (jitter), esc_telemetry (sync errors) | reflash_esc_firmware (target esc_N) | MOTOR_DEAD, CAN_TERMINATION_MISSING |
| CAN_TERMINATION_MISSING | esc_telemetry (loss on all), harness (120 ohm); sometimes power_on | install_can_terminator | ESC_DESYNC |
| IMU_GYRO_MISCAL | imu_static (one axis bias) | recalibrate_imu | |
| I2C_CONNECTOR_LOOSE | imu_static (dropouts), compass_static (read errors); sometimes harness, power_on | reseat_i2c_connector | IMU_SENSOR_FAULT |
| IMU_SENSOR_FAULT | imu_static (dropouts, higher noise) | replace_imu_board | I2C_CONNECTOR_LOOSE |
| BATTERY_WEAK_CELL | battery_rest, battery_load | replace_battery_pack | BATTERY_HIGH_IR |
| BATTERY_HIGH_IR | battery_load only | replace_battery_pack | BATTERY_WEAK_CELL |
| CAMERA_RIBBON_FAULT | camera_selftest (low fps, CRC errors) | reseat_camera_ribbon | CAMERA_SENSOR_DEAD |
| CAMERA_SENSOR_DEAD | camera_selftest (0 fps, no CRC), power_on | replace_camera_module | CAMERA_RIBBON_FAULT |
| COMPASS_INTERFERENCE | compass_static, compass_motor_interference | reroute_compass_wiring | COMPASS_HARD_IRON |
| COMPASS_HARD_IRON | compass_static only (field slightly high) | degauss_and_recalibrate_compass | COMPASS_INTERFERENCE |

Noise and fault parameters are seeded per `(unit seed, test name, run index, rework count)`, so readings are reproducible and independent of test order, and repeated runs give fresh samples (how intermittent faults show up). The unit seed also picks the affected motor/ESC position, gyro axis, weak cell, and sign of compass error. Rework clears the fault only when the action matches and, for motor/ESC faults, the target position matches.

### Endpoints

- `GET /health`
- `POST /units` body `{fault_id?, seed?}` returns `{unit_id}` only (fault hidden)
- `GET /units/<id>` station status (time used, run counts), never the fault
- `GET /units/<id>/tests` test catalog with costs (TestCatalog proto)
- `POST /units/<id>/tests/<test_name>` returns TestResult: readings, passed, failures, cost_s, run_index, unit_total_test_time_s
- `GET /rework/actions`
- `POST /units/<id>/rework` body `{action, target?}` returns ReworkResult: suite_passed, failing_tests, cost_s

Responses are built as protobuf messages and serialized to JSON at the HTTP boundary.

## 6. Stage 2: failure library and retrieval

- `agent/failure_library.json`: 26 records, each with id, title, subsystem, symptom_summary, key_tests, root_cause_code, root_cause, rework_action, rework_notes, occurrences. FL-001 to FL-014 cover each simulator fault, FL-015, FL-025 and FL-026 are extra variants of real faults, FL-016 to FL-024 are decoys the simulator cannot produce (IMU_MOUNT_LOOSE, PROP_IMBALANCE, ESC_THERMAL_DERATE, BATTERY_CONNECTOR_HIGH_RESISTANCE, CAMERA_FIRMWARE_MISMATCH, UART_CONNECTOR_DAMAGED, FIXTURE_MAGNETIC_CONTAMINATION, MOTOR_MAGNET_DEMAG, CAN_STUB_DAMAGED) with `rework_action: null`.
- `retrieval.py`: `Retriever` protocol (`name`, `search(query, k) -> list[Match]`), swappable via `get_retriever(name)`. Tokenizer lowercases, drops stopwords and numbers, applies domain synonyms and light stemming, adds bigrams. `key_tests` is deliberately not indexed (test names appear in queries for passing tests too).
- Real retriever-only benchmark (`python -m eval.retrieval_eval --seeds 50`, 700 queries per style, from `eval/results/sample/retrieval.json`):

| Query style | Retriever | Top-1 | Top-3 |
|---|---|---|---|
| failures only | bm25 | 0.56 | 0.9286 |
| failures only | tfidf | 0.5414 | 0.9286 |
| full dump (incl. passing tests) | bm25 | 0.50 | 0.7143 |
| full dump | tfidf | 0.4414 | 0.7857 |

Takeaway used in Stage 3: the agent uses BM25, top 3, and is told to query with abnormal readings and failure messages, not passing test names. Retrieval alone cannot separate the confusable pairs at top-1, which is why the agent has to reason over readings.

## 7. Stage 3: LangGraph agent (`agent/graph.py`)

### Graph

`plan -> act -> observe -> decide -> (plan | END)`

- **plan**: LLM structured output `PlanDecision {thought, tool, test_name?, query?, root_cause?, confidence?, rework_action?, rework_target?, evidence_tests?}`. `tool` is a Literal built per mode (no `search_failure_library` in no-library mode). When forced to finalize, a `FinalDecision` schema allows only `propose_rework`.
- **act**: calls the LangChain tool. Enforces the time budget: a `run_test` that would exceed it returns an error and never reaches the station. Unknown test names return an error. Each call is one step.
- **observe**: LLM structured output `Observation {summary, hypotheses: [{root_cause_code, confidence 0..1, rationale}]}`, keeps the top 5 sorted by confidence. Skipped (deterministic summary) for list_tests, propose_rework, and tool errors.
- **decide**: deterministic. Sets `must_finalize` when steps used >= max_steps - 1 or no remaining test fits the time budget. Ends when a final answer exists.

### Tools (`agent/tools.py`)
`list_tests`, `run_test(test_name)`, `search_failure_library(query)` (library mode only), `propose_rework(action, target)`. `propose_rework` is terminal: it applies the rework (unless action `none`), re-runs the suite, and the run ends. `FactoryClient` works over `HttpTransport(base_url)` or `FlaskTransport(app)` (in-process, same routes).

### Final answer
```
{root_cause, confidence, recommended_rework: {action, target}, evidence: [{step, test_name, run_index, passed, failures, readings}]}
```
Evidence is filled from the actually recorded test results for the tests the model cites (unknown citations dropped; if none cited, all failing tests).

### Trace JSON (one per run; the viewer will replay this)
Top level: `run_id, unit_id, agent{model, config}, started_at, duration_s, stop_reason (proposed | budget_forced | llm_error | crash), final, rework_result, totals{tool_calls, tests_run, test_time_s, llm_calls, input_tokens, output_tokens}, errors, steps[]`. Each step: `step, thought, tool, args, result, test_time_s, observation, hypotheses`. The eval harness adds `mode, scenario_index, ground_truth{fault_id, unit_seed, target, rework_action}, score{predicted, correct, rework_fixed_unit}`.

### LLM backends (`agent/llm.py`)
- `GeminiLLM`: `ChatGoogleGenerativeAI(...).with_structured_output(schema, include_raw=True)` (json_schema method), temperature 0, max_retries 3, reads `GOOGLE_API_KEY` or `GEMINI_API_KEY`, model from arg, then `GEMINI_MODEL`, then default `gemini-3.5-flash` (unverified). Token usage from `usage_metadata`.
- `ScriptedLLM`: replays fixed responses for unit tests.
- `RuleBasedLLM`: deterministic stand-in for CI smoke runs (runs tests cheapest first, searches library once, takes the top match). Its numbers are never agent results.
- The graph retries a failed LLM call once; if plan still fails, it falls back to the top hypothesis with rework `none` (`stop_reason: llm_error`).

### Defaults and decisions
1. `max_steps=12` (includes list_tests and propose_rework), `time_budget_s=180` (full suite is 210, so the agent must choose).
2. The agent reports a code from `defect_codes.json` (14 real + 9 decoy codes + HEALTHY + UNKNOWN), names only, no symptoms, so the library still carries the diagnostic knowledge and accuracy is gradeable.
3. The test catalog is not in the initial prompt; the agent must call `list_tests` (counts as a step). The rework action list is in the system prompt.
4. Prompt rules: prefer cheap discriminating tests, combine readings to separate confusable faults, cover every subsystem before calling a unit HEALTHY, motor/ESC rework must name the position.
5. The agent only ever receives a unit ID. Test `test_agent_never_sees_fault_id` checks no request or response contains fault info.

CLI: `python -m agent.graph [--api URL --unit ID | --fault F --seed S] [--no-library] [--max-steps] [--time-budget] [--llm gemini|mock] [--model] [--out DIR]`.

## 8. Stage 4: evaluation harness (`eval/run_eval.py`)

- Scenarios: `make_scenarios(n, seed)` cycles all 15 labels (balanced within 1), shuffles with the seed, draws unit seeds. Both modes run on the same scenarios.
- Each run gets a fresh `TriageAgent` and `FlaskTransport` over one shared in-process app; ThreadPoolExecutor with `--concurrency`.
- Scoring: correct if `final.root_cause == fault_id`. `rework_fixed_unit`: suite passed after rework (for HEALTHY, recommended action is `none`).
- Outputs in `eval/results/<UTC timestamp>/` (or `--out`): `runs/<mode>/<run_id>.json`, `results.json` (config, command, per-mode metrics, run index), `summary.md`.
- Metrics per mode: accuracy, rework fixed rate, per-fault accuracy, confusion pairs, mean/median tool calls, tests run, test time, stop reasons, token totals and per-run mean, cost estimate only if `--price-in`/`--price-out` (USD per 1M tokens) are given. Summary shows the library minus no-library delta and the exact command. Mock runs get a "not agent results" banner.
- Flags: `--n` (per mode, default 30), `--seed` (7), `--concurrency` (4), `--modes library no_library`, `--llm gemini|mock`, `--model`, `--max-steps`, `--time-budget`, `--price-in`, `--price-out`, `--out`.
- Caveat to put in docs: scenarios are exactly reproducible from the seed; LLM output at temperature 0 is close to but not guaranteed repeatable.

## 9. Remaining work

### Stage 5: React + TypeScript viewer (`web/`)
Pages: (1) run list with outcome (correct/incorrect), steps, time; (2) run detail with the step timeline (thought, tool call, result, hypothesis confidence bars), final diagnosis next to ground truth, rework result; (3) eval summary with per-fault accuracy and with-vs-without-library comparison. Typed API clients and shared TS types matching the trace and results JSON above. Clean, readable, desktop-first, no heavy UI libraries. Needs a small backend route (or static serving) to list eval result directories and read run JSON.

### Stage 6: polish
- README: one-paragraph overview, Mermaid architecture diagram, quickstart (`docker compose up`), how to run the eval, results table copied from a REAL eval run, a viewer screenshot or GIF, honest limitations section (the factory is simulated, faults are single and designed, LLM nondeterminism, library written by the same author as the simulator).
- Type hints and docstrings on public functions, ruff and mypy config, GitHub Actions running pytest, lint, and a 10-unit smoke eval with the mocked LLM (`--llm mock`).
- Docker Compose with two services: api+agent, web.
- `.env.example` with no secrets (exists).

### Final deliverable to me
A short list of real numbers (accuracy with and without the library, average tool calls, number of scenarios) from actual eval output, for resume bullets.

## 10. Rules
- One stage at a time; run tests and show results before continuing.
- Do not ask clarifying questions unless blocked; list choices made at the end of each stage.
- Never fabricate metrics. README numbers come only from eval output files.
- No em dashes anywhere in text, comments, or docs.
