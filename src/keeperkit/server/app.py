"""FastAPI app powering the KeeperKit demo dashboard.

The demo intentionally has *two* modes:

* **Direct tool mode** — ``POST /api/tools/{name}`` calls a single KeeperKit
  tool with the supplied arguments. No LLM. The catalogue includes both the
  "static" discovery / call tools and one auto-generated tool per
  discoverable KeeperHub workflow.
* **Agent mode** — ``POST /api/agent/run`` spins up a LangChain ReAct agent
  bound to the same tool catalogue and forwards the user's prompt.

Both modes can run against the real KeeperHub API or the in-memory mock,
controlled by ``KEEPERKIT_MODE`` (``real`` / ``mock``).
"""

from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from keeperkit import __version__
from keeperkit.client import KeeperHubClient
from keeperkit.exceptions import KeeperHubAuthError
from keeperkit.mock import MockKeeperHubClient
from keeperkit.server.llm import detect_provider
from keeperkit.tools._common import (
    ToolSpec,
    build_all_tool_specs,
    safe_dispatch,
)

HERE = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(HERE / "templates"))


def _build_client() -> tuple[Any, str]:
    mode = os.environ.get("KEEPERKIT_MODE", "real").strip().lower()
    if mode == "mock":
        return MockKeeperHubClient(), "mock"
    api_key = os.environ.get("KEEPERHUB_API_KEY", "").strip()
    if not api_key:
        # Fall back to mock if no key is configured. We never want the demo
        # server to hard-crash at startup just because someone forgot to set
        # an env var — the UI will say "running in mock mode".
        return MockKeeperHubClient(), "mock-fallback"
    try:
        client = KeeperHubClient.from_env()
        return client, "real"
    except KeeperHubAuthError:
        return MockKeeperHubClient(), "mock-fallback"


def _build_tool_specs(client: Any) -> list[ToolSpec]:
    """Build the full catalogue. Falls back to static tools if discovery fails."""
    try:
        return build_all_tool_specs(client)
    except Exception:  # noqa: BLE001 - degrade to static-only on network/listing errors
        from keeperkit.tools._common import STATIC_TOOL_SPECS
        return list(STATIC_TOOL_SPECS)


def _client_meta(client: Any, mode: str, tool_count: int) -> dict[str, Any]:
    is_mock = isinstance(client, MockKeeperHubClient)
    provider = detect_provider()
    return {
        "mode": mode,
        "is_mock": is_mock,
        "base_url": getattr(client, "base_url", "in-memory") if not is_mock else "in-memory",
        "version": __version__,
        "llm_provider": provider or "heuristic",
        "llm_model": (os.environ.get("KEEPERKIT_LLM_MODEL")
                      or os.environ.get("OPENAI_MODEL")
                      or None),
        "tool_count": tool_count,
    }


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = {}


class AgentRunRequest(BaseModel):
    prompt: str
    use_mock: bool | None = None  # explicit override, otherwise follow env


def _spec_summary(spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.parameters,
        "metadata": dict(spec.metadata or {}),
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="KeeperKit Demo",
        version=__version__,
        description=(
            "Reference dashboard for the KeeperKit plugin — see "
            "https://github.com/danilaverbena/keeperkit"
        ),
    )

    static_dir = HERE / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    state: dict[str, Any] = {}

    def _refresh_specs() -> list[ToolSpec]:
        specs = _build_tool_specs(state["client"])
        state["specs"] = specs
        return specs

    def _find_spec(name: str) -> ToolSpec:
        for s in state.get("specs", []):
            if s.name == name:
                return s
        raise KeyError(f"unknown tool: {name!r}")

    @app.on_event("startup")
    def _startup() -> None:
        client, mode = _build_client()
        state["client"] = client
        state["mode"] = mode
        _refresh_specs()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        client = state.get("client")
        if client and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Any:
        specs = state.get("specs") or _refresh_specs()
        meta = _client_meta(state["client"], state["mode"], len(specs))
        tools = [_spec_summary(s) for s in specs]
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"meta": meta, "tools": tools},
        )

    # --------------------------------------------------------------- meta API
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        specs = state.get("specs") or []
        return {"ok": True, **_client_meta(state["client"], state["mode"], len(specs))}

    @app.get("/api/tools")
    def list_tools() -> list[dict[str, Any]]:
        return [_spec_summary(s) for s in (state.get("specs") or [])]

    @app.post("/api/tools/_refresh")
    def refresh_tools() -> dict[str, Any]:
        specs = _refresh_specs()
        return {"ok": True, "tool_count": len(specs)}

    # -------------------------------------------------------- direct tool API
    @app.post("/api/tools/{name}")
    def call_tool(name: str, payload: ToolCallRequest) -> dict[str, Any]:
        try:
            spec = _find_spec(name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            return safe_dispatch(spec, state["client"], **payload.arguments)
        except Exception as exc:  # noqa: BLE001 - surface to UI
            return {"ok": False, "error": str(exc),
                    "trace": traceback.format_exc(limit=2)}

    # -------------------------------------------------------------- agent API
    @app.post("/api/agent/run")
    async def agent_run(req: AgentRunRequest) -> JSONResponse:
        if req.use_mock is True:
            client: Any = MockKeeperHubClient()
            mode = "mock"
        else:
            client = state["client"]
            mode = state["mode"]

        try:
            from keeperkit.server.agent import run_agent
        except ImportError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)

        try:
            result = await run_agent(client, req.prompt)
        except Exception as exc:  # noqa: BLE001 - surface to UI
            return JSONResponse(
                {"ok": False, "error": str(exc),
                 "trace": traceback.format_exc(limit=4),
                 "mode": mode},
                status_code=500,
            )
        return JSONResponse({"ok": True, "mode": mode, **result})

    # ------------------------------------------------------ ElizaOS descriptor
    @app.get("/api/elizaos/plugin.json")
    def elizaos_plugin() -> dict[str, Any]:
        from keeperkit.tools.elizaos import build_elizaos_plugin_descriptor
        base_url = os.environ.get("KEEPERHUB_BASE_URL",
                                  "https://app.keeperhub.com/api")
        return build_elizaos_plugin_descriptor(client=state["client"],
                                                base_url=base_url)

    # -------------------------------------------------------- tool dispatch fwd
    @app.post("/keeperkit/dispatch")
    def elizaos_dispatch(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        tool_name = payload.get("tool")
        if not tool_name:
            raise HTTPException(400, "missing 'tool' field in dispatch payload")
        try:
            spec = _find_spec(tool_name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        args = payload.get("arguments") or {}
        return safe_dispatch(spec, state["client"], **args)

    return app


app = create_app()
