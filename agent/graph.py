"""LangGraph triage agent: plan -> act -> observe -> decide, looping until a diagnosis.

- plan: the LLM picks the next tool call (or the final propose_rework).
- act: the tool is called against the factory API; hard budgets are enforced here.
- observe: the LLM summarizes the result and updates the hypothesis list.
- decide: deterministic routing; forces a final answer when the step or time
  budget runs out, otherwise loops back to plan.

The agent receives only a unit ID. Every cycle is appended to a trace that the
viewer replays.

Usage:
    python -m agent.graph --fault MOTOR_DEAD --seed 3            # in-process API
    python -m agent.graph --api http://localhost:5000 --unit U-abc --no-library
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, create_model

from agent import prompts
from agent.llm import LLM, LLMError, LLMResult
from agent.retrieval import get_retriever
from agent.tools import FactoryClient, FlaskTransport, HttpTransport, Transport, build_tools

DEFECT_CODES_PATH = Path(__file__).with_name("defect_codes.json")
DEFAULT_RUNS_DIR = Path(__file__).resolve().parent.parent / "eval" / "results" / "runs"
POSITIONAL_ACTIONS = {"replace_motor": "motor", "reflash_esc_firmware": "esc"}


@dataclass
class AgentConfig:
    """Agent limits and mode switches."""

    max_steps: int = 12
    time_budget_s: float = 180.0
    use_library: bool = True
    retriever: str = "bm25"
    top_k: int = 3


class Hypothesis(BaseModel):
    """One candidate root cause and how strongly the evidence supports it."""

    root_cause_code: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class Observation(BaseModel):
    """Output of the observe node."""

    summary: str
    hypotheses: list[Hypothesis]


def _plan_schema(tool_names: tuple[str, ...], name: str) -> type[BaseModel]:
    """Build the plan output schema with ``tool`` restricted to ``tool_names``."""
    # A Literal built at runtime is not a static type; typing it as Any keeps mypy
    # versions from disagreeing about which ignore code applies.
    tool_type: Any = Literal[tool_names]
    model: type[BaseModel] = create_model(
        name,
        thought=(str, ...),
        tool=(tool_type, ...),
        test_name=(str | None, None),
        query=(str | None, None),
        root_cause=(str | None, None),
        confidence=(float | None, None),
        rework_action=(str | None, None),
        rework_target=(str | None, None),
        evidence_tests=(list[str] | None, None),
    )
    return model


class AgentState(TypedDict, total=False):
    """Graph state. Lists are replaced wholesale by each node."""

    unit_id: str
    steps: list[dict[str, Any]]
    hypotheses: list[dict[str, Any]]
    test_time_s: float
    pending: dict[str, Any] | None
    must_finalize: bool
    final: dict[str, Any] | None
    stop_reason: str | None
    usage: dict[str, int]
    errors: list[str]


def load_defect_codes(path: Path = DEFECT_CODES_PATH) -> list[dict[str, str]]:
    """Load the station defect code taxonomy."""
    codes: list[dict[str, str]] = json.loads(path.read_text())["codes"]
    return codes


class TriageAgent:
    """Builds and runs the LangGraph triage loop for one unit at a time."""

    def __init__(self, llm: LLM, transport: Transport, config: AgentConfig | None = None) -> None:
        self.llm = llm
        self.transport = transport
        self.config = config or AgentConfig()
        self.codes = load_defect_codes()
        self.retriever = get_retriever(self.config.retriever) if self.config.use_library else None
        self.tool_names: tuple[str, ...] = ("list_tests", "run_test") + (
            ("search_failure_library",) if self.config.use_library else ()
        ) + ("propose_rework",)
        self._plan_any = _plan_schema(self.tool_names, "PlanDecision")
        self._plan_final = _plan_schema(("propose_rework",), "FinalDecision")

    # ------------------------------------------------------------------ helpers

    def _add_usage(self, usage: dict[str, int], res: LLMResult) -> dict[str, int]:
        return {
            "llm_calls": usage.get("llm_calls", 0) + 1,
            "input_tokens": usage.get("input_tokens", 0) + res.input_tokens,
            "output_tokens": usage.get("output_tokens", 0) + res.output_tokens,
        }

    def _call(
        self, schema: type[BaseModel], messages: list[BaseMessage], ctx: dict[str, Any], usage: dict[str, int]
    ) -> tuple[BaseModel | None, dict[str, int], str | None]:
        """Call the LLM with one retry. Returns (parsed or None, usage, error)."""
        err = None
        for _ in range(2):
            try:
                res = self.llm.structured(schema, messages, ctx)
                return res.parsed, self._add_usage(usage, res), None
            except LLMError as exc:
                usage = {**usage, "llm_calls": usage.get("llm_calls", 0) + 1}
                err = str(exc)
        return None, usage, err

    def _context(self, state: AgentState, **extra: Any) -> dict[str, Any]:
        steps = state.get("steps", [])
        catalog = next((s["result"].get("tests") for s in steps if s["tool"] == "list_tests"), None)
        return {
            "steps": steps,
            "hypotheses": state.get("hypotheses", []),
            "test_time_s": state.get("test_time_s", 0.0),
            "time_budget_s": self.config.time_budget_s,
            "max_steps": self.config.max_steps,
            "use_library": self.config.use_library,
            "must_finalize": state.get("must_finalize", False),
            "catalog": catalog,
            **extra,
        }

    def _fallback_final(self, state: AgentState) -> dict[str, Any]:
        hyps = state.get("hypotheses") or []
        top = hyps[0] if hyps else {"root_cause_code": "UNKNOWN", "confidence": 0.0}
        return {
            "thought": "Fallback: model unavailable, reporting the top hypothesis without rework.",
            "tool": "propose_rework",
            "root_cause": top["root_cause_code"],
            "confidence": top["confidence"],
            "rework_action": "none",
            "rework_target": None,
            "evidence_tests": None,
        }

    def _evidence(self, steps: list[dict[str, Any]], names: list[str] | None) -> list[dict[str, Any]]:
        """Attach the real recorded results for the tests the agent cites."""
        runs = [s for s in steps if s["tool"] == "run_test" and "error" not in s["result"]]
        latest: dict[str, dict[str, Any]] = {}
        for s in runs:
            latest[s["result"]["test_name"]] = s
        wanted = [n for n in (names or []) if n in latest] or [n for n, s in latest.items() if not s["result"]["passed"]]
        return [
            {
                "step": latest[n]["step"],
                "test_name": n,
                "run_index": latest[n]["result"].get("run_index", 0),
                "passed": latest[n]["result"]["passed"],
                "failures": latest[n]["result"].get("failures", []),
                "readings": latest[n]["result"].get("readings", {}),
            }
            for n in wanted
        ]

    # ------------------------------------------------------------------ nodes

    def plan(self, state: AgentState) -> AgentState:
        """Ask the LLM for the next tool call."""
        must = state.get("must_finalize", False)
        history = prompts.history_block(
            state.get("steps", []),
            state.get("hypotheses", []),
            test_time_s=state.get("test_time_s", 0.0),
            time_budget_s=self.config.time_budget_s,
            max_steps=self.config.max_steps,
        )
        msg = history + "\n\n" + prompts.PLAN_INSTRUCTIONS + ("\n" + prompts.FORCE_FINAL if must else "")
        schema = self._plan_final if must else self._plan_any
        parsed, usage, err = self._call(
            schema, [SystemMessage(self._system), HumanMessage(msg)], self._context(state), state.get("usage", {})
        )
        errors = list(state.get("errors", []))
        if parsed is None:
            errors.append(f"plan: {err}")
            pending = self._fallback_final(state)
            pending["llm_error"] = True
        else:
            pending = parsed.model_dump()
        return {"pending": pending, "usage": usage, "errors": errors}

    def act(self, state: AgentState) -> AgentState:
        """Run the planned tool, enforcing the test-time budget."""
        d = state["pending"] or {}
        tool = d["tool"]
        steps = list(state.get("steps", []))
        test_time = state.get("test_time_s", 0.0)
        args: dict[str, Any]
        result: dict[str, Any] | None = None
        if tool == "list_tests":
            args = {}
        elif tool == "run_test":
            name = d.get("test_name") or ""
            args = {"test_name": name}
            spec = self.client.catalog().get(name)
            if spec is None:
                result = {"error": f"unknown test: {name}"}
            elif test_time + spec["cost_s"] > self.config.time_budget_s:
                result = {"error": f"{name} costs {spec['cost_s']} s, only {self.config.time_budget_s - test_time:.0f} s left"}
        elif tool == "search_failure_library":
            args = {"query": d.get("query") or ""}
        else:
            action = d.get("rework_action") or "none"
            target = d.get("rework_target") if action in POSITIONAL_ACTIONS else None
            args = {"action": action, "target": target}
        if result is None:
            result = self.tools[tool].invoke(args)
        if tool == "run_test" and "error" not in result:
            test_time += float(result.get("cost_s", 0.0))
        step = {
            "step": len(steps) + 1,
            "thought": d.get("thought", ""),
            "tool": tool,
            "args": args,
            "result": result,
            "test_time_s": test_time,
            "observation": None,
            "hypotheses": state.get("hypotheses", []),
        }
        steps.append(step)
        out: AgentState = {"steps": steps, "test_time_s": test_time, "pending": None}
        if tool == "propose_rework":
            out["final"] = {
                "root_cause": d.get("root_cause") or "UNKNOWN",
                "confidence": d.get("confidence") if d.get("confidence") is not None else 0.0,
                "recommended_rework": args,
                "evidence": self._evidence(steps, d.get("evidence_tests")),
            }
            out["stop_reason"] = (
                "llm_error" if d.get("llm_error") else "budget_forced" if state.get("must_finalize") else "proposed"
            )
        return out

    def observe(self, state: AgentState) -> AgentState:
        """Summarize the latest result and update hypotheses."""
        steps = list(state.get("steps", []))
        last = dict(steps[-1])
        hyps = state.get("hypotheses", [])
        usage = state.get("usage", {})
        errors = list(state.get("errors", []))
        if last["tool"] == "propose_rework":
            r = last["result"]
            last["observation"] = (
                "No rework applied." if not r.get("applied") else f"Rework applied; full suite passed: {r.get('suite_passed')}."
            )
        elif "error" in last["result"]:
            last["observation"] = f"Tool error: {last['result']['error']}"
        elif last["tool"] == "list_tests":
            n = len(last["result"].get("tests", []))
            last["observation"] = f"Station offers {n} tests."
        else:
            history = prompts.history_block(
                steps, hyps, test_time_s=state.get("test_time_s", 0.0),
                time_budget_s=self.config.time_budget_s, max_steps=self.config.max_steps,
            )
            ctx = self._context(state, last_tool=last["tool"], last_result=last["result"])
            parsed, usage, err = self._call(
                Observation,
                [SystemMessage(self._system), HumanMessage(history + "\n\n" + prompts.OBSERVE_INSTRUCTIONS)],
                ctx,
                usage,
            )
            if parsed is None:
                errors.append(f"observe: {err}")
                last["observation"] = "Observation failed; hypotheses unchanged."
            else:
                obs = Observation.model_validate(parsed.model_dump())
                last["observation"] = obs.summary
                hyps = sorted((h.model_dump() for h in obs.hypotheses), key=lambda h: -h["confidence"])[:5]
        last["hypotheses"] = hyps
        steps[-1] = last
        return {"steps": steps, "hypotheses": hyps, "usage": usage, "errors": errors}

    def decide(self, state: AgentState) -> AgentState:
        """Force a final answer when the step or time budget is exhausted."""
        if state.get("final"):
            return {}
        steps = state.get("steps", [])
        costs = [t["cost_s"] for t in self.client.catalog().values()]
        remaining = self.config.time_budget_s - state.get("test_time_s", 0.0)
        out_of_time = not costs or remaining < min(costs)
        return {"must_finalize": len(steps) >= self.config.max_steps - 1 or out_of_time}

    # ------------------------------------------------------------------ graph

    def build(self) -> Any:
        """Compile the graph."""
        g: StateGraph[AgentState] = StateGraph(AgentState)
        g.add_node("plan", self.plan)
        g.add_node("act", self.act)
        g.add_node("observe", self.observe)
        g.add_node("decide", self.decide)
        g.set_entry_point("plan")
        g.add_edge("plan", "act")
        g.add_edge("act", "observe")
        g.add_edge("observe", "decide")
        g.add_conditional_edges("decide", lambda s: "end" if s.get("final") else "plan", {"end": END, "plan": "plan"})
        return g.compile()

    def run(self, unit_id: str, run_id: str | None = None) -> dict[str, Any]:
        """Diagnose one unit and return its full trace.

        Only ``unit_id`` reaches the agent. The ground-truth fault is never
        passed in; the eval harness attaches it to the trace afterwards.
        """
        self.client = FactoryClient(self.transport, unit_id)
        self.tools = build_tools(self.client, self.retriever, self.config.top_k)
        self._system = prompts.system_prompt(
            tool_names=list(self.tool_names),
            codes=self.codes,
            actions=self.client.rework_actions(),
            max_steps=self.config.max_steps,
            time_budget_s=self.config.time_budget_s,
        )
        started = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        init: AgentState = {
            "unit_id": unit_id, "steps": [], "hypotheses": [], "test_time_s": 0.0, "pending": None,
            "must_finalize": False, "final": None, "stop_reason": None, "usage": {}, "errors": [],
        }
        state: AgentState = self.build().invoke(init, {"recursion_limit": 8 * self.config.max_steps + 10})
        steps = state.get("steps", [])
        final_step = steps[-1] if steps and steps[-1]["tool"] == "propose_rework" else None
        usage = state.get("usage", {})
        return {
            "run_id": run_id or f"run-{uuid.uuid4().hex[:10]}",
            "unit_id": unit_id,
            "agent": {"model": self.llm.model_name, "config": asdict(self.config)},
            "started_at": started.isoformat(),
            "duration_s": round(time.perf_counter() - t0, 3),
            "stop_reason": state.get("stop_reason"),
            "final": state.get("final"),
            "rework_result": final_step["result"] if final_step else None,
            "totals": {
                "tool_calls": len(steps),
                "tests_run": sum(1 for s in steps if s["tool"] == "run_test" and "error" not in s["result"]),
                "test_time_s": state.get("test_time_s", 0.0),
                "llm_calls": usage.get("llm_calls", 0),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
            "errors": state.get("errors", []),
            "steps": steps,
        }


def write_trace(trace: dict[str, Any], out_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    """Write a trace JSON file named after its run ID."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{trace['run_id']}.json"
    path.write_text(json.dumps(trace, indent=2))
    return path


def make_llm(kind: str, model: str | None = None) -> LLM:
    """Build an LLM backend by name: ``gemini`` or ``mock`` (rule-based)."""
    from agent.llm import GeminiLLM, RuleBasedLLM

    if kind == "mock":
        return RuleBasedLLM()
    return GeminiLLM(model=model)


def main(argv: list[str] | None = None) -> int:
    """CLI: diagnose one unit and write its trace."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--api",
        default=os.environ.get("FACTORY_API_URL"),
        help="Base URL of a running factory API (default: FACTORY_API_URL). Omit to use the API in-process.",
    )
    p.add_argument("--unit", help="Existing unit ID (with --api).")
    p.add_argument("--fault", default=None, help="In-process only: fault to inject into a new unit.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-library", action="store_true", help="Run without the failure library.")
    p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--time-budget", type=float, default=180.0)
    p.add_argument("--llm", choices=["gemini", "mock"], default="gemini")
    p.add_argument("--model", default=None)
    p.add_argument("--out", type=Path, default=DEFAULT_RUNS_DIR)
    a = p.parse_args(argv)

    transport: Transport
    if a.api:
        transport = HttpTransport(a.api)
    else:
        from backend.app import create_app

        transport = FlaskTransport(create_app())
    unit_id = a.unit
    if unit_id is None:
        status, body = transport.request("POST", "/units", {"fault_id": a.fault, "seed": a.seed})
        if status != 201:
            raise SystemExit(f"could not create unit: {body}")
        unit_id = body["unit_id"]
    cfg = AgentConfig(max_steps=a.max_steps, time_budget_s=a.time_budget, use_library=not a.no_library)
    trace = TriageAgent(make_llm(a.llm, a.model), transport, cfg).run(unit_id)
    path = write_trace(trace, a.out)
    print(json.dumps({"trace": str(path), "final": trace["final"], "totals": trace["totals"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
