"""Verify the REST client handles auth / status errors correctly."""
from __future__ import annotations

import pytest

respx = pytest.importorskip("respx")
import httpx

from keeperkit import KeeperHubClient
from keeperkit.exceptions import (
    KeeperHubAuthError,
    KeeperHubNotFoundError,
    KeeperHubValidationError,
)


def _client(api_key="kh_test", base_url="https://kh-test.example/api"):
    return KeeperHubClient(api_key=api_key, base_url=base_url, max_retries=0)


@respx.mock
def test_401_raises_auth_error():
    respx.get("https://kh-test.example/api/workflows").mock(
        return_value=httpx.Response(401, json={"error": "bad token"})
    )
    with _client() as c:
        with pytest.raises(KeeperHubAuthError):
            c.list_workflows()


@respx.mock
def test_404_raises_not_found():
    respx.get("https://kh-test.example/api/workflows/wf_x").mock(
        return_value=httpx.Response(404, json={"error": "missing"})
    )
    with _client() as c:
        with pytest.raises(KeeperHubNotFoundError):
            c.get_workflow("wf_x")


@respx.mock
def test_400_raises_validation_error():
    respx.post("https://kh-test.example/api/execute").mock(
        return_value=httpx.Response(400, json={"error": "bad config"})
    )
    with _client() as c:
        with pytest.raises(KeeperHubValidationError):
            c.execute_action("web3/check-balance", {})
