from keeperkit import MockKeeperHubClient, Network, WorkflowBuilder
from keeperkit.exceptions import KeeperHubNotFoundError


def test_create_and_execute_workflow():
    client = MockKeeperHubClient()
    wf = (
        WorkflowBuilder("test")
        .manual_trigger()
        .action("balance", "web3/check-balance",
                network=Network.SEPOLIA,
                address="0x0000000000000000000000000000000000000001")
        .build()
    )
    saved = client.create_workflow(wf)
    assert saved.id is not None
    assert len(saved.nodes) == 2
    assert len(saved.edges) == 1

    execution = client.execute_workflow(saved.id)
    assert execution.status.value == "success"
    assert execution.workflowId == saved.id

    logs = client.get_execution_logs(execution.id)
    assert len(logs) == 1
    assert logs[0].status.value == "success"
    assert logs[0].output is not None
    assert logs[0].output["balance"] == "0.1234"


def test_check_balance_shortcut():
    client = MockKeeperHubClient()
    out = client.check_balance("11155111", "0xabcdef0123456789abcdef0123456789abcdef01")
    assert out["balance"] == "0.1234"
    assert "executionId" in out


def test_missing_workflow_404():
    client = MockKeeperHubClient()
    try:
        client.get_workflow("wf_does_not_exist")
    except KeeperHubNotFoundError:
        pass
    else:
        raise AssertionError("expected KeeperHubNotFoundError")


def test_transfer_returns_tx_metadata():
    client = MockKeeperHubClient()
    wallet = client.get_wallet_integration()
    execution = client.transfer_funds(
        "11155111",
        "0x9c8f005ab27adb94f3d49020a15722db2fcd9f27",
        "0.001",
        wallet.id,
    )
    assert execution.status.value == "success"
    output = execution.output or {}
    assert output["status"] == "confirmed"
    assert output["private"] is True
    assert output["txHash"].startswith("0x")
    assert output["transactionLink"].startswith("https://")


def test_ai_generate_workflow_creates_real_workflow():
    client = MockKeeperHubClient()
    wf = client.ai_generate_workflow("send daily balance report")
    assert wf.id is not None
    assert any(n.type == "action" for n in wf.nodes)
