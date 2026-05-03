"""Sync + async HTTP clients for the KeeperHub public REST API.

The KeeperHub public API exposes **callable workflows** rather than CRUD
primitives. Discovery happens via :meth:`KeeperHubClient.list_workflows`
(``GET /api/mcp/workflows``) and execution via
:meth:`KeeperHubClient.call_workflow` (``POST /api/mcp/workflows/{slug}/call``).
The full per-workflow JSON Schema is published at
:meth:`KeeperHubClient.get_openapi` (``GET /api/openapi``).

Auth is via ``Authorization: Bearer kh_...`` (an *organization* API key).
The ``kh_…`` token authenticates *who* is calling but it does **not** pay
for paid workflows. Paid workflows respond with HTTP 402 and an x402
``payment-required`` header; surface that back to the caller as a
:class:`KeeperHubPaymentRequired` exception so an x402 client (agentcash,
openclaw, the upstream caller, etc.) can do the actual settlement and
replay.

Org-scoped helpers (``list_org_workflows``, ``list_integrations``) are kept
so a builder-side agent can enumerate the workflows and wallet integrations
it owns.
"""

from __future__ import annotations

import os
import time
from base64 import b64decode
from typing import Any

import anyio
import httpx

from keeperkit.exceptions import (
    KeeperHubAPIError,
    KeeperHubAuthError,
    KeeperHubNotFoundError,
    KeeperHubPaymentRequired,
    KeeperHubValidationError,
)

DEFAULT_BASE_URL = "https://app.keeperhub.com/api"
DEFAULT_TIMEOUT = 30.0
DEFAULT_USER_AGENT = "keeperkit/0.1.0 (+https://github.com/danilaverbena/keeperkit)"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _decode_x402_header(value: str | None) -> dict[str, Any] | None:
    """Decode the base64 JSON blob in the ``payment-required`` /
    ``x-payment-requirements`` headers KeeperHub returns on 402."""
    if not value:
        return None
    try:
        # Add padding if missing.
        pad = "=" * (-len(value) % 4)
        raw = b64decode(value + pad)
        import json
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001 - non-fatal, headers are optional
        return None


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.is_success:
        return

    if resp.status_code == 402:
        # Paid workflow — surface as a payment-required exception so callers
        # can route through their x402 client.
        x402 = (_decode_x402_header(resp.headers.get("x-payment-requirements"))
                or _decode_x402_header(resp.headers.get("payment-required")))
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        raise KeeperHubPaymentRequired(
            "KeeperHub workflow requires payment (HTTP 402).",
            x402=x402,
            payload=body,
            www_authenticate=resp.headers.get("www-authenticate"),
        )

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
    def _request(
        self, method: str, path: str, *, json: Any = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        last_exc: Exception | None = None
        delay = self.backoff_initial
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.request(method, path, json=json, params=params,
                                          headers=extra_headers)
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

    # --------------------------------------------------------- discovery (public)
    def list_workflows(self) -> dict[str, Any]:
        """List discoverable workflows (public catalogue).

        ``GET /api/mcp/workflows`` — returns ``{"items": [...]}`` where each
        item has ``listedSlug``, ``inputSchema``, ``priceUsdcPerCall``,
        ``workflowType`` (``"read"`` or ``"write"``), ``category``, ``chain``.
        """
        data = self._request("GET", "/mcp/workflows")
        if isinstance(data, list):
            return {"items": data}
        return data or {"items": []}

    def get_openapi(self) -> dict[str, Any]:
        """Fetch KeeperHub's OpenAPI document (``GET /api/openapi``).

        The document includes per-workflow JSON Schemas under
        ``paths['/api/mcp/workflows/{slug}/call']``, x-payment-info, and
        worked examples in ``info.x-guidance``.
        """
        return self._request("GET", "/openapi") or {}

    # --------------------------------------------------------- execution (public)
    def call_workflow(
        self,
        slug: str,
        body: dict[str, Any] | None = None,
        *,
        x_payment: str | None = None,
    ) -> dict[str, Any]:
        """Invoke a KeeperHub workflow.

        ``POST /api/mcp/workflows/{slug}/call``. ``body`` must satisfy the
        workflow's ``inputSchema`` (see :meth:`list_workflows`). For paid
        workflows, pass an x402 payment token in ``x_payment`` (the value that
        goes into the ``X-Payment`` header per x402 v2). Without it, the
        server returns HTTP 402 and this method raises
        :class:`KeeperHubPaymentRequired` carrying the decoded payment
        descriptor for downstream settlement.

        Returns the parsed JSON response, typically
        ``{"executionId": ..., "status": ..., "output": {...}}``.
        """
        extra: dict[str, str] | None = None
        if x_payment:
            extra = {"X-Payment": x_payment}
        return self._request("POST", f"/mcp/workflows/{slug}/call",
                             json=body or {}, extra_headers=extra) or {}

    # ----------------------------------------------------- builder-side helpers
    def list_org_workflows(self) -> list[dict[str, Any]]:
        """List the *organization's* workflows (builder view).

        ``GET /api/workflows`` returns workflows owned by the org tied to the
        ``kh_…`` key — useful for an agent that operates on its own
        workflows. Public/discoverable workflows belonging to *other* orgs
        only appear via :meth:`list_workflows`.
        """
        data = self._request("GET", "/workflows") or []
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        return data or []

    def list_integrations(self) -> list[dict[str, Any]]:
        """List wallet / external integrations configured on the org.

        ``GET /api/integrations``. Each entry typically contains a chain id,
        a connector name, and an opaque integration id usable in workflow
        bodies. Returns ``[]`` for orgs that have no integrations yet.
        """
        data = self._request("GET", "/integrations") or []
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        return data or []

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

    async def _request(
        self, method: str, path: str, *, json: Any = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        last_exc: Exception | None = None
        delay = self.backoff_initial
        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._http.request(method, path, json=json, params=params,
                                                headers=extra_headers)
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

    async def list_workflows(self) -> dict[str, Any]:
        data = await self._request("GET", "/mcp/workflows")
        if isinstance(data, list):
            return {"items": data}
        return data or {"items": []}

    async def get_openapi(self) -> dict[str, Any]:
        return await self._request("GET", "/openapi") or {}

    async def call_workflow(
        self,
        slug: str,
        body: dict[str, Any] | None = None,
        *,
        x_payment: str | None = None,
    ) -> dict[str, Any]:
        extra: dict[str, str] | None = None
        if x_payment:
            extra = {"X-Payment": x_payment}
        return await self._request("POST", f"/mcp/workflows/{slug}/call",
                                   json=body or {}, extra_headers=extra) or {}

    async def list_org_workflows(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/workflows") or []
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        return data or []

    async def list_integrations(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/integrations") or []
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        return data or []

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncKeeperHubClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
