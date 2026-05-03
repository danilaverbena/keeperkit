"""In-memory ``MockKeeperHubClient`` mirroring the real public API.

The mock matches the surface of :class:`keeperkit.client.KeeperHubClient`
exactly — same method names, same return shapes — so the rest of the
codebase (tools, server, examples) doesn't care which one it talks to.

The mock ships with a small **representative** catalogue derived from the
real ``GET /api/mcp/workflows`` response (free + paid samples across the
three workflow archetypes KeeperHub publishes today: read DeFi data, write
onchain transactions, and a hello-world). It's enough to demo the full
plugin surface — including 402 / x402 — without any external network
calls.

Tip: pass ``catalogue=`` to override the built-in fixture (e.g. to load a
saved real-API snapshot from ``tests/fixtures/keeperhub_catalogue.json``).
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from keeperkit.exceptions import (
    KeeperHubNotFoundError,
    KeeperHubPaymentRequired,
)

# Representative subset of the real catalogue. Slugs, schemas, prices and
# workflowType match what KeeperHub returns in production today (May 2026).
DEFAULT_CATALOGUE: list[dict[str, Any]] = [
    {
        "id": "mock_helloworld",
        "name": "HelloWorld",
        "description": "Simple workflow that returns a Hello, World! message.",
        "listedSlug": "helloworld",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "priceUsdcPerCall": None,
        "workflowType": "read",
        "category": "demo",
        "chain": None,
        "isListed": True,
    },
    {
        "id": "mock_defi_position_aggregator_base",
        "name": "DeFi Position Aggregator: Wallet on Base",
        "description": (
            "Aggregates a wallet's DeFi positions across the major lending and "
            "yield venues KeeperHub supports on Base in a single call — Aave V3 "
            "(with health factor), Compound V3 USDC, Morpho Steakhouse USDC."
        ),
        "listedSlug": "defi-position-aggregator-base",
        "inputSchema": {
            "type": "object",
            "required": ["wallet"],
            "properties": {
                "wallet": {
                    "type": "string",
                    "description": "Wallet address (0x…) on Base.",
                }
            },
            "additionalProperties": False,
        },
        "priceUsdcPerCall": None,
        "workflowType": "read",
        "category": "defi",
        "chain": "8453",
        "isListed": True,
    },
    {
        "id": "mock_aave_v3_health_check",
        "name": "Aave v3 Health Check",
        "description": (
            "Reads the Aave v3 health factor, total collateral, total debt, and "
            "risk classification for a given wallet."
        ),
        "listedSlug": "aave-v3-health-check",
        "inputSchema": {
            "type": "object",
            "required": ["address"],
            "properties": {
                "address": {"type": "string", "description": "EVM wallet address."}
            },
            "additionalProperties": False,
        },
        "priceUsdcPerCall": "0.01",
        "workflowType": "read",
        "category": "defi",
        "chain": "1",
        "isListed": True,
    },
    {
        "id": "mock_microtip",
        "name": "Microtip",
        "description": (
            "Send a small USDC tip from your KeeperHub wallet to any EVM address "
            "with idempotency built in."
        ),
        "listedSlug": "microtip",
        "inputSchema": {
            "type": "object",
            "required": ["recipient", "amount"],
            "properties": {
                "recipient": {"type": "string"},
                "amount": {"type": "string", "description": "USDC amount, decimal string."},
                "chain": {"type": "string", "default": "8453"},
            },
            "additionalProperties": False,
        },
        "priceUsdcPerCall": "0.01",
        "workflowType": "write",
        "category": "payments",
        "chain": "8453",
        "isListed": True,
    },
    {
        "id": "mock_sepolia_balance_check",
        "name": "Sepolia Balance Check",
        "description": "Read the native ETH balance of an address on Sepolia.",
        "listedSlug": "sepolia-balance-check",
        "inputSchema": {
            "type": "object",
            "required": ["address"],
            "properties": {
                "address": {"type": "string", "description": "0x… EVM address."}
            },
            "additionalProperties": False,
        },
        "priceUsdcPerCall": None,
        "workflowType": "read",
        "category": "defi",
        "chain": "11155111",
        "isListed": True,
    },
]


def _exec_id() -> str:
    return f"exec_{secrets.token_hex(6)}"


def _x402_descriptor(slug: str, price_usdc: str) -> dict[str, Any]:
    """Build the structured x402 descriptor we'd return on 402."""
    return {
        "x402Version": 2,
        "error": "Payment required",
        "resource": {
            "url": f"https://app.keeperhub.com/api/mcp/workflows/{slug}/call",
            "description": f"Pay to run workflow: {slug}",
            "mimeType": "application/json",
        },
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
                "amount": str(int(float(price_usdc) * 1_000_000)),  # 6-decimal atomic
                "payTo": "0x650a09bc1cda076486716acdd80fce1bba5e84ff",
                "maxTimeoutSeconds": 300,
                "extra": {"name": "USD Coin", "version": "2"},
            }
        ],
    }


class MockKeeperHubClient:
    """In-memory KeeperHub client mirroring the real public API surface."""

    def __init__(
        self,
        *,
        catalogue: list[dict[str, Any]] | None = None,
        accept_x_payment_token: str = "mock-token",
    ) -> None:
        self.base_url = "in-memory"
        self.api_key = "mock"
        self._catalogue = list(catalogue if catalogue is not None else DEFAULT_CATALOGUE)
        self._accept_token = accept_x_payment_token
        self._executions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------- discovery
    def list_workflows(self) -> dict[str, Any]:
        return {"items": list(self._catalogue)}

    def get_openapi(self) -> dict[str, Any]:
        return {
            "openapi": "3.1.0",
            "info": {
                "title": "KeeperHub (mock)",
                "version": "0.1.0",
                "description": "Mock KeeperHub OpenAPI for offline demos.",
            },
            "paths": {
                f"/api/mcp/workflows/{wf['listedSlug']}/call": {
                    "post": {
                        "operationId": f"call-{wf['listedSlug']}",
                        "summary": wf["name"],
                        "description": wf.get("description", ""),
                        "requestBody": {
                            "content": {"application/json": {"schema": wf["inputSchema"]}}
                        },
                    }
                }
                for wf in self._catalogue
                if wf.get("listedSlug")
            },
        }

    # ------------------------------------------------------------- execution
    def call_workflow(
        self,
        slug: str,
        body: dict[str, Any] | None = None,
        *,
        x_payment: str | None = None,
    ) -> dict[str, Any]:
        wf = next((w for w in self._catalogue if w.get("listedSlug") == slug), None)
        if wf is None:
            raise KeeperHubNotFoundError(
                f"workflow {slug!r} not in mock catalogue", status_code=404
            )

        price = wf.get("priceUsdcPerCall")
        if price and x_payment != self._accept_token:
            raise KeeperHubPaymentRequired(
                f"workflow {slug!r} requires payment ({price} USDC).",
                x402=_x402_descriptor(slug, price),
            )

        execution_id = _exec_id()
        result = _simulate_output(slug, body or {})
        record = {
            "executionId": execution_id,
            "status": "success",
            "output": {"logs": [], "result": result, "success": True},
            "_slug": slug,
            "_calledAt": time.time(),
        }
        self._executions[execution_id] = record
        return {k: v for k, v in record.items() if not k.startswith("_")}

    # ----------------------------------------------------- builder-side helpers
    def list_org_workflows(self) -> list[dict[str, Any]]:
        # In mock land the org "owns" the same listed catalogue.
        return [dict(w) for w in self._catalogue]

    def list_integrations(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "mock_wallet_base",
                "type": "web3",
                "chain": "8453",
                "name": "Mock Base wallet",
                "address": "0x000000000000000000000000000000000000dEaD",
            }
        ]

    # ------------------------------------------------------------- housekeeping
    def close(self) -> None:
        pass

    def __enter__(self) -> MockKeeperHubClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _simulate_output(slug: str, body: dict[str, Any]) -> dict[str, Any]:
    """Return a plausible output payload per workflow type."""
    if slug == "helloworld":
        return {"message": "Hello World!"}

    if slug == "defi-position-aggregator-base":
        return {
            "wallet": body.get("wallet"),
            "totalUsd": "1234.56",
            "positions": [
                {"protocol": "aave-v3", "asset": "USDC", "balance": "1000.00",
                 "apy": "5.41"},
                {"protocol": "morpho", "asset": "USDC", "balance": "234.56",
                 "apy": "4.82"},
            ],
        }

    if slug == "aave-v3-health-check":
        return {
            "address": body.get("address"),
            "healthFactor": "2.13",
            "totalCollateralUSD": "12345.00",
            "totalDebtUSD": "5800.00",
            "riskLevel": "healthy",
        }

    if slug == "microtip":
        return {
            "recipient": body.get("recipient"),
            "amount": body.get("amount"),
            "chain": body.get("chain", "8453"),
            "txHash": f"0x{secrets.token_hex(32)}",
            "transactionLink": (
                "https://basescan.org/tx/"
                f"0x{secrets.token_hex(32)}"
            ),
        }

    if slug == "sepolia-balance-check":
        return {
            "address": body.get("address"),
            "chainId": "11155111",
            "balanceWei": "12345678901234567890",
            "balanceEth": "12.345",
        }

    return {"slug": slug, "input": body, "note": "mock simulated output"}
