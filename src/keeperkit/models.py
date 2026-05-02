"""Pydantic models that mirror KeeperHub's REST/MCP payload shapes.

These models are intentionally permissive — the upstream API still evolves,
so unknown fields are preserved via ``model_config["extra"] = "allow"`` and
optional fields default to ``None``. The goal is to give you typed access to
the common cases without breaking when KeeperHub adds a new field.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Network(str, Enum):
    """Common EVM chain IDs accepted by KeeperHub web3 actions."""

    ETHEREUM = "1"
    SEPOLIA = "11155111"
    BASE = "8453"
    BASE_SEPOLIA = "84532"
    ARBITRUM = "42161"
    POLYGON = "137"
    OPTIMISM = "10"
    UNICHAIN = "130"


class TriggerType(str, Enum):
    """Workflow trigger types supported by KeeperHub."""

    MANUAL = "Manual"
    SCHEDULE = "Schedule"
    WEBHOOK = "Webhook"
    EVENT = "Event"
    BLOCK = "Block"


class NodeStatus(str, Enum):
    """Per-node execution status."""

    IDLE = "idle"
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"


class ExecutionStatus(str, Enum):
    """Top-level execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    COMPLETED = "completed"  # alias used in some MCP responses
    FAILED = "failed"


class _AllowExtra(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class NodeData(_AllowExtra):
    """The ``data`` blob attached to every workflow node."""

    label: str
    description: str | None = None
    type: Literal["trigger", "action", "condition", "for-each"] = "action"
    config: dict[str, Any] = Field(default_factory=dict)
    status: NodeStatus = NodeStatus.IDLE


class Node(_AllowExtra):
    """A single workflow node (trigger / action / condition / for-each)."""

    id: str
    type: Literal["trigger", "action", "condition", "for-each"]
    data: NodeData
    position: dict[str, float] | None = None  # auto-laid-out by API if omitted


class Edge(_AllowExtra):
    """An edge between two workflow nodes."""

    id: str
    source: str
    target: str
    sourceHandle: str | None = None  # required for condition / for-each


class Workflow(_AllowExtra):
    """A KeeperHub workflow definition."""

    id: str | None = None
    name: str
    description: str | None = None
    enabled: bool = True
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)


class ExecutionLogEntry(_AllowExtra):
    """One log entry inside an execution's logs array."""

    nodeId: str
    nodeName: str | None = None
    nodeType: str | None = None
    status: NodeStatus
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    duration: int | None = None
    createdAt: str | None = None
    error: str | None = None


class WorkflowExecution(_AllowExtra):
    """An execution record returned by ``execute_workflow`` / status endpoints."""

    id: str
    workflowId: str | None = None
    status: ExecutionStatus
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    nodeStatuses: list[dict[str, Any]] | None = None
    progress: dict[str, Any] | None = None
    createdAt: str | None = None
    completedAt: str | None = None


class WalletIntegration(_AllowExtra):
    """The wallet integration metadata required for write actions."""

    id: str
    name: str | None = None
    network: str | None = None
    address: str | None = None
