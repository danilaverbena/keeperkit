"""Minimal CrewAI example using KeeperKit tools.

Run with::

    pip install -e ".[crewai]"
    OPENAI_API_KEY=sk-… python examples/crewai_demo.py
"""

from __future__ import annotations

import os

from crewai import Agent, Crew, Task

from keeperkit import KeeperHubClient, MockKeeperHubClient
from keeperkit.tools.crewai import build_crewai_tools


def main() -> None:
    client = (KeeperHubClient.from_env()
              if os.environ.get("KEEPERHUB_API_KEY") else MockKeeperHubClient())

    tools = build_crewai_tools(client)
    trader = Agent(
        role="Onchain Operations",
        goal="Reliably read balances and submit transactions via KeeperHub.",
        backstory=("You always delegate execution to KeeperHub for retry, "
                   "gas optimization, and MEV-aware private routing."),
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )
    task = Task(
        description=(
            "Check the Sepolia balance of "
            "0x9c8f005ab27adb94f3d49020a15722db2fcd9f27 and report whether it "
            "is below 0.01 ETH."
        ),
        expected_output="A one-line summary including the balance and the threshold check.",
        agent=trader,
    )
    crew = Crew(agents=[trader], tasks=[task], verbose=True)
    print(crew.kickoff())


if __name__ == "__main__":
    main()
