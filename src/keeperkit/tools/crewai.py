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

Like the LangChain factory, this returns a tool *per* discoverable
KeeperHub workflow plus the static discovery / call tools.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from keeperkit.tools._common import (
    ToolSpec,
    build_all_tool_specs,
    safe_dispatch,
)


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
    properties = schema.get("properties", {}) or {}
    required = set(schema.get("required", []) or [])
    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue
        py_type = _TYPE_MAP.get(prop_schema.get("type", "string"), str)
        description = prop_schema.get("description", "")
        default = prop_schema.get("default", ...)
        if prop_name not in required and default is ...:
            default = None
            py_type = py_type | None  # type: ignore[operator]
        safe_name = prop_name.lstrip("_") or prop_name
        fields[safe_name] = (py_type, Field(default=default, description=description))
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
            return safe_dispatch(spec, client, **clean)

    _KeeperHubCrewTool.__name__ = f"KeeperHub_{spec.name}_Tool"
    return _KeeperHubCrewTool


def build_crewai_tools(
    client: Any,
    *,
    only: Iterable[str] | None = None,
    include_per_workflow: bool = True,
) -> list[Any]:
    """Return CrewAI ``BaseTool`` instances bound to ``client``."""
    if include_per_workflow:
        specs = build_all_tool_specs(client)
    else:
        from keeperkit.tools._common import STATIC_TOOL_SPECS
        specs = list(STATIC_TOOL_SPECS)

    keep = set(only) if only else None
    tools: list[Any] = []
    for spec in specs:
        if keep is not None and spec.name not in keep:
            continue
        tool_cls = _make_tool_class(client, spec)
        tools.append(tool_cls())
    return tools
