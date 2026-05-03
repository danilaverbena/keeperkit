"""ElizaOS plugin descriptor tests."""

from __future__ import annotations

from keeperkit import MockKeeperHubClient
from keeperkit.tools.elizaos import (
    build_elizaos_plugin_descriptor,
    write_elizaos_plugin,
)


def test_static_only_descriptor_includes_core_actions():
    desc = build_elizaos_plugin_descriptor()
    names = {a["name"] for a in desc["actions"]}
    assert {"keeperhub_list_workflows", "keeperhub_call_workflow"} <= names
    assert all(a["dispatch"]["kind"] == "http" for a in desc["actions"])


def test_descriptor_with_client_includes_per_workflow_actions():
    client = MockKeeperHubClient()
    desc = build_elizaos_plugin_descriptor(client=client)
    names = {a["name"] for a in desc["actions"]}
    assert "keeperhub_helloworld" in names
    assert "keeperhub_aave_v3_health_check" in names


def test_write_elizaos_plugin_to_disk(tmp_path):
    out = write_elizaos_plugin(tmp_path / "plugin.json",
                               client=MockKeeperHubClient())
    assert out.exists()
    text = out.read_text()
    assert "keeperhub_helloworld" in text
