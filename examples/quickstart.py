"""LLM-free smoke test: discover the catalogue, call a free + paid workflow.

Useful for hackathon judges who want to verify the SDK works end-to-end
without setting up any credentials. Runs entirely against the in-memory
``MockKeeperHubClient`` so no network access is needed.
"""

from __future__ import annotations

from keeperkit import MockKeeperHubClient
from keeperkit.exceptions import KeeperHubPaymentRequired


def main() -> None:
    client = MockKeeperHubClient()

    catalogue = client.list_workflows()
    print(f"discovered {len(catalogue['items'])} workflows in mock catalogue:")
    for wf in catalogue["items"]:
        price = wf.get("priceUsdcPerCall") or "free"
        print(f"  · {wf['listedSlug']:<40s}  type={wf['workflowType']:<5s} price={price}")

    print("\n--- calling free helloworld ---")
    out = client.call_workflow("helloworld", {})
    print("status:", out["status"])
    print("output:", out["output"]["result"])

    print("\n--- calling paid aave-v3-health-check WITHOUT x402 token ---")
    try:
        client.call_workflow(
            "aave-v3-health-check",
            {"address": "0x000000000000000000000000000000000000dEaD"},
        )
    except KeeperHubPaymentRequired as exc:
        print("got 402 as expected.")
        print("  amount:    ", exc.amount_usdc, "atomic USDC")
        print("  network:   ", exc.x402["accepts"][0]["network"])
        print("  payTo:     ", exc.x402["accepts"][0]["payTo"])

    print("\n--- replaying with mock x402 settlement token ---")
    out = client.call_workflow(
        "aave-v3-health-check",
        {"address": "0x000000000000000000000000000000000000dEaD"},
        x_payment="mock-token",
    )
    print("status:", out["status"])
    print("result:", out["output"]["result"])


if __name__ == "__main__":
    main()
