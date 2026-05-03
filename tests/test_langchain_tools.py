"""LangChain adapter tests."""

from __future__ import annotations

import pytest

from keeperkit import MockKeeperHubClient
from keeperkit.tools._common import STATIC_TOOL_SPECS

langchain_core = pytest.importorskip("langchain_core")


def test_build_langchain_tools_includes_static_and_workflow():
    from keeperkit.tools.langchain import build_langchain_tools

    client = MockKeeperHubClient()
    tools = build_langchain_tools(client)
    names = {t.name for t in tools}

    static_names = {s.name for s in STATIC_TOOL_SPECS}
    assert static_names <= names
    assert "keeperhub_helloworld" in names
    assert "keeperhub_aave_v3_health_check" in names


def test_workflow_tool_runs_against_mock():
    from keeperkit.tools.langchain import build_langchain_tools

    client = MockKeeperHubClient()
    tools = build_langchain_tools(client)
    helloworld = next(t for t in tools if t.name == "keeperhub_helloworld")

    out = helloworld.invoke({})
    assert out["ok"] is True
    assert out["data"]["status"] == "success"


def test_paid_workflow_tool_returns_payment_required():
    from keeperkit.tools.langchain import build_langchain_tools

    client = MockKeeperHubClient()
    tools = build_langchain_tools(client)
    aave = next(t for t in tools if t.name == "keeperhub_aave_v3_health_check")

    out = aave.invoke({"address": "0x0000000000000000000000000000000000000000"})
    assert out["ok"] is False
    assert out["error"] == "payment_required"
    assert out["x402"]["x402Version"] == 2


def test_static_call_workflow_tool_can_call_anything():
    from keeperkit.tools.langchain import build_langchain_tools

    client = MockKeeperHubClient()
    tools = build_langchain_tools(client)
    universal = next(t for t in tools if t.name == "keeperhub_call_workflow")

    out = universal.invoke({"slug": "helloworld", "body": {}})
    assert out["ok"] is True
    assert out["data"]["output"]["result"]["message"] == "Hello World!"


def test_include_per_workflow_false_keeps_only_static():
    from keeperkit.tools.langchain import build_langchain_tools

    client = MockKeeperHubClient()
    tools = build_langchain_tools(client, include_per_workflow=False)
    names = {t.name for t in tools}
    assert names == {s.name for s in STATIC_TOOL_SPECS}
