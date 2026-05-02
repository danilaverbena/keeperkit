"""LangChain (langchain-core) tool factory for KeeperHub.

Use it like::

    from keeperkit import KeeperHubClient
    from keeperkit.tools.langchain import build_langchain_tools
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    client = KeeperHubClient.from_env()
    tools = build_langchain_tools(client)
    agent = create_react_agent(ChatOpenAI(model="gpt-4o-mini"), tools)

The factory returns a list of :class:`langchain_core.tools.StructuredTool`
objects bound to the supplied client. Each tool maps 1:1 to a KeeperHub
operation and surfaces the parameters declared in
``KEEPERHUB_TOOL_SPECS``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from keeperkit.tools._common import KEEPERHUB_TOOL_SPECS, ToolSpec, default_dispatch


def _import_langchain():
    try:
        from langchain_core.tools import StructuredTool  # type: ignore
        from pydantic import BaseModel, Field, create_model  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "LangChain support requires `langchain-core`. Install with "
            "`pip install keeperkit[langchain]` or `pip install langchain-core`."
        ) from exc
    return StructuredTool, BaseModel, Field, create_model


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _model_from_jsonschema(name: str, schema: dict[str, Any]):
    """Build a pydantic model class from a tool's JSON Schema parameters."""
    _, BaseModel, Field, create_model = _import_langchain()
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


def _make_tool(client: Any, spec: ToolSpec):
    StructuredTool, _, _, _ = _import_langchain()
    args_model = _model_from_jsonschema(f"{spec.name}_Args", spec.parameters)

    def _run(**kwargs: Any) -> dict[str, Any]:
        kwargs.pop("noop", None)
        # Only forward keys that are not None to keep client signatures clean.
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return default_dispatch(client, spec, **clean)

    return StructuredTool.from_function(
        func=_run,
        name=spec.name,
        description=spec.description,
        args_schema=args_model,
    )


def build_langchain_tools(client: Any,
                          *, only: Iterable[str] | None = None) -> list[Any]:
    """Return a list of LangChain ``StructuredTool``s bound to ``client``.

    Args:
        client: A :class:`KeeperHubClient` or :class:`MockKeeperHubClient`.
        only: Optional iterable of tool names to include. If omitted, all
            KeeperHub tools are returned.
    """
    keep = set(only) if only else None
    tools = []
    for spec in KEEPERHUB_TOOL_SPECS:
        if keep is not None and spec.name not in keep:
            continue
        tools.append(_make_tool(client, spec))
    return tools
