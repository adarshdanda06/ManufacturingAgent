"""LLM backends for the triage agent.

The graph talks to an ``LLM`` through one method, ``structured``, which
returns a parsed Pydantic object plus token usage. ``GeminiLLM`` is the real
backend (Gemini via ``langchain-google-genai``). ``ScriptedLLM`` replays fixed
responses for unit tests, and ``RuleBasedLLM`` is a deterministic stand-in for
CI smoke runs. Numbers produced by the two mocks are not agent results.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence, TypeVar

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-3.5-flash"


class LLMError(RuntimeError):
    """The model call failed or returned output that did not parse."""


@dataclass
class LLMResult:
    """Parsed output of one model call and its token usage."""

    parsed: BaseModel
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    """Anything that can turn a prompt into a schema-validated object."""

    model_name: str

    def structured(
        self, schema: type[T], messages: Sequence[BaseMessage], context: dict[str, Any] | None = None
    ) -> LLMResult:
        """Call the model and parse its reply into ``schema``.

        ``context`` carries machine-readable agent state. Real models ignore
        it; the mocks use it so they do not have to parse prompt text.
        """
        ...


class GeminiLLM:
    """Gemini chat model with native JSON-schema structured output.

    Reads ``GOOGLE_API_KEY`` from the environment. The model name comes from
    the ``model`` argument, then ``GEMINI_MODEL``, then ``DEFAULT_MODEL``.
    """

    def __init__(self, model: str | None = None, temperature: float = 0.0, max_retries: int = 3) -> None:
        if not os.environ.get("GOOGLE_API_KEY"):
            raise LLMError("GOOGLE_API_KEY is not set")
        from langchain_google_genai import ChatGoogleGenerativeAI

        self.model_name = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        self._chat = ChatGoogleGenerativeAI(
            model=self.model_name, temperature=temperature, max_retries=max_retries
        )

    def structured(
        self, schema: type[T], messages: Sequence[BaseMessage], context: dict[str, Any] | None = None
    ) -> LLMResult:
        runnable = self._chat.with_structured_output(schema, include_raw=True)
        try:
            out: dict[str, Any] = runnable.invoke(list(messages))  # type: ignore[assignment]
        except Exception as exc:  # network, quota, safety block
            raise LLMError(f"model call failed: {exc}") from exc
        parsed = out.get("parsed")
        if out.get("parsing_error") is not None or not isinstance(parsed, schema):
            raise LLMError(f"could not parse model output: {out.get('parsing_error')}")
        usage = getattr(out.get("raw"), "usage_metadata", None) or {}
        return LLMResult(parsed, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)))


class ScriptedLLM:
    """Replays a fixed list of responses, one per call. For unit tests.

    Each entry is a dict of field values, or a callable taking ``context``
    and returning one, or an ``Exception`` to raise.
    """

    model_name = "scripted"

    def __init__(self, responses: Sequence[dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | Exception]):
        self.responses = list(responses)
        self.calls: list[tuple[str, list[BaseMessage]]] = []

    def structured(
        self, schema: type[T], messages: Sequence[BaseMessage], context: dict[str, Any] | None = None
    ) -> LLMResult:
        self.calls.append((schema.__name__, list(messages)))
        if not self.responses:
            raise LLMError("script exhausted")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        data = nxt(context or {}) if callable(nxt) else nxt
        try:
            return LLMResult(schema.model_validate(data), 100, 20)
        except ValidationError as exc:
            raise LLMError(f"could not parse scripted output: {exc}") from exc


_POSITION = re.compile(r"\b(motor|esc)_(\d)\b")


class RuleBasedLLM:
    """Deterministic policy used where no API key is available (CI smoke eval).

    Plan: list tests, run each test once in ascending cost order while budget
    allows, search the library once after the first failure (library mode),
    then propose the top library match. Without the library it reports
    HEALTHY when nothing failed and UNKNOWN otherwise. This is a plumbing
    check, not a diagnostic baseline.
    """

    model_name = "rule-based-mock"

    def structured(
        self, schema: type[T], messages: Sequence[BaseMessage], context: dict[str, Any] | None = None
    ) -> LLMResult:
        ctx = context or {}
        if schema.__name__ == "Observation":
            return LLMResult(schema.model_validate(self._observe(ctx)))
        return LLMResult(schema.model_validate(self._plan(ctx)))

    def _observe(self, ctx: dict[str, Any]) -> dict[str, Any]:
        hyps = list(ctx.get("hypotheses", []))
        result = ctx.get("last_result") or {}
        if ctx.get("last_tool") == "search_failure_library":
            matches = result.get("matches", [])
            hyps = [
                {"root_cause_code": m["root_cause_code"], "confidence": round(0.6 / (i + 1), 2), "rationale": m["title"]}
                for i, m in enumerate(matches)
            ]
        return {"summary": f"{ctx.get('last_tool')} done", "hypotheses": hyps}

    def _plan(self, ctx: dict[str, Any]) -> dict[str, Any]:
        steps: list[dict[str, Any]] = ctx.get("steps", [])
        done = {s["args"].get("test_name") for s in steps if s["tool"] == "run_test"}
        failures = [f for s in steps if s["tool"] == "run_test" for f in s["result"].get("failures", [])]
        searched = any(s["tool"] == "search_failure_library" for s in steps)
        catalog: list[dict[str, Any]] = ctx.get("catalog") or []
        if not ctx.get("must_finalize"):
            if not steps or not catalog:
                return {"thought": "Get the test catalog.", "tool": "list_tests"}
            if failures and ctx.get("use_library") and not searched:
                return {"thought": "Look up failures.", "tool": "search_failure_library", "query": "; ".join(failures)}
            remaining = ctx.get("time_budget_s", 0.0) - ctx.get("test_time_s", 0.0)
            for t in sorted(catalog, key=lambda t: t["cost_s"]):
                if t["name"] not in done and t["cost_s"] <= remaining and not (failures and searched):
                    return {"thought": f"Run {t['name']}.", "tool": "run_test", "test_name": t["name"]}
        hyps = ctx.get("hypotheses") or []
        if not failures:
            code, action = "HEALTHY", "none"
        elif hyps:
            code = hyps[0]["root_cause_code"]
            actions = {
                m["root_cause_code"]: m["rework_action"]
                for s in steps
                if s["tool"] == "search_failure_library"
                for m in s["result"].get("matches", [])
            }
            action = actions.get(code) or "none"
        else:
            code, action = "UNKNOWN", "none"
        pos = _POSITION.search(" ".join(failures))
        target = None
        if pos and action in ("replace_motor", "reflash_esc_firmware"):
            kind = "motor" if action == "replace_motor" else "esc"
            target = f"{kind}_{pos.group(2)}"
        return {
            "thought": "Finalize.",
            "tool": "propose_rework",
            "root_cause": code,
            "confidence": hyps[0]["confidence"] if hyps and failures else 0.5,
            "rework_action": action,
            "rework_target": target,
            "evidence_tests": sorted(t for t in done if t),
        }
