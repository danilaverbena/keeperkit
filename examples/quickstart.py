"""LLM-free smoke test: build a workflow, run it through the mock, inspect it.

Useful for hackathon judges who want to verify the SDK works end-to-end
without setting up any credentials.
"""

from __future__ import annotations

from keeperkit import MockKeeperHubClient, Network, WorkflowBuilder


def main() -> None:
    client = MockKeeperHubClient()

    workflow = (
        WorkflowBuilder("Sepolia balance ping",
                        description="Reads my balance whenever triggered.")
        .manual_trigger()
        .action(
            "Check Balance",
            "web3/check-balance",
            network=Network.SEPOLIA,
            address="0x9c8f005ab27adb94f3d49020a15722db2fcd9f27",
        )
        .build()
    )

    saved = client.create_workflow(workflow)
    print("created workflow", saved.id, "with", len(saved.nodes), "nodes")

    execution = client.execute_workflow(saved.id, inputs={"note": "hello"})
    print("execution", execution.id, "->", execution.status.value)

    final = client.wait_for_execution(execution.id)
    print("final output:", final.output)

    logs = client.get_execution_logs(execution.id)
    for log in logs:
        print(f"  · {log.nodeName}: {log.status.value} ({log.duration} ms)")


if __name__ == "__main__":
    main()
