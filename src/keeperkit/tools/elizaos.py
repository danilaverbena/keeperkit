"""ElizaOS bridge.

ElizaOS is TypeScript-first, so ``keeperkit-elizaos`` ships as a generated
plugin descriptor (``elizaos/keeperkit-plugin.json``) plus a thin Python helper
that emits the JSON your ElizaOS character file imports.

Why we generate the plugin from Python:

* The tool catalogue, descriptions, and JSON Schemas are defined once in
  :mod:`keeperkit.tools._common` and shared across LangChain, CrewAI, and
  ElizaOS — there is no risk of drift between frameworks.
* The descriptor includes both the static tools (``keeperhub_call_workflow``,
  ``keeperhub_list_workflows``, …) **and** an action per discoverable
  workflow when a client is supplied — so an ElizaOS character can call
  ``keeperhub_microtip`` directly with typed args.
* It keeps the demo server self-contained — no Node toolchain required to
  produce the artifact builders can drop into their ElizaOS character.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from keeperkit.tools._common import (
    STATIC_TOOL_SPECS,
    ToolSpec,
    build_all_tool_specs,
)


def _action_from_spec(spec: ToolSpec, *, base_url: str) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.parameters,
        "metadata": dict(spec.metadata or {}),
        "dispatch": {
            "kind": "http",
            "method": "POST",
            "url": f"{base_url.rstrip('/')}/keeperkit/dispatch",
            "auth": "bearer:KEEPERHUB_API_KEY",
            "body": {"tool": spec.name},
        },
    }


def build_elizaos_plugin_descriptor(
    *,
    client: Any | None = None,
    base_url: str = "https://app.keeperhub.com/api",
    version: str = "0.1.0",
) -> dict[str, Any]:
    """Return a JSON-serializable ElizaOS plugin descriptor for KeeperHub.

    Args:
        client: When supplied, the descriptor will additionally include an
            action per discoverable KeeperHub workflow (auto-generated from
            ``client.list_workflows()``). When ``None``, only the static
            tools are included — useful for offline descriptor generation.
        base_url: Where the descriptor's ``dispatch`` URL should point.
        version: Plugin version.
    """
    if client is not None:
        specs: list[ToolSpec] = build_all_tool_specs(client)
    else:
        specs = list(STATIC_TOOL_SPECS)

    actions = [_action_from_spec(s, base_url=base_url) for s in specs]

    return {
        "name": "@keeperkit/elizaos-plugin",
        "version": version,
        "description": (
            "KeeperHub workflow plugin for ElizaOS. Gives your character "
            "typed access to the public KeeperHub workflow catalogue (DeFi "
            "reads, payments, write transactions) with built-in x402 "
            "payment-required handling."
        ),
        "homepage": "https://github.com/danilaverbena/keeperkit",
        "actions": actions,
        "envVars": [
            {"name": "KEEPERHUB_API_KEY", "required": True,
             "description": "Organization API key (kh_...) from KeeperHub."},
            {"name": "KEEPERHUB_BASE_URL", "required": False,
             "default": "https://app.keeperhub.com/api"},
        ],
    }


def write_elizaos_plugin(
    out_path: str | Path,
    *,
    client: Any | None = None,
    base_url: str = "https://app.keeperhub.com/api",
) -> Path:
    """Write the ElizaOS plugin descriptor JSON to disk and return the path."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            build_elizaos_plugin_descriptor(client=client, base_url=base_url),
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
