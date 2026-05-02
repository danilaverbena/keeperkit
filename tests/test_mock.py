"""Tests for the in-memory MockKeeperHubClient and its public-API parity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from keeperkit import MockKeeperHubClient
from keeperkit.exceptions import KeeperHubNotFoundError, KeeperHubPaymentRequired

FIXTURES = Path(__file__).parent / "fixtures"


def test_default_catalogue_is_non_empty():
    client = MockKeeperHubClient()
    cat = client.list_workflows()
    assert cat["items"]
    # Each entry has the fields production /api/mcp/workflows returns.
    for wf in cat["items"]:
        assert {"id", "name", "listedSlug", "inputSchema", "workflowType"} <= set(wf)


def test_real_catalogue_fixture_is_well_formed():
    """Smoke test: the saved real-API snapshot still parses."""
    raw = json.loads((FIXTURES / "keeperhub_catalogue.json").read_text())
    assert "items" in raw
    # Use the real snapshot as a mock catalogue and verify key methods.
    client = MockKeeperHubClient(catalogue=raw["items"])
    cat = client.list_workflows()
    assert len(cat["items"]) == len(raw["items"])


def test_helloworld_is_free_and_returns_executionid():
    client = MockKeeperHubClient()
    res = client.call_workflow("helloworld", {})
    assert res["status"] == "success"
    assert "executionId" in res
    assert res["output"]["result"]["message"] == "Hello World!"


def test_paid_workflow_raises_payment_required_without_token():
    client = MockKeeperHubClient()
    with pytest.raises(KeeperHubPaymentRequired) as excinfo:
        client.call_workflow("aave-v3-health-check",
                             {"address": "0x000000000000000000000000000000000000dEaD"})
    err = excinfo.value
    assert err.x402["x402Version"] == 2
    assert err.x402["accepts"][0]["network"] == "eip155:8453"
    assert err.amount_usdc  # not None


def test_paid_workflow_succeeds_with_token():
    client = MockKeeperHubClient()
    res = client.call_workflow(
        "aave-v3-health-check",
        {"address": "0x000000000000000000000000000000000000dEaD"},
        x_payment="mock-token",
    )
    assert res["status"] == "success"
    assert "healthFactor" in res["output"]["result"]


def test_unknown_slug_raises_not_found():
    client = MockKeeperHubClient()
    with pytest.raises(KeeperHubNotFoundError):
        client.call_workflow("does-not-exist", {})


def test_get_openapi_describes_listed_workflows():
    client = MockKeeperHubClient()
    spec = client.get_openapi()
    paths = spec["paths"]
    assert "/api/mcp/workflows/helloworld/call" in paths
    schema = paths["/api/mcp/workflows/aave-v3-health-check/call"]["post"]
    assert schema["summary"] == "Aave v3 Health Check"


def test_org_endpoints_return_lists():
    client = MockKeeperHubClient()
    assert isinstance(client.list_org_workflows(), list)
    assert isinstance(client.list_integrations(), list)
