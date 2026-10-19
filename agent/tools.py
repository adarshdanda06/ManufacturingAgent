"""Tool wrappers around the factory test station API.

``FactoryClient`` speaks to the Flask API either over real HTTP or through an
in-process Flask test client (same routes, no socket). ``build_tools`` turns a
client and an optional retriever into the LangChain tools the agent can call.
The client only ever sends a unit ID; it has no way to learn the fault.
"""

from __future__ import annotations

from typing import Any, Protocol

import requests
from langchain_core.tools import BaseTool, StructuredTool

from agent.retrieval import Retriever


class Transport(Protocol):
    """Minimal HTTP verb interface shared by real and in-process transports."""

    def request(self, method: str, path: str, json: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        """Send a request and return ``(status_code, json_body)``."""
        ...


class HttpTransport:
    """Talks to a running factory API, for example ``http://localhost:5000``."""

    def __init__(self, base_url: str, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._session = requests.Session()

    def request(self, method: str, path: str, json: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        resp = self._session.request(method, self.base_url + path, json=json, timeout=self.timeout_s)
        return resp.status_code, resp.json()


class FlaskTransport:
    """Calls the API routes in-process through ``app.test_client()``."""

    def __init__(self, app: Any) -> None:
        self._client = app.test_client()

    def request(self, method: str, path: str, json: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        resp = self._client.open(path, method=method, json=json)
        return resp.status_code, resp.get_json()


class FactoryClient:
    """Typed access to one unit on the test station."""

    def __init__(self, transport: Transport, unit_id: str) -> None:
        self.transport = transport
        self.unit_id = unit_id
        self._catalog: dict[str, dict[str, Any]] | None = None

    def _call(self, method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        status, body = self.transport.request(method, path, json)
        if status >= 400:
            return {"error": body.get("error", f"HTTP {status}"), "status": status}
        return body

    def list_tests(self) -> dict[str, Any]:
        """Return the test catalog with per-test cost in simulated seconds."""
        body = self._call("GET", f"/units/{self.unit_id}/tests")
        if "tests" in body:
            self._catalog = {t["name"]: t for t in body["tests"]}
        return body

    def catalog(self) -> dict[str, dict[str, Any]]:
        """Cached test catalog keyed by name (fetched once, not charged as a step)."""
        if self._catalog is None:
            self.list_tests()
        return self._catalog or {}

    def run_test(self, test_name: str) -> dict[str, Any]:
        """Run one test and return the ``TestResult`` JSON."""
        return self._call("POST", f"/units/{self.unit_id}/tests/{test_name}")

    def rework(self, action: str, target: str | None) -> dict[str, Any]:
        """Apply a rework action and return the ``ReworkResult`` JSON."""
        return self._call("POST", f"/units/{self.unit_id}/rework", {"action": action, "target": target})

    def rework_actions(self) -> list[dict[str, str]]:
        """Rework actions the station supports."""
        actions: list[dict[str, str]] = self._call("GET", "/rework/actions").get("actions", [])
        return actions


def build_tools(client: FactoryClient, retriever: Retriever | None, top_k: int = 3) -> dict[str, BaseTool]:
    """Build the agent's tools. ``search_failure_library`` is omitted when ``retriever`` is None."""

    def list_tests() -> dict[str, Any]:
        """List the tests available on the station and their cost in simulated seconds."""
        return client.list_tests()

    def run_test(test_name: str) -> dict[str, Any]:
        """Run one station test on the unit and return readings, pass/fail and failures."""
        return client.run_test(test_name)

    def propose_rework(action: str, target: str | None = None) -> dict[str, Any]:
        """Apply the recommended rework and re-run the full suite. Use action 'none' for a healthy unit."""
        if action == "none":
            return {"applied": False, "action": "none", "suite_passed": None}
        out = client.rework(action, target)
        if "error" not in out:
            out["applied"] = True
        return out

    tools: dict[str, BaseTool] = {
        "list_tests": StructuredTool.from_function(list_tests),
        "run_test": StructuredTool.from_function(run_test),
        "propose_rework": StructuredTool.from_function(propose_rework),
    }
    if retriever is not None:

        def search_failure_library(query: str) -> dict[str, Any]:
            """Search historical failure records with a plain-text description of observed symptoms."""
            matches = retriever.search(query, k=top_k)
            return {
                "retriever": retriever.name,
                "matches": [{**m.record.to_dict(), "score": m.score} for m in matches],
            }

        tools["search_failure_library"] = StructuredTool.from_function(search_failure_library)
    return tools
