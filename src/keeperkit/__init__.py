"""KeeperKit — unified KeeperHub plugin for AI agent frameworks.

Give your LangChain / CrewAI / ElizaOS agent reliable onchain execution in one
import. KeeperKit wraps KeeperHub's REST API and MCP tools in:

* a plain async/sync :class:`KeeperHubClient` for direct integration,
* an in-memory :class:`MockKeeperHubClient` for tests and offline demos,
* framework-specific tool factories under :mod:`keeperkit.tools`.

Example::

    from keeperkit import KeeperHubClient
    from keeperkit.tools.langchain import build_langchain_tools

    client = KeeperHubClient.from_env()
    tools = build_langchain_tools(client)
    # ... pass `tools` to any LangChain / LangGraph agent.
"""

from keeperkit.client import AsyncKeeperHubClient, KeeperHubClient
from keeperkit.exceptions import (
    KeeperHubAPIError,
    KeeperHubAuthError,
    KeeperHubNotFoundError,
    KeeperHubPaymentRequired,
    KeeperHubValidationError,
)
from keeperkit.mock import MockKeeperHubClient

__version__ = "0.1.0"

__all__ = [
    "AsyncKeeperHubClient",
    "KeeperHubAPIError",
    "KeeperHubAuthError",
    "KeeperHubClient",
    "KeeperHubNotFoundError",
    "KeeperHubPaymentRequired",
    "KeeperHubValidationError",
    "MockKeeperHubClient",
    "__version__",
]
