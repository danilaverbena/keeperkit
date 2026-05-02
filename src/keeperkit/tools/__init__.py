"""Framework-specific KeeperHub tool factories.

Each submodule exposes a ``build_*_tools(client)`` helper that turns a
:class:`KeeperHubClient` (or :class:`MockKeeperHubClient`) into the tool
objects expected by that framework.
"""

from keeperkit.tools._common import (
    STATIC_TOOL_SPECS,
    ToolSpec,
    build_all_tool_specs,
    build_workflow_tools,
    safe_dispatch,
)

__all__ = [
    "STATIC_TOOL_SPECS",
    "ToolSpec",
    "build_all_tool_specs",
    "build_workflow_tools",
    "safe_dispatch",
]
