"""CrewAI tool factory for KeeperHub.

Usage::

    from keeperkit import KeeperHubClient
    from keeperkit.tools.crewai import build_crewai_tools
    from crewai import Agent, Task, Crew

    client = KeeperHubClient.from_env()
    tools = build_crewai_tools(client)

    trader = Agent(
        role="Onchain Trader",
        goal="Execute trades reliably on Sepolia.",
        tools=tools,
        backstory="You delegate every transaction to KeeperHub.",
    )

CrewAI builds on top of pydantic BaseTool, so the surface mirrors LangChain
fairly closely; we still keep a separate factory because CrewAI imports
``crewai.tools.BaseTool`` and expects ``_run`` semantics.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from keeperkit.tools._common import KEEPERHUB_TOOL_SPECS, ToolSpec, default_dispatch


def _import_crewai():
    try:
        from crewai.tools import BaseTool  # type: ignore
        from pydantic import BaseModel, Field, create_model  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "CrewAI support requires `crewai`. Install with "
            "`pip install keeperkit[crewai]` or `pip install crewai`."
        ) from exc
    return BaseTool, BaseModel, Field, create_model


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _model_from_jsonschema(name: str, schema: dict[str, Any]):
    _, BaseModel, Field, create_model = _import_crewai()
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        py_type = _TYPE_MAP.get(prop_schema.get("type", "string"), str)
        description = prop_schema.get("description", "")
        default = prop_schema.get("default", ...)
        if prop_name not in required and default is ...:
            default = None
            py_type = py_type | None  # type: ignore[operator]
        fields[prop_name] = (py_type, Field(default=default, description=description))
    if not fields:
        fields["noop"] = (
            str | None,  # type: ignore[operator]
            Field(default=None, description="(no parameters)"),
        )
    return create_model(name, __base__=BaseModel, **fields)


def _make_tool_class(client: Any, spec: ToolSpec):
    BaseTool, _, _, _ = _import_crewai()
    args_schema = _model_from_jsonschema(f"{spec.name}_Args", spec.parameters)

    class _KeeperHubCrewTool(BaseTool):  # type: ignore[misc]
        name: str = spec.name
        description: str = spec.description
        args_schema: type = args_schema

        def _run(self, **kwargs: Any) -> dict[str, Any]:
            kwargs.pop("noop", None)
            clean = {k: v for k, v in kwargs.items() if v is not None}
            return default_dispatch(client, spec, **clean)

    _KeeperHubCrewTool.__name__ = f"KeeperHub_{spec.name}_Tool"
    return _KeeperHubCrewTool


def build_crewai_tools(client: Any,
                       *, only: Iterable[str] | None = None) -> list[Any]:
    """Return a list of CrewAI ``BaseTool`` instances bound to ``client``."""
    keep = set(only) if only else None
    tools = []
    for spec in KEEPERHUB_TOOL_SPECS:
        if keep is not None and spec.name not in keep:
            continue
        tool_cls = _make_tool_class(client, spec)
        tools.append(tool_cls())
    return tools
