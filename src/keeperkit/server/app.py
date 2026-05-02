"""FastAPI app powering the KeeperKit demo dashboard.

The demo intentionally has *two* modes:

* **Direct tool mode** — ``POST /api/tools/{name}`` calls a single KeeperHub
  tool with the supplied arguments. No LLM. Useful as a smoke test and as a
  KeeperHub MCP-style HTTP bridge.
* **Agent mode** — ``POST /api/agent/run`` spins up a LangChain ReAct agent
  bound to the full KeeperHub tool catalogue and forwards the user's prompt.
  This is the "sees a real agent flow end-to-end" demo.

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
from keeperkit.exceptions import KeeperHubAPIError, KeeperHubAuthError
from keeperkit.mock import MockKeeperHubClient
from keeperkit.tools._common import KEEPERHUB_TOOL_SPECS, default_dispatch, find_spec

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


def _client_meta(client: Any, mode: str) -> dict[str, Any]:
    is_mock = isinstance(client, MockKeeperHubClient)
    return {
        "mode": mode,
        "is_mock": is_mock,
        "base_url": getattr(client, "base_url", "in-memory") if not is_mock else "in-memory",
        "version": __version__,
    }


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = {}


class AgentRunRequest(BaseModel):
    prompt: str
    use_mock: bool | None = None  # explicit override, otherwise follow env


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

    @app.on_event("startup")
    def _startup() -> None:
        client, mode = _build_client()
        state["client"] = client
        state["mode"] = mode

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
        meta = _client_meta(state["client"], state["mode"])
        tools = [
            {
                "name": s.name,
                "description": s.description,
                "parameters": s.parameters,
            }
            for s in KEEPERHUB_TOOL_SPECS
        ]
        return TEMPLATES.TemplateResponse(
            request,
            "index.html",
            {"meta": meta, "tools": tools},
        )

    # --------------------------------------------------------------- meta API
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, **_client_meta(state["client"], state["mode"])}

    @app.get("/api/tools")
    def list_tools() -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "parameters": s.parameters,
            }
            for s in KEEPERHUB_TOOL_SPECS
        ]

    # -------------------------------------------------------- direct tool API
    @app.post("/api/tools/{name}")
    def call_tool(name: str, payload: ToolCallRequest) -> dict[str, Any]:
        try:
            spec = find_spec(name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            return default_dispatch(state["client"], spec, **payload.arguments)
        except KeeperHubAPIError as exc:
            return {"ok": False, "error": str(exc), "status_code": exc.status_code}
        except Exception as exc:  # noqa: BLE001 - surface to UI
            return {"ok": False, "error": str(exc), "trace": traceback.format_exc(limit=2)}

    # -------------------------------------------------------------- agent API
    @app.post("/api/agent/run")
    async def agent_run(req: AgentRunRequest) -> JSONResponse:
        # Decide which client to use for THIS run (allows testing mock without
        # restarting the server).
        if req.use_mock is True:
            client: Any = MockKeeperHubClient()
            mode = "mock"
        elif req.use_mock is False:
            client = state["client"]
            mode = state["mode"]
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
        base_url = os.environ.get("KEEPERHUB_BASE_URL", "https://app.keeperhub.com/api")
        return build_elizaos_plugin_descriptor(base_url=base_url)

    # -------------------------------------------------------- tool dispatch fwd
    # ElizaOS plugin descriptor points action invocations back to /keeperkit/dispatch.
    @app.post("/keeperkit/dispatch")
    def elizaos_dispatch(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        tool_name = payload.get("tool")
        if not tool_name:
            raise HTTPException(400, "missing 'tool' field in dispatch payload")
        try:
            spec = find_spec(tool_name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        args = payload.get("arguments") or {}
        try:
            return default_dispatch(state["client"], spec, **args)
        except KeeperHubAPIError as exc:
            return {"ok": False, "error": str(exc), "status_code": exc.status_code}

    return app


app = create_app()
