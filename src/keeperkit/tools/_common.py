"""Framework-agnostic tool definitions consumed by the LangChain / CrewAI shims.

Each tool is described once here as a :class:`ToolSpec` (name, description,
JSON schema, dispatch callable). Three "static" tools are always present —
``list_workflows``, ``call_workflow``, ``get_openapi`` — and one extra tool
is **auto-generated per discoverable workflow** in the catalogue. That way
your agent gets a typed, named tool for every KeeperHub workflow without
any hardcoding: add a new workflow on KeeperHub, refresh the tool list,
and the agent picks it up.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


class _ClientProto(Protocol):
    """Minimal client surface our tool dispatchers rely on."""

    def list_workflows(self) -> Any: ...
    def get_openapi(self) -> Any: ...
    def call_workflow(self, slug: str, body: dict[str, Any] | None = ...,
                      *, x_payment: str | None = ...) -> Any: ...
    def list_org_workflows(self) -> Any: ...
    def list_integrations(self) -> Any: ...


DispatchFn = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    """A framework-agnostic tool description."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema fragment for the args
    dispatch: DispatchFn         # signature: dispatch(client, **kwargs) -> Any
    metadata: dict[str, Any] = field(default_factory=dict)


def _serialize(obj: Any) -> Any:
    """Turn arbitrary tool output into something JSON-friendly."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)


def _slug_to_ident(slug: str) -> str:
    """Convert a workflow slug into a Python-safe identifier suffix."""
    ident = re.sub(r"[^A-Za-z0-9]+", "_", slug).strip("_").lower()
    return ident or "workflow"


# ---------------------------------------------------------------------------
# Generic dispatch helper used by adapters (catches errors, returns dict).
# ---------------------------------------------------------------------------


def safe_dispatch(spec: ToolSpec, client: _ClientProto, **kwargs: Any) -> dict[str, Any]:
    """Invoke ``spec.dispatch`` and wrap success / failure into a dict.

    All framework adapters route through this so the LLM sees a uniform
    ``{ok, data}`` / ``{ok: false, error, ...}`` shape.
    """
    from keeperkit.exceptions import KeeperHubAPIError, KeeperHubPaymentRequired

    try:
        result = spec.dispatch(client, **kwargs)
    except KeeperHubPaymentRequired as exc:
        return {
            "ok": False,
            "error": "payment_required",
            "message": str(exc),
            "x402": exc.x402,
            "amount_usdc": exc.amount_usdc,
            "hint": (
                "This is a paid KeeperHub workflow. Settle via your x402 client "
                "(agentcash / openclaw / custom signer) and replay the call with "
                "an `X-Payment` header."
            ),
        }
    except KeeperHubAPIError as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "status": exc.status_code,
            "message": str(exc),
            "payload": _serialize(exc.payload),
        }
    except Exception as exc:  # noqa: BLE001 - surface unexpected failures
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}

    return {"ok": True, "data": _serialize(result)}


# ---------------------------------------------------------------------------
# Static tools (always present) — discovery + universal call entry point.
# ---------------------------------------------------------------------------


def _dispatch_list_workflows(client: _ClientProto) -> Any:
    return client.list_workflows()


def _dispatch_get_openapi(client: _ClientProto) -> Any:
    return client.get_openapi()


def _dispatch_call_workflow(
    client: _ClientProto,
    *,
    slug: str,
    body: dict[str, Any] | None = None,
    x_payment: str | None = None,
) -> Any:
    return client.call_workflow(slug, body or {}, x_payment=x_payment)


def _dispatch_list_org_workflows(client: _ClientProto) -> Any:
    return client.list_org_workflows()


def _dispatch_list_integrations(client: _ClientProto) -> Any:
    return client.list_integrations()


def _make_call_workflow_for_slug(slug: str) -> DispatchFn:
    """Return a dispatch function that calls a *fixed* workflow slug.

    Each generated tool needs its own closure so the LLM doesn't have to
    pass the slug back as an argument.
    """

    def _dispatch(client: _ClientProto, **body: Any) -> Any:
        x_payment = body.pop("_x_payment", None) if "_x_payment" in body else None
        return client.call_workflow(slug, body, x_payment=x_payment)

    return _dispatch


STATIC_TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="keeperhub_list_workflows",
        description=(
            "Discover the public KeeperHub workflow catalogue. Returns each "
            "workflow's slug, input JSON Schema, price (USDC), workflow type "
            "(read|write), category, and target chain. Use this whenever you "
            "need to choose which KeeperHub action to take next."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        dispatch=_dispatch_list_workflows,
        metadata={"static": True},
    ),
    ToolSpec(
        name="keeperhub_call_workflow",
        description=(
            "Invoke any KeeperHub workflow by slug. The body must satisfy the "
            "workflow's inputSchema (use keeperhub_list_workflows to look it "
            "up). Returns {executionId, status, output}. Paid workflows return "
            "an x402 payment-required descriptor instead of executing — settle "
            "with your x402 client and pass the X-Payment token via x_payment."
        ),
        parameters={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Workflow slug, e.g. 'helloworld' or 'aave-v3-health-check'.",
                },
                "body": {
                    "type": "object",
                    "description": "Workflow input matching its inputSchema.",
                    "additionalProperties": True,
                },
                "x_payment": {
                    "type": "string",
                    "description": "Optional x402 payment token (X-Payment header).",
                },
            },
            "required": ["slug"],
            "additionalProperties": False,
        },
        dispatch=_dispatch_call_workflow,
        metadata={"static": True},
    ),
    ToolSpec(
        name="keeperhub_get_openapi",
        description=(
            "Fetch the KeeperHub OpenAPI document. Useful when the agent needs "
            "the per-workflow JSON Schema (request/response) or the worked "
            "examples in info.x-guidance."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        dispatch=_dispatch_get_openapi,
        metadata={"static": True},
    ),
    ToolSpec(
        name="keeperhub_list_org_workflows",
        description=(
            "List the workflows owned by *your* KeeperHub organization (the "
            "one tied to your KEEPERHUB_API_KEY). Use this when you want to "
            "operate only on workflows you yourself authored, not the public "
            "catalogue."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        dispatch=_dispatch_list_org_workflows,
        metadata={"static": True},
    ),
    ToolSpec(
        name="keeperhub_list_integrations",
        description=(
            "List wallet / connector integrations configured on your "
            "KeeperHub org. Returns chain id, integration id, and connector "
            "metadata. Required input for some write workflows."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        dispatch=_dispatch_list_integrations,
        metadata={"static": True},
    ),
)


# ---------------------------------------------------------------------------
# Per-workflow tool generation.
# ---------------------------------------------------------------------------


def build_workflow_tools(client: _ClientProto) -> list[ToolSpec]:
    """Generate one :class:`ToolSpec` per discoverable workflow.

    Each tool's name is ``keeperhub_<slug-as-ident>``, its parameters match
    the workflow's ``inputSchema``, and its description includes the workflow
    description, price, type, and chain so the LLM can pick the right one.
    """
    catalogue = client.list_workflows()
    items = catalogue.get("items") if isinstance(catalogue, dict) else catalogue
    items = items or []

    specs: list[ToolSpec] = []
    seen: set[str] = set()
    for wf in items:
        slug = wf.get("listedSlug")
        if not slug:
            continue
        ident = _slug_to_ident(slug)
        name = f"keeperhub_{ident}"
        # Avoid duplicate names if multiple workflows collide on slug shape.
        if name in seen:
            continue
        seen.add(name)

        price = wf.get("priceUsdcPerCall")
        wf_type = wf.get("workflowType") or "read"
        chain = wf.get("chain")

        descr_parts = [wf.get("description", "").strip() or wf.get("name", slug)]
        descr_parts.append(f"[type={wf_type}, slug='{slug}'"
                           + (f", chain={chain}" if chain else "")
                           + (f", price={price} USDC" if price else ", free")
                           + "]")
        if price:
            descr_parts.append(
                "Returns x402 payment_required if no X-Payment token is provided."
            )
        description = " ".join(descr_parts)

        schema = wf.get("inputSchema") or {"type": "object", "properties": {}}
        # JSON Schema in some catalogues lacks "type": "object" at the top level.
        if "type" not in schema:
            schema = {"type": "object", **schema}

        specs.append(
            ToolSpec(
                name=name,
                description=description,
                parameters=schema,
                dispatch=_make_call_workflow_for_slug(slug),
                metadata={
                    "static": False,
                    "slug": slug,
                    "price_usdc_per_call": price,
                    "workflow_type": wf_type,
                    "chain": chain,
                    "category": wf.get("category"),
                },
            )
        )
    return specs


def build_all_tool_specs(client: _ClientProto) -> list[ToolSpec]:
    """Static tools + one tool per discoverable workflow."""
    return [*STATIC_TOOL_SPECS, *build_workflow_tools(client)]


def find_spec(name: str, specs: list[ToolSpec] | None = None) -> ToolSpec:
    """Look up a spec by name. Raises :class:`KeyError` if absent."""
    haystack = specs if specs is not None else list(STATIC_TOOL_SPECS)
    for spec in haystack:
        if spec.name == name:
            return spec
    raise KeyError(f"unknown tool: {name!r}")
