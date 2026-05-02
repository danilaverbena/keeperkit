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
        goal="Use KeeperHub workflows to monitor and act on DeFi positions.",
        backstory=("You delegate every onchain action to a KeeperHub "
                   "workflow. Paid workflows are settled via x402."),
        tools=tools,
        verbose=True,
        allow_delegation=False,
    )
    task = Task(
        description=(
            "Inspect the KeeperHub workflow catalogue, pick the right "
            "workflow to check the Aave v3 health factor for "
            "0x9c8f005ab27adb94f3d49020a15722db2fcd9f27, and call it. "
            "If the tool returns `payment_required`, summarise the x402 "
            "descriptor and stop instead of guessing a result."
        ),
        expected_output="Either the health factor + summary, or a clear x402 payment-required note.",
        agent=trader,
    )
    crew = Crew(agents=[trader], tasks=[task], verbose=True)
    print(crew.kickoff())


if __name__ == "__main__":
    main()
