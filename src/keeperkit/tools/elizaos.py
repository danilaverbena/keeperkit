"""ElizaOS bridge.

ElizaOS is TypeScript-first, so ``keeperkit-elizaos`` ships as a generated
plugin descriptor (``elizaos/keeperkit-plugin.json``) plus a thin Python helper
that emits the JSON your ElizaOS character file imports.

Why we generate the plugin from Python:

* The tool catalogue, descriptions, and JSON Schemas are defined once in
  :mod:`keeperkit.tools._common` and shared across LangChain, CrewAI, and
  ElizaOS — there is no risk of drift between frameworks.
* It keeps the demo server self-contained — no Node toolchain required to
  produce the artifact builders can drop into their ElizaOS character.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from keeperkit.tools._common import KEEPERHUB_TOOL_SPECS


def build_elizaos_plugin_descriptor(*, base_url: str = "https://app.keeperhub.com/api",
                                    version: str = "0.1.0") -> dict[str, Any]:
    """Return a JSON-serializable ElizaOS plugin descriptor for KeeperHub."""
    actions = []
    for spec in KEEPERHUB_TOOL_SPECS:
        actions.append({
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
            "dispatch": {
                "kind": "http",
                "method": "POST",
                "url": f"{base_url}/keeperkit/dispatch",
                "auth": "bearer:KEEPERHUB_API_KEY",
                "body": {"tool": spec.name},
            },
        })

    return {
        "name": "@keeperkit/elizaos-plugin",
        "version": version,
        "description": (
            "KeeperHub onchain execution plugin for ElizaOS. Routes agent "
            "transactions through KeeperHub's reliable execution layer "
            "(retry, gas optimization, MEV-aware private routing, audit "
            "trail, x402 / MPP payment rails)."
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


def write_elizaos_plugin(out_path: str | Path,
                         *, base_url: str = "https://app.keeperhub.com/api") -> Path:
    """Write the ElizaOS plugin descriptor JSON to disk and return the path."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_elizaos_plugin_descriptor(base_url=base_url), indent=2),
        encoding="utf-8",
    )
    return path
