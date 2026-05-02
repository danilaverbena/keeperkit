"""In-memory mock backend that mimics the KeeperHub API.

Why this matters: KeeperHub auth is org-scoped, so getting a real key takes
time at the start of a hackathon and you can't easily share one. The mock
backend lets a builder integrate KeeperKit immediately, write tests against a
deterministic surface, and then flip a single env var to hit the real API.

The mock is *intentionally* not a perfect simulator — it covers the surface
KeeperKit's tools depend on:

* workflow CRUD,
* ``execute_workflow`` (returns a deterministic, completed execution),
* ``execute_action`` (single-shot web3 actions: balance, transfer, write),
* execution status + logs,
* a default mock wallet integration.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from keeperkit.exceptions import KeeperHubNotFoundError
from keeperkit.models import (
    Edge,
    ExecutionLogEntry,
    ExecutionStatus,
    Node,
    NodeStatus,
    WalletIntegration,
    Workflow,
    WorkflowExecution,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class MockKeeperHubClient:
    """Drop-in stand-in for :class:`KeeperHubClient`.

    The mock implements the same method names, so swapping ``KeeperHubClient``
    for ``MockKeeperHubClient()`` in your code is enough to run end-to-end
    against an in-memory backend.
    """

    is_mock = True

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._executions: dict[str, WorkflowExecution] = {}
        self._logs: dict[str, list[ExecutionLogEntry]] = {}
        # one default wallet so transfer/write actions don't need extra setup
        self._wallet = WalletIntegration(
            id="wallet_mock_main",
            name="Mock KeeperHub Wallet",
            network="11155111",
            address="0xMockWallet0000000000000000000000000000000",
        )

    # ----------------------------------------------------------------- workflows
    def list_workflows(self, *, limit: int = 50, offset: int = 0) -> list[Workflow]:
        items = list(self._workflows.values())
        return items[offset : offset + limit]

    def get_workflow(self, workflow_id: str) -> Workflow:
        if workflow_id not in self._workflows:
            raise KeeperHubNotFoundError(f"workflow {workflow_id} not found")
        return self._workflows[workflow_id]

    def create_workflow(self, workflow: Workflow | dict[str, Any]) -> Workflow:
        if isinstance(workflow, dict):
            workflow = Workflow.model_validate(workflow)
        wf = workflow.model_copy(update={"id": workflow.id or _new_id("wf")})
        self._workflows[wf.id] = wf
        return wf

    def update_workflow(self, workflow_id: str, patch: dict[str, Any]) -> Workflow:
        wf = self.get_workflow(workflow_id)
        updated = wf.model_copy(update=patch)
        self._workflows[workflow_id] = updated
        return updated

    def delete_workflow(self, workflow_id: str, *, force: bool = False) -> None:
        if workflow_id not in self._workflows:
            raise KeeperHubNotFoundError(f"workflow {workflow_id} not found")
        del self._workflows[workflow_id]

    # ----------------------------------------------------------------- execution
    def execute_workflow(self, workflow_id: str,
                         inputs: dict[str, Any] | None = None) -> WorkflowExecution:
        wf = self.get_workflow(workflow_id)
        return self._simulate_execution(wf, inputs or {})

    def get_execution_status(self, execution_id: str) -> WorkflowExecution:
        if execution_id not in self._executions:
            raise KeeperHubNotFoundError(f"execution {execution_id} not found")
        return self._executions[execution_id]

    def get_execution_logs(self, execution_id: str) -> list[ExecutionLogEntry]:
        if execution_id not in self._logs:
            raise KeeperHubNotFoundError(f"execution {execution_id} not found")
        return list(self._logs[execution_id])

    def list_executions(self, workflow_id: str) -> list[WorkflowExecution]:
        return [e for e in self._executions.values() if e.workflowId == workflow_id]

    def wait_for_execution(self, execution_id: str, *, timeout: float = 120.0,
                           poll_interval: float = 0.0) -> WorkflowExecution:
        # Mock executions are synchronous, so we can just return the stored one.
        return self.get_execution_status(execution_id)

    # ------------------------------------------------------- single-shot actions
    def execute_action(self, action_type: str, config: dict[str, Any], *,
                       network: str | None = None) -> WorkflowExecution:
        cfg = dict(config)
        if network is not None:
            cfg.setdefault("network", network)
        wf = Workflow(
            name=f"adhoc:{action_type}",
            nodes=[
                Node(
                    id="trigger-1", type="trigger",
                    data={"label": "Manual", "type": "trigger",
                          "config": {"triggerType": "Manual"}},
                ),
                Node(
                    id="action-1", type="action",
                    data={"label": action_type, "type": "action",
                          "config": cfg | {"actionType": action_type}},
                ),
            ],
            edges=[Edge(id="e1", source="trigger-1", target="action-1")],
        )
        return self._simulate_execution(wf, cfg)

    def check_balance(self, network: str, address: str) -> dict[str, Any]:
        execution = self.execute_action(
            "web3/check-balance",
            {"network": network, "address": address},
        )
        return (execution.output or {}) | {"executionId": execution.id}

    def transfer_funds(self, network: str, to_address: str, amount: str,
                       wallet_id: str) -> WorkflowExecution:
        return self.execute_action(
            "web3/transfer-funds",
            {"network": network, "toAddress": to_address,
             "amount": amount, "walletId": wallet_id},
        )

    def write_contract(self, network: str, contract_address: str, function_name: str,
                       wallet_id: str, args: list[Any] | None = None,
                       value: str | None = None) -> WorkflowExecution:
        cfg: dict[str, Any] = {
            "network": network,
            "contractAddress": contract_address,
            "functionName": function_name,
            "walletId": wallet_id,
        }
        if args is not None:
            cfg["args"] = args
        if value is not None:
            cfg["value"] = value
        return self.execute_action("web3/write-contract", cfg)

    # --------------------------------------------------------------- integrations
    def list_integrations(self, *, type: str | None = None) -> list[dict[str, Any]]:
        return [self._wallet.model_dump()]

    def get_wallet_integration(self) -> WalletIntegration:
        return self._wallet

    def list_action_schemas(self, *, category: str | None = None) -> list[dict[str, Any]]:
        # A representative subset of KeeperHub's web3 action schemas, kept
        # compact so the demo agent can list them without overwhelming the LLM.
        all_schemas = [
            {
                "actionType": "web3/check-balance",
                "category": "web3",
                "description": "Read native token balance for an address.",
                "fields": ["network", "address"],
            },
            {
                "actionType": "web3/check-token-balance",
                "category": "web3",
                "description": "Read ERC-20 token balance.",
                "fields": ["network", "address", "tokenAddress"],
            },
            {
                "actionType": "web3/transfer-funds",
                "category": "web3",
                "description": "Send native token (with retry + gas opt + private routing).",
                "fields": ["network", "toAddress", "amount", "walletId"],
            },
            {
                "actionType": "web3/transfer-token",
                "category": "web3",
                "description": "Send ERC-20 token.",
                "fields": ["network", "toAddress", "tokenAddress", "amount", "walletId"],
            },
            {
                "actionType": "web3/write-contract",
                "category": "web3",
                "description": "Call a state-changing contract function.",
                "fields": ["network", "contractAddress", "functionName", "walletId",
                           "args"],
            },
            {
                "actionType": "web3/read-contract",
                "category": "web3",
                "description": "Read from a view/pure contract function.",
                "fields": ["network", "contractAddress", "functionName", "args"],
            },
        ]
        if category:
            return [s for s in all_schemas if s["category"] == category]
        return all_schemas

    def ai_generate_workflow(self, description: str, *,
                             modify_workflow_id: str | None = None) -> Workflow:
        # The mock can't actually call an LLM, but it can produce a sensible
        # single-action workflow so downstream code paths still exercise.
        wf = Workflow(
            name=f"AI: {description[:50]}",
            description=description,
            nodes=[
                Node(
                    id="trigger-1", type="trigger",
                    data={"label": "Manual", "type": "trigger",
                          "config": {"triggerType": "Manual"}},
                ),
                Node(
                    id="action-1", type="action",
                    data={
                        "label": "Check Balance",
                        "type": "action",
                        "config": {
                            "actionType": "web3/check-balance",
                            "network": "11155111",
                            "address": "0x0000000000000000000000000000000000000000",
                        },
                    },
                ),
            ],
            edges=[Edge(id="e1", source="trigger-1", target="action-1")],
        )
        return self.create_workflow(wf)

    # ------------------------------------------------------- internal simulation
    def _simulate_execution(self, wf: Workflow,
                            inputs: dict[str, Any]) -> WorkflowExecution:
        execution_id = _new_id("exec")
        action_logs: list[ExecutionLogEntry] = []
        output: dict[str, Any] = {}
        for node in wf.nodes:
            if node.type != "action":
                continue
            action = node.data.config.get("actionType", "")
            simulated = _simulate_action(action, node.data.config, inputs)
            output = simulated
            action_logs.append(
                ExecutionLogEntry(
                    nodeId=node.id,
                    nodeName=node.data.label,
                    nodeType=node.type,
                    status=NodeStatus.SUCCESS,
                    input=node.data.config,
                    output=simulated,
                    duration=42,
                    createdAt=_now(),
                )
            )
        execution = WorkflowExecution(
            id=execution_id,
            workflowId=wf.id,
            status=ExecutionStatus.SUCCESS,
            input=inputs,
            output=output,
            createdAt=_now(),
            completedAt=_now(),
        )
        self._executions[execution_id] = execution
        self._logs[execution_id] = action_logs
        return execution

    def close(self) -> None:
        pass

    def __enter__(self) -> MockKeeperHubClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _simulate_action(action: str, config: dict[str, Any],
                     inputs: dict[str, Any]) -> dict[str, Any]:
    """Return a plausible action output without touching a real chain."""
    if action == "web3/check-balance":
        return {
            "balance": "0.1234",
            "balanceWei": "123400000000000000",
            "address": config.get("address"),
            "network": config.get("network"),
        }
    if action == "web3/check-token-balance":
        return {
            "balance": "1000.0",
            "tokenAddress": config.get("tokenAddress"),
            "address": config.get("address"),
            "network": config.get("network"),
        }
    if action in ("web3/transfer-funds", "web3/transfer-token"):
        return {
            "txHash": f"0x{uuid.uuid4().hex}{uuid.uuid4().hex}",
            "from": "0xMockWallet0000000000000000000000000000000",
            "to": config.get("toAddress"),
            "amount": config.get("amount"),
            "network": config.get("network"),
            "status": "confirmed",
            "retries": 0,
            "gasUsed": "21000",
            "private": True,
            "transactionLink": "https://sepolia.etherscan.io/tx/0xMOCK",
        }
    if action == "web3/write-contract":
        return {
            "txHash": f"0x{uuid.uuid4().hex}{uuid.uuid4().hex}",
            "contractAddress": config.get("contractAddress"),
            "functionName": config.get("functionName"),
            "args": config.get("args"),
            "network": config.get("network"),
            "status": "confirmed",
        }
    if action == "web3/read-contract":
        return {
            "value": "42",
            "functionName": config.get("functionName"),
            "contractAddress": config.get("contractAddress"),
        }
    return {"action": action, "config": config, "inputs": inputs, "ok": True}
