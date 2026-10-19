"""Prompt text for the plan and observe nodes."""

from __future__ import annotations

import json
from typing import Any

SYSTEM = """You are a manufacturing test engineer triaging a drone that came off the assembly line at an \
end-of-line test station. Your job is to find the single root cause (or confirm the unit is healthy) using as \
few tests and as little station time as possible, then recommend one rework action.

How the station works:
- Each test costs simulated station time. Tests have realistic measurement noise, and some faults are \
intermittent, so a repeated test can give a different result.
- Several faults share symptoms. Separate them by combining readings from different tests, not by one reading.
- Prefer cheap tests that discriminate between your current top hypotheses. Run an expensive test only when \
it is the best way to separate the remaining candidates.
- A unit with no failing readings across the subsystems you checked is HEALTHY. Do not stop early on a \
healthy-looking unit before you have covered every subsystem at least once with some test.
- For motor or ESC faults, the rework target must name the affected position, for example motor_3 or esc_2.

Budget: at most {max_steps} tool calls in total (including the final propose_rework) and at most \
{time_budget_s:.0f} simulated seconds of test time. Running out forces an immediate diagnosis.

Tools:
{tools}

Root cause codes (report exactly one):
{codes}

Rework actions (use exactly one; "none" for a healthy unit):
{actions}
"""

TOOL_DOCS = {
    "list_tests": "list_tests(): list the station tests and their cost. Free, but counts as a tool call.",
    "run_test": "run_test(test_name): run one test on the unit. Costs that test's station time.",
    "search_failure_library": (
        "search_failure_library(query): search historical root-cause records written by technicians. Free in "
        "station time, counts as a tool call. Write the query as a plain description of the abnormal readings "
        "and failure messages (not the names of tests that passed). Records are past cases, not ground truth "
        "for this unit, and some describe failures that look similar but differ in one reading."
    ),
    "propose_rework": (
        "propose_rework: final step. Give root_cause, confidence (0 to 1), rework_action, rework_target (or "
        "null), and evidence_tests (names of the tests whose results support the diagnosis). The rework is "
        "applied and the unit is re-tested; you get no further steps."
    ),
}

PLAN_INSTRUCTIONS = """Decide the next tool call. Set "thought" to one or two sentences: what you expect to \
learn and why this is the cheapest useful next step. Fill only the argument fields the chosen tool needs."""

FORCE_FINAL = """The budget is exhausted. You must call propose_rework now with your best diagnosis."""

OBSERVE_INSTRUCTIONS = """Summarize what the latest tool result shows in one or two sentences, focusing on \
abnormal readings and what they rule in or out. Then return the updated hypothesis list: up to 5 root cause \
codes from the code list with confidence between 0 and 1 (they need not sum to 1) and a short rationale. \
Drop hypotheses the evidence has ruled out."""


def system_prompt(
    *,
    tool_names: list[str],
    codes: list[dict[str, str]],
    actions: list[dict[str, str]],
    max_steps: int,
    time_budget_s: float,
) -> str:
    """Render the system prompt for the given tool set and budget."""
    return SYSTEM.format(
        max_steps=max_steps,
        time_budget_s=time_budget_s,
        tools="\n".join(f"- {TOOL_DOCS[n]}" for n in tool_names),
        codes="\n".join(f"- {c['code']}: {c['name']}" for c in codes),
        actions="\n".join(f"- {a['action']}: {a['description']}" for a in actions) + "\n- none: no rework needed.",
    )


def _clip(obj: Any, limit: int = 3000) -> str:
    text = json.dumps(obj, separators=(",", ":"))
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def history_block(
    steps: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    *,
    test_time_s: float,
    time_budget_s: float,
    max_steps: int,
) -> str:
    """Render the step history, current hypotheses and remaining budget."""
    lines = [f"Unit under test. Steps used {len(steps)} of {max_steps}. Test time used {test_time_s:.0f} of {time_budget_s:.0f} s."]
    if not steps:
        lines.append("No steps yet.")
    for s in steps:
        lines.append(f"\nStep {s['step']}: {s['tool']}({_clip(s['args'], 300)})")
        lines.append(f"Result: {_clip(s['result'])}")
        if s.get("observation"):
            lines.append(f"Observation: {s['observation']}")
    lines.append("\nCurrent hypotheses: " + (_clip(hypotheses, 1500) if hypotheses else "none yet"))
    return "\n".join(lines)
