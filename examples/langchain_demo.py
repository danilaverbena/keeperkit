"""Minimal LangChain example.

Run with::

    pip install -e ".[langchain,server]"
    OPENAI_API_KEY=sk-… python examples/langchain_demo.py

If ``KEEPERHUB_API_KEY`` is missing, the example falls back to the in-memory
mock client so you can still see end-to-end agent traces.
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from keeperkit import KeeperHubClient, MockKeeperHubClient
from keeperkit.tools.langchain import build_langchain_tools


def main() -> None:
    if os.environ.get("KEEPERHUB_API_KEY"):
        client = KeeperHubClient.from_env()
        print("[demo] using real KeeperHub backend at", client.base_url)
    else:
        client = MockKeeperHubClient()
        print("[demo] no KEEPERHUB_API_KEY — using in-memory mock backend")

    tools = build_langchain_tools(client)
    llm = ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
    agent = create_react_agent(llm, tools)

    prompt = (
        "Check the native balance of 0x9c8f005ab27adb94f3d49020a15722db2fcd9f27 "
        "on Sepolia and report it."
    )
    response = agent.invoke({"messages": [("user", prompt)]})
    for msg in response["messages"]:
        kind = getattr(msg, "type", msg.__class__.__name__)
        content = getattr(msg, "content", "")
        print(f"--- {kind} ---")
        print(content)


if __name__ == "__main__":
    main()
