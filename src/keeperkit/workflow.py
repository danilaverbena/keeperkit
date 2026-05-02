"""Tiny workflow builder DSL.

KeeperHub's REST API takes nodes + edges directly, but writing those by hand
is verbose and error-prone. ``WorkflowBuilder`` lets you compose a workflow
with a couple of method calls:

    wf = (
        WorkflowBuilder("Daily DCA")
        .manual_trigger()
        .action("check", "web3/check-balance",
                network=Network.SEPOLIA, address="0x...")
        .build()
    )

Then either ``client.create_workflow(wf)`` to persist it or
``client.execute_action(...)`` for one-shots.
"""

from __future__ import annotations

import uuid
from typing import Any

from keeperkit.models import Edge, Network, Node, NodeData, NodeStatus, TriggerType, Workflow


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


class WorkflowBuilder:
    """Fluent builder for :class:`Workflow`."""

    def __init__(self, name: str, description: str | None = None) -> None:
        self.name = name
        self.description = description
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self._last_id: str | None = None
        self._enabled = True

    def disabled(self) -> WorkflowBuilder:
        self._enabled = False
        return self

    # --------------------------------------------------------------------- triggers
    def manual_trigger(self, label: str = "Manual") -> WorkflowBuilder:
        node = Node(
            id=_gen_id("trigger"),
            type="trigger",
            data=NodeData(
                label=label,
                type="trigger",
                config={"triggerType": TriggerType.MANUAL.value},
            ),
        )
        self.nodes.append(node)
        self._last_id = node.id
        return self

    def schedule_trigger(self, cron: str, label: str = "Schedule") -> WorkflowBuilder:
        node = Node(
            id=_gen_id("trigger"),
            type="trigger",
            data=NodeData(
                label=label,
                type="trigger",
                config={"triggerType": TriggerType.SCHEDULE.value, "cron": cron},
            ),
        )
        self.nodes.append(node)
        self._last_id = node.id
        return self

    def webhook_trigger(self, label: str = "Webhook") -> WorkflowBuilder:
        node = Node(
            id=_gen_id("trigger"),
            type="trigger",
            data=NodeData(
                label=label,
                type="trigger",
                config={"triggerType": TriggerType.WEBHOOK.value},
            ),
        )
        self.nodes.append(node)
        self._last_id = node.id
        return self

    # ----------------------------------------------------------------------- nodes
    def action(self, label: str, action_type: str,
               *, network: Network | str | None = None,
               after: str | None = None,
               **config: Any) -> WorkflowBuilder:
        cfg: dict[str, Any] = {"actionType": action_type, **config}
        if network is not None:
            cfg["network"] = network.value if isinstance(network, Network) else network
        node = Node(
            id=_gen_id("action"),
            type="action",
            data=NodeData(label=label, type="action", config=cfg, status=NodeStatus.IDLE),
        )
        self.nodes.append(node)
        prev = after or self._last_id
        if prev is not None:
            self.edges.append(Edge(id=_gen_id("edge"), source=prev, target=node.id))
        self._last_id = node.id
        return self

    def condition(self, label: str, expression: str, *,
                  after: str | None = None) -> WorkflowBuilder:
        node = Node(
            id=_gen_id("cond"),
            type="condition",
            data=NodeData(
                label=label, type="condition",
                config={"expression": expression},
            ),
        )
        self.nodes.append(node)
        prev = after or self._last_id
        if prev is not None:
            self.edges.append(Edge(id=_gen_id("edge"), source=prev, target=node.id))
        self._last_id = node.id
        return self

    def edge(self, source: str, target: str,
             *, source_handle: str | None = None) -> WorkflowBuilder:
        self.edges.append(Edge(
            id=_gen_id("edge"),
            source=source, target=target, sourceHandle=source_handle,
        ))
        return self

    # ----------------------------------------------------------------------- build
    def build(self) -> Workflow:
        return Workflow(
            name=self.name,
            description=self.description,
            enabled=self._enabled,
            nodes=list(self.nodes),
            edges=list(self.edges),
        )
