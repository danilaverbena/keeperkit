from keeperkit import MockKeeperHubClient
from keeperkit.tools._common import KEEPERHUB_TOOL_SPECS, default_dispatch, find_spec


def test_every_spec_dispatches_against_mock():
    client = MockKeeperHubClient()
    # The mock has no created workflows, so calls expecting an id should not
    # be dispatched here. We just smoke-test the read-only / no-arg ones.
    for spec in KEEPERHUB_TOOL_SPECS:
        if spec.dispatch_key in ("get_workflow", "execute_workflow",
                                  "get_execution_status", "get_execution_logs"):
            continue
        if spec.dispatch_key in ("transfer_funds", "write_contract"):
            args = {"network": "11155111",
                    "to_address": "0x0000000000000000000000000000000000000001",
                    "amount": "0.001",
                    "wallet_id": "wallet_mock_main"}
            if spec.dispatch_key == "write_contract":
                args = {"network": "11155111",
                        "contract_address": "0xcafe000000000000000000000000000000000000",
                        "function_name": "transfer",
                        "wallet_id": "wallet_mock_main",
                        "args": ["0x0000000000000000000000000000000000000001", "1"]}
            result = default_dispatch(client, spec, **args)
        elif spec.dispatch_key == "check_balance":
            result = default_dispatch(
                client, spec,
                network="11155111",
                address="0x0000000000000000000000000000000000000001",
            )
        elif spec.dispatch_key == "ai_generate_workflow":
            result = default_dispatch(client, spec, description="test")
        else:
            result = default_dispatch(client, spec)
        assert result["ok"] is True


def test_find_spec_roundtrip():
    spec = find_spec("keeperhub_check_balance")
    assert spec.dispatch_key == "check_balance"
