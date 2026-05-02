"""Framework-specific KeeperHub tool factories.

Each submodule exposes a ``build_*_tools(client)`` helper that turns a
:class:`KeeperHubClient` (or :class:`MockKeeperHubClient`) into the tool
objects expected by that framework.
"""

from keeperkit.tools._common import KEEPERHUB_TOOL_SPECS, ToolSpec, default_dispatch

__all__ = ["KEEPERHUB_TOOL_SPECS", "ToolSpec", "default_dispatch"]
