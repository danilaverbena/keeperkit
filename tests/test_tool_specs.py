"""Tests for the framework-agnostic ToolSpec catalogue."""

from __future__ import annotations

from keeperkit import MockKeeperHubClient
from keeperkit.tools._common import (
    STATIC_TOOL_SPECS,
    build_all_tool_specs,
    build_workflow_tools,
    safe_dispatch,
)


def test_static_tools_have_unique_names_and_schemas():
    names = [s.name for s in STATIC_TOOL_SPECS]
    assert len(names) == len(set(names))
    for s in STATIC_TOOL_SPECS:
        assert s.parameters.get("type") == "object"
        assert s.metadata.get("static") is True


def test_workflow_tools_generated_from_catalogue():
    client = MockKeeperHubClient()
    wf_specs = build_workflow_tools(client)
    expected_slugs = {wf["listedSlug"] for wf in client.list_workflows()["items"]
                      if wf.get("listedSlug")}
    actual_slugs = {s.metadata["slug"] for s in wf_specs}
    assert actual_slugs == expected_slugs
    # Names are namespaced with `keeperhub_`.
    for s in wf_specs:
        assert s.name.startswith("keeperhub_")
        assert s.metadata.get("static") is False


def test_build_all_combines_static_and_workflow():
    client = MockKeeperHubClient()
    all_specs = build_all_tool_specs(client)
    static_names = {s.name for s in STATIC_TOOL_SPECS}
    assert static_names <= {s.name for s in all_specs}
    assert len(all_specs) == len(STATIC_TOOL_SPECS) + len(build_workflow_tools(client))


def test_workflow_tools_handle_null_description_and_name():
    """Real KeeperHub catalogue can return entries with description=null;
    the spec builder must fall back to name/slug instead of crashing."""
    client = MockKeeperHubClient(catalogue=[
        {
            "id": "wf_null_desc",
            "name": None,
            "description": None,
            "listedSlug": "weird-workflow",
            "workflowType": "read",
            "priceUsdcPerCall": None,
            "inputSchema": {"type": "object", "properties": {}},
        }
    ])
    specs = build_workflow_tools(client)
    assert len(specs) == 1
    assert specs[0].name == "keeperhub_weird_workflow"
    assert "weird-workflow" in specs[0].description


def test_safe_dispatch_handles_payment_required():
    client = MockKeeperHubClient()
    specs = build_workflow_tools(client)
    aave_spec = next(s for s in specs if s.metadata["slug"] == "aave-v3-health-check")
    res = safe_dispatch(aave_spec, client,
                        address="0x000000000000000000000000000000000000dEaD")
    assert res["ok"] is False
    assert res["error"] == "payment_required"
    assert res["x402"]["x402Version"] == 2
    assert res["amount_usdc"]


def test_safe_dispatch_unwraps_success():
    client = MockKeeperHubClient()
    specs = build_workflow_tools(client)
    hello = next(s for s in specs if s.metadata["slug"] == "helloworld")
    res = safe_dispatch(hello, client)
    assert res["ok"] is True
    assert res["data"]["status"] == "success"


def test_safe_dispatch_static_list_workflows():
    client = MockKeeperHubClient()
    list_spec = next(s for s in STATIC_TOOL_SPECS
                     if s.name == "keeperhub_list_workflows")
    res = safe_dispatch(list_spec, client)
    assert res["ok"] is True
    assert res["data"]["items"]


def test_safe_dispatch_static_call_workflow_with_payment():
    client = MockKeeperHubClient()
    call_spec = next(s for s in STATIC_TOOL_SPECS
                     if s.name == "keeperhub_call_workflow")
    res = safe_dispatch(
        call_spec, client,
        slug="aave-v3-health-check",
        body={"address": "0x000000000000000000000000000000000000dEaD"},
        x_payment="mock-token",
    )
    assert res["ok"] is True
    assert res["data"]["output"]["result"]["healthFactor"] == "2.13"
