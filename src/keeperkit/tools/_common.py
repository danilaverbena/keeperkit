"""Framework-agnostic tool definitions consumed by the LangChain / CrewAI shims.

Each tool is described once here as a :class:`ToolSpec` (name, description,
JSON schema, dispatch function), then the framework adapters turn that into
LangChain ``BaseTool`` instances or CrewAI ``Tool`` instances. This way new
frameworks can be added in one file without touching the core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from keeperkit.models import Network


class _ClientProto(Protocol):
    """Subset of the client interface our tools rely on (sync)."""

    def list_workflows(self, *, limit: int = ..., offset: int = ...) -> Any: ...
    def get_workflow(self, workflow_id: str) -> Any: ...
    def create_workflow(self, workflow: Any) -> Any: ...
    def execute_workflow(self, workflow_id: str,
                         inputs: dict[str, Any] | None = ...) -> Any: ...
    def get_execution_status(self, execution_id: str) -> Any: ...
    def get_execution_logs(self, execution_id: str) -> Any: ...
    def execute_action(self, action_type: str, config: dict[str, Any],
                       *, network: str | None = ...) -> Any: ...
    def list_action_schemas(self, *, category: str | None = ...) -> Any: ...
    def ai_generate_workflow(self, description: str,
                             *, modify_workflow_id: str | None = ...) -> Any: ...


@dataclass(frozen=True)
class ToolSpec:
    """A framework-agnostic tool description."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema fragment
    dispatch_key: str  # which client method we proxy to


def _serialize(obj: Any) -> Any:
    """Turn pydantic / dict / list output into something JSON-friendly."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return str(obj)


def default_dispatch(client: _ClientProto, spec: ToolSpec,
                     **kwargs: Any) -> dict[str, Any]:
    """Generic dispatcher used by all framework adapters."""
    method = getattr(client, spec.dispatch_key)
    result = method(**kwargs)
    return {"ok": True, "data": _serialize(result)}


# ---------------------------------------------------------------------------
# Tool catalogue. Keep these descriptions LLM-readable: the agent reads them
# verbatim to decide when to call.
# ---------------------------------------------------------------------------

_NETWORK_DESC = (
    "EVM chain ID as a string. Common values: "
    + ", ".join(f"'{n.value}' ({n.name.lower()})" for n in Network)
    + "."
)

KEEPERHUB_TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="keeperhub_list_workflows",
        description=(
            "List workflows already configured in your KeeperHub organization. "
            "Use this to discover existing automations the agent can reuse "
            "instead of building from scratch."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
                "offset": {"type": "integer", "default": 0, "minimum": 0},
            },
            "additionalProperties": False,
        },
        dispatch_key="list_workflows",
    ),
    ToolSpec(
        name="keeperhub_get_workflow",
        description="Fetch the full configuration (nodes + edges) of a workflow by id.",
        parameters={
            "type": "object",
            "properties": {"workflow_id": {"type": "string"}},
            "required": ["workflow_id"],
            "additionalProperties": False,
        },
        dispatch_key="get_workflow",
    ),
    ToolSpec(
        name="keeperhub_execute_workflow",
        description=(
            "Trigger a stored KeeperHub workflow by id and return the execution "
            "envelope. KeeperHub handles retries, gas optimization, simulation, "
            "and private MEV-aware routing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
                "inputs": {
                    "type": "object",
                    "description": "Optional input payload passed to the workflow.",
                },
            },
            "required": ["workflow_id"],
            "additionalProperties": False,
        },
        dispatch_key="execute_workflow",
    ),
    ToolSpec(
        name="keeperhub_get_execution_status",
        description=(
            "Return the current status (pending/running/success/error/cancelled) "
            "of an execution by id, including per-node progress."
        ),
        parameters={
            "type": "object",
            "properties": {"execution_id": {"type": "string"}},
            "required": ["execution_id"],
            "additionalProperties": False,
        },
        dispatch_key="get_execution_status",
    ),
    ToolSpec(
        name="keeperhub_get_execution_logs",
        description=(
            "Return per-node execution logs (input, output, duration, tx hashes) "
            "for an execution. Use this to give the user an audit trail."
        ),
        parameters={
            "type": "object",
            "properties": {"execution_id": {"type": "string"}},
            "required": ["execution_id"],
            "additionalProperties": False,
        },
        dispatch_key="get_execution_logs",
    ),
    ToolSpec(
        name="keeperhub_check_balance",
        description=(
            "Read the native token balance of an address on a given EVM chain. "
            "No wallet integration is required."
        ),
        parameters={
            "type": "object",
            "properties": {
                "network": {"type": "string", "description": _NETWORK_DESC},
                "address": {"type": "string", "description": "0x-prefixed address."},
            },
            "required": ["network", "address"],
            "additionalProperties": False,
        },
        dispatch_key="check_balance",
    ),
    ToolSpec(
        name="keeperhub_transfer_funds",
        description=(
            "Send native token (ETH/MATIC/etc.) reliably. KeeperHub adds retry "
            "logic, gas escalation, simulation-before-submit, and MEV-aware "
            "private routing. Requires a wallet integration ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "network": {"type": "string", "description": _NETWORK_DESC},
                "to_address": {"type": "string", "description": "0x recipient address."},
                "amount": {
                    "type": "string",
                    "description": "Amount in ETH-units as a string (e.g. '0.1').",
                },
                "wallet_id": {
                    "type": "string",
                    "description": "KeeperHub wallet integration id "
                                   "(see `keeperhub_get_wallet_integration`).",
                },
            },
            "required": ["network", "to_address", "amount", "wallet_id"],
            "additionalProperties": False,
        },
        dispatch_key="transfer_funds",
    ),
    ToolSpec(
        name="keeperhub_write_contract",
        description=(
            "Call a state-changing contract function via KeeperHub's reliable "
            "execution path."
        ),
        parameters={
            "type": "object",
            "properties": {
                "network": {"type": "string", "description": _NETWORK_DESC},
                "contract_address": {"type": "string"},
                "function_name": {"type": "string"},
                "wallet_id": {"type": "string"},
                "args": {"type": "array", "items": {}},
                "value": {"type": "string", "description": "Optional native value to send."},
            },
            "required": ["network", "contract_address", "function_name", "wallet_id"],
            "additionalProperties": False,
        },
        dispatch_key="write_contract",
    ),
    ToolSpec(
        name="keeperhub_list_action_schemas",
        description=(
            "List the action types available on KeeperHub. Filter by category: "
            "web3, discord, sendgrid, webhook, system."
        ),
        parameters={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["web3", "discord", "sendgrid", "webhook", "system"],
                },
            },
            "additionalProperties": False,
        },
        dispatch_key="list_action_schemas",
    ),
    ToolSpec(
        name="keeperhub_ai_generate_workflow",
        description=(
            "Ask KeeperHub's built-in workflow generator to produce a workflow "
            "from a natural-language description. Useful for skipping manual "
            "node-by-node construction."
        ),
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "modify_workflow_id": {
                    "type": "string",
                    "description": "Optional id of an existing workflow to modify.",
                },
            },
            "required": ["description"],
            "additionalProperties": False,
        },
        dispatch_key="ai_generate_workflow",
    ),
    ToolSpec(
        name="keeperhub_get_wallet_integration",
        description=(
            "Return the active wallet integration metadata, including the "
            "wallet_id needed by transfer/write actions."
        ),
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
        dispatch_key="get_wallet_integration",
    ),
)


def find_spec(name: str) -> ToolSpec:
    for spec in KEEPERHUB_TOOL_SPECS:
        if spec.name == name:
            return spec
    raise KeyError(f"Unknown KeeperHub tool: {name}")
