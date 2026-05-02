"""Sync + async HTTP clients for the KeeperHub REST API.

The client is intentionally thin — it does request shaping, auth, retries,
error mapping, and Pydantic deserialization, then exposes one method per
KeeperHub action. Higher-level UX (LangChain Tools, CrewAI Tools, workflow
DSL) is built on top of this.

Notes:
* Auth is via ``Authorization: Bearer kh_...`` (an *organization* API key).
* Base URL defaults to ``https://app.keeperhub.com/api`` and is overridable.
* Network/transient failures are retried with exponential backoff so an agent
  can survive transient gas spikes / RPC failovers without writing its own
  retry logic. KeeperHub itself also retries onchain — this is the *outer*
  layer protecting the API call to KeeperHub.
"""

from __future__ import annotations

import os
import time
from typing import Any

import anyio
import httpx
from pydantic import BaseModel, TypeAdapter

from keeperkit.exceptions import (
    KeeperHubAPIError,
    KeeperHubAuthError,
    KeeperHubNotFoundError,
    KeeperHubValidationError,
)
from keeperkit.models import (
    ExecutionLogEntry,
    WalletIntegration,
    Workflow,
    WorkflowExecution,
)

DEFAULT_BASE_URL = "https://app.keeperhub.com/api"
DEFAULT_TIMEOUT = 30.0
DEFAULT_USER_AGENT = "keeperkit/0.1.0 (+https://github.com/danilaverbena/keeperkit)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    payload: Any
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001 - keep raw body if not JSON
        payload = resp.text
    message = (
        payload.get("error") or payload.get("message")
        if isinstance(payload, dict)
        else str(payload)
    ) or f"HTTP {resp.status_code}"

    if resp.status_code in (401, 403):
        raise KeeperHubAuthError(message, status_code=resp.status_code, payload=payload)
    if resp.status_code == 404:
        raise KeeperHubNotFoundError(message, status_code=resp.status_code, payload=payload)
    if resp.status_code == 400:
        raise KeeperHubValidationError(message, status_code=resp.status_code, payload=payload)
    raise KeeperHubAPIError(message, status_code=resp.status_code, payload=payload)


def _coerce(model: type[BaseModel], data: Any) -> Any:
    """Turn a JSON dict / list into a Pydantic model (or list of models)."""
    if isinstance(data, dict) and "data" in data and len(data) <= 2:
        # Common envelope shape: ``{"data": [...]}``
        data = data["data"]
    if isinstance(data, list):
        return TypeAdapter(list[model]).validate_python(data)
    return model.model_validate(data)


class _BaseClient:
    """Shared config / retry policy for sync + async clients."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = 3,
        backoff_initial: float = 0.5,
    ) -> None:
        self.api_key = api_key or os.environ.get("KEEPERHUB_API_KEY")
        self.base_url = (base_url or os.environ.get("KEEPERHUB_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_initial = backoff_initial
        if not self.api_key:
            raise KeeperHubAuthError(
                "KEEPERHUB_API_KEY is not set. Either pass api_key= or set the env var. "
                "If you want to develop without an API key, use MockKeeperHubClient."
            )

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json",
        }


class KeeperHubClient(_BaseClient):
    """Synchronous KeeperHub REST client."""

    def __init__(self, api_key: str | None = None, **kw: Any) -> None:
        super().__init__(api_key, **kw)
        self._http = httpx.Client(base_url=self.base_url, headers=self.headers,
                                  timeout=self.timeout)

    # ------------------------------------------------------------------ helpers
    def _request(self, method: str, path: str, *, json: Any = None,
                 params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        delay = self.backoff_initial
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.request(method, path, json=json, params=params)
                if resp.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                _raise_for_status(resp)
                if resp.status_code == 204 or not resp.content:
                    return None
                return resp.json()
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise KeeperHubAPIError(f"Network error talking to KeeperHub: {exc}") from exc
        if last_exc:
            raise KeeperHubAPIError(str(last_exc)) from last_exc
        raise KeeperHubAPIError("Unknown error talking to KeeperHub")

    # -------------------------------------------------------------- constructors
    @classmethod
    def from_env(cls, **kw: Any) -> KeeperHubClient:
        """Build a client from environment variables."""
        return cls(**kw)

    # ----------------------------------------------------------------- workflows
    def list_workflows(self, *, limit: int = 50, offset: int = 0) -> list[Workflow]:
        data = self._request("GET", "/workflows", params={"limit": limit, "offset": offset})
        return _coerce(Workflow, data)

    def get_workflow(self, workflow_id: str) -> Workflow:
        data = self._request("GET", f"/workflows/{workflow_id}")
        return _coerce(Workflow, data)

    def create_workflow(self, workflow: Workflow | dict[str, Any]) -> Workflow:
        if isinstance(workflow, Workflow):
            body: Any = workflow.model_dump(by_alias=True, exclude_none=True)
        else:
            body = workflow
        data = self._request("POST", "/workflows", json=body)
        return _coerce(Workflow, data)

    def update_workflow(self, workflow_id: str, patch: dict[str, Any]) -> Workflow:
        data = self._request("PATCH", f"/workflows/{workflow_id}", json=patch)
        return _coerce(Workflow, data)

    def delete_workflow(self, workflow_id: str, *, force: bool = False) -> None:
        self._request("DELETE", f"/workflows/{workflow_id}",
                      params={"force": "true"} if force else None)

    # ----------------------------------------------------------------- execution
    def execute_workflow(self, workflow_id: str,
                         inputs: dict[str, Any] | None = None) -> WorkflowExecution:
        data = self._request("POST", f"/workflows/{workflow_id}/execute",
                             json={"input": inputs or {}})
        return _coerce(WorkflowExecution, data)

    def get_execution_status(self, execution_id: str) -> WorkflowExecution:
        data = self._request("GET", f"/workflows/executions/{execution_id}/status")
        return _coerce(WorkflowExecution, data)

    def get_execution_logs(self, execution_id: str) -> list[ExecutionLogEntry]:
        data = self._request("GET", f"/workflows/executions/{execution_id}/logs")
        return _coerce(ExecutionLogEntry, data)

    def list_executions(self, workflow_id: str) -> list[WorkflowExecution]:
        data = self._request("GET", f"/workflows/{workflow_id}/executions")
        return _coerce(WorkflowExecution, data)

    def wait_for_execution(self, execution_id: str, *, timeout: float = 120.0,
                           poll_interval: float = 2.0) -> WorkflowExecution:
        """Poll an execution until it reaches a terminal state, then return it.

        Terminal states: ``success``, ``error``, ``failed``, ``cancelled``,
        ``completed``. Raises :class:`KeeperHubAPIError` on timeout.
        """
        deadline = time.monotonic() + timeout
        while True:
            execution = self.get_execution_status(execution_id)
            if execution.status.value in ("success", "error", "failed",
                                          "cancelled", "completed"):
                return execution
            if time.monotonic() > deadline:
                raise KeeperHubAPIError(
                    f"Timed out waiting for execution {execution_id}; last status="
                    f"{execution.status.value}"
                )
            time.sleep(poll_interval)

    # ---------------------------------------------------------------- one-shots
    def execute_action(self, action_type: str, config: dict[str, Any], *,
                       network: str | None = None) -> WorkflowExecution:
        """Convenience: build a single-action workflow, run it, return execution.

        Internally this calls KeeperHub's ``/api/execute`` endpoint, which lets
        you fire a single web3 action without first creating a stored workflow.
        """
        body = {"actionType": action_type, "config": dict(config)}
        if network is not None:
            body["config"].setdefault("network", network)
        data = self._request("POST", "/execute", json=body)
        return _coerce(WorkflowExecution, data)

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
        config: dict[str, Any] = {
            "network": network,
            "contractAddress": contract_address,
            "functionName": function_name,
            "walletId": wallet_id,
        }
        if args is not None:
            config["args"] = args
        if value is not None:
            config["value"] = value
        return self.execute_action("web3/write-contract", config)

    # --------------------------------------------------------------- integrations
    def list_integrations(self, *, type: str | None = None) -> list[dict[str, Any]]:
        data = self._request("GET", "/integrations",
                             params={"type": type} if type else None)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        return data or []

    def get_wallet_integration(self) -> WalletIntegration | None:
        wallets = self.list_integrations(type="web3")
        if not wallets:
            return None
        return WalletIntegration.model_validate(wallets[0])

    def list_action_schemas(self, *, category: str | None = None) -> list[dict[str, Any]]:
        data = self._request("GET", "/action-schemas",
                             params={"category": category} if category else None)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        return data or []

    # -------------------------------------------------------------- ai-generated
    def ai_generate_workflow(self, description: str, *,
                             modify_workflow_id: str | None = None) -> Workflow:
        body: dict[str, Any] = {"prompt": description}
        if modify_workflow_id:
            body["workflowId"] = modify_workflow_id
        data = self._request("POST", "/workflows/ai-generate", json=body)
        return _coerce(Workflow, data)

    # -------------------------------------------------------------- housekeeping
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> KeeperHubClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AsyncKeeperHubClient(_BaseClient):
    """Async variant of :class:`KeeperHubClient`."""

    def __init__(self, api_key: str | None = None, **kw: Any) -> None:
        super().__init__(api_key, **kw)
        self._http = httpx.AsyncClient(base_url=self.base_url, headers=self.headers,
                                       timeout=self.timeout)

    async def _request(self, method: str, path: str, *, json: Any = None,
                       params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        delay = self.backoff_initial
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._http.request(method, path, json=json, params=params)
                if resp.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                    await anyio.sleep(delay)
                    delay *= 2
                    continue
                _raise_for_status(resp)
                if resp.status_code == 204 or not resp.content:
                    return None
                return resp.json()
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    await anyio.sleep(delay)
                    delay *= 2
                    continue
                raise KeeperHubAPIError(f"Network error talking to KeeperHub: {exc}") from exc
        if last_exc:
            raise KeeperHubAPIError(str(last_exc)) from last_exc
        raise KeeperHubAPIError("Unknown error talking to KeeperHub")

    @classmethod
    def from_env(cls, **kw: Any) -> AsyncKeeperHubClient:
        return cls(**kw)

    async def list_workflows(self, *, limit: int = 50, offset: int = 0) -> list[Workflow]:
        data = await self._request("GET", "/workflows",
                                   params={"limit": limit, "offset": offset})
        return _coerce(Workflow, data)

    async def get_workflow(self, workflow_id: str) -> Workflow:
        data = await self._request("GET", f"/workflows/{workflow_id}")
        return _coerce(Workflow, data)

    async def execute_workflow(self, workflow_id: str,
                               inputs: dict[str, Any] | None = None) -> WorkflowExecution:
        data = await self._request("POST", f"/workflows/{workflow_id}/execute",
                                   json={"input": inputs or {}})
        return _coerce(WorkflowExecution, data)

    async def get_execution_status(self, execution_id: str) -> WorkflowExecution:
        data = await self._request("GET", f"/workflows/executions/{execution_id}/status")
        return _coerce(WorkflowExecution, data)

    async def get_execution_logs(self, execution_id: str) -> list[ExecutionLogEntry]:
        data = await self._request("GET", f"/workflows/executions/{execution_id}/logs")
        return _coerce(ExecutionLogEntry, data)

    async def wait_for_execution(self, execution_id: str, *, timeout: float = 120.0,
                                 poll_interval: float = 2.0) -> WorkflowExecution:
        deadline = anyio.current_time() + timeout
        while True:
            execution = await self.get_execution_status(execution_id)
            if execution.status.value in ("success", "error", "failed",
                                          "cancelled", "completed"):
                return execution
            if anyio.current_time() > deadline:
                raise KeeperHubAPIError(
                    f"Timed out waiting for execution {execution_id}; last status="
                    f"{execution.status.value}"
                )
            await anyio.sleep(poll_interval)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncKeeperHubClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
