"""Verify the real KeeperHubClient maps HTTP statuses to typed exceptions.

These tests use respx to fake the upstream API — no network required.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from keeperkit import KeeperHubClient
from keeperkit.exceptions import (
    KeeperHubAPIError,
    KeeperHubAuthError,
    KeeperHubNotFoundError,
    KeeperHubPaymentRequired,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> KeeperHubClient:
    monkeypatch.setenv("KEEPERHUB_API_KEY", "kh_test")
    return KeeperHubClient.from_env(max_retries=0, backoff_initial=0)


@respx.mock
def test_list_workflows_happy_path(client: KeeperHubClient):
    respx.get("https://app.keeperhub.com/api/mcp/workflows").mock(
        return_value=httpx.Response(200, json={"items": [{"listedSlug": "helloworld"}]})
    )
    cat = client.list_workflows()
    assert cat == {"items": [{"listedSlug": "helloworld"}]}


@respx.mock
def test_call_workflow_success(client: KeeperHubClient):
    respx.post(
        "https://app.keeperhub.com/api/mcp/workflows/helloworld/call"
    ).mock(return_value=httpx.Response(
        200, json={"executionId": "exec_1", "status": "success",
                   "output": {"result": {"message": "Hello World!"}}}
    ))
    res = client.call_workflow("helloworld", {})
    assert res["executionId"] == "exec_1"
    assert res["output"]["result"]["message"] == "Hello World!"


@respx.mock
def test_call_workflow_402_raises_payment_required(client: KeeperHubClient):
    descriptor = {
        "x402Version": 2,
        "error": "Payment required",
        "resource": {"url": "x", "description": "y", "mimeType": "application/json"},
        "accepts": [{
            "scheme": "exact",
            "network": "eip155:8453",
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "amount": "10000",
            "payTo": "0xpayto",
        }],
    }
    encoded = base64.b64encode(json.dumps(descriptor).encode()).decode()
    respx.post(
        "https://app.keeperhub.com/api/mcp/workflows/aave-v3-health-check/call"
    ).mock(return_value=httpx.Response(
        402,
        headers={
            "x-payment-requirements": encoded,
            "www-authenticate": 'Payment id="abc"',
        },
        json=descriptor,
    ))

    with pytest.raises(KeeperHubPaymentRequired) as excinfo:
        client.call_workflow("aave-v3-health-check",
                             {"address": "0x000000000000000000000000000000000000dEaD"})
    err = excinfo.value
    assert err.amount_usdc == "10000"
    assert err.www_authenticate.startswith("Payment ")
    assert err.x402["accepts"][0]["network"] == "eip155:8453"


@respx.mock
def test_401_raises_auth_error(client: KeeperHubClient):
    respx.get("https://app.keeperhub.com/api/mcp/workflows").mock(
        return_value=httpx.Response(401, json={"error": "bad key"})
    )
    with pytest.raises(KeeperHubAuthError) as excinfo:
        client.list_workflows()
    assert "bad key" in str(excinfo.value)


@respx.mock
def test_404_raises_not_found(client: KeeperHubClient):
    respx.post(
        "https://app.keeperhub.com/api/mcp/workflows/missing/call"
    ).mock(return_value=httpx.Response(404, json={"error": "not found"}))
    with pytest.raises(KeeperHubNotFoundError):
        client.call_workflow("missing", {})


@respx.mock
def test_5xx_eventually_raises(client: KeeperHubClient):
    respx.get("https://app.keeperhub.com/api/mcp/workflows").mock(
        return_value=httpx.Response(503, text="bad gateway")
    )
    with pytest.raises(KeeperHubAPIError):
        client.list_workflows()


@respx.mock
def test_call_workflow_forwards_x_payment_header(client: KeeperHubClient):
    route = respx.post(
        "https://app.keeperhub.com/api/mcp/workflows/aave-v3-health-check/call"
    ).mock(return_value=httpx.Response(
        200, json={"executionId": "ok", "status": "success", "output": {}}
    ))
    client.call_workflow(
        "aave-v3-health-check",
        {"address": "0x0"},
        x_payment="x402-token",
    )
    request = route.calls.last.request
    assert request.headers["x-payment"] == "x402-token"
