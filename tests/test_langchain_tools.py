"""Smoke tests for the LangChain adapter, skipped if langchain-core missing."""
from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")

from keeperkit import MockKeeperHubClient
from keeperkit.tools.langchain import build_langchain_tools


def test_builds_tools_against_mock():
    tools = build_langchain_tools(MockKeeperHubClient())
    names = {t.name for t in tools}
    assert "keeperhub_check_balance" in names
    assert "keeperhub_execute_workflow" in names


def test_tool_invocation_returns_ok():
    tools = build_langchain_tools(MockKeeperHubClient(),
                                  only=["keeperhub_check_balance"])
    tool = tools[0]
    result = tool.invoke({
        "network": "11155111",
        "address": "0x0000000000000000000000000000000000000001",
    })
    assert result["ok"] is True
    assert "data" in result
