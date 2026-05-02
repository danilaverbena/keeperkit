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
objects bound to the supplied client. The list contains:

* a small set of *static* tools — discovery (``keeperhub_list_workflows``,
  ``keeperhub_get_openapi``, …), a universal ``keeperhub_call_workflow``,
  and ``keeperhub_list_org_workflows`` / ``keeperhub_list_integrations``
  for builders.
* one *auto-generated* tool per discoverable workflow — name
  ``keeperhub_<slug>``, parameters built from the workflow's
  ``inputSchema``, description annotated with workflow type / chain /
  price.

Add a new workflow on KeeperHub → call ``build_langchain_tools(client)``
again → the new tool appears with no code changes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from keeperkit.tools._common import (
    ToolSpec,
    build_all_tool_specs,
    safe_dispatch,
)


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
        # Sanitize field name for pydantic (drop leading underscores etc.).
        safe_name = prop_name.lstrip("_") or prop_name
        fields[safe_name] = (py_type, Field(default=default, description=description))
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
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return safe_dispatch(spec, client, **clean)

    return StructuredTool.from_function(
        func=_run,
        name=spec.name,
        description=spec.description,
        args_schema=args_model,
    )


def build_langchain_tools(
    client: Any,
    *,
    only: Iterable[str] | None = None,
    include_per_workflow: bool = True,
) -> list[Any]:
    """Return a list of LangChain ``StructuredTool``s bound to ``client``.

    Args:
        client: A :class:`KeeperHubClient` or :class:`MockKeeperHubClient`.
        only: Optional iterable of tool names to include. If omitted, all
            KeeperHub tools are returned.
        include_per_workflow: When True (default), additionally generate one
            tool per discoverable workflow in ``client.list_workflows()``.
            Set to False to keep just the five static tools (e.g. when you
            don't want to make a network round-trip at startup).
    """
    if include_per_workflow:
        specs = build_all_tool_specs(client)
    else:
        from keeperkit.tools._common import STATIC_TOOL_SPECS
        specs = list(STATIC_TOOL_SPECS)

    keep = set(only) if only else None
    return [_make_tool(client, s) for s in specs if keep is None or s.name in keep]
