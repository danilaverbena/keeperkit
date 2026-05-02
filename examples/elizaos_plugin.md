# Using KeeperKit with ElizaOS

ElizaOS characters consume action plugins as JSON. KeeperKit ships a plugin
descriptor generator so you don't have to hand-write the action definitions.

## 1 · Generate the plugin descriptor

```bash
python -c "from keeperkit.tools.elizaos import write_elizaos_plugin; \
           write_elizaos_plugin('./elizaos/keeperkit-plugin.json', \
                                base_url='https://app.keeperhub.com/api')"
```

Or fetch it from the live demo server:

```bash
curl -s https://your-keeperkit-server/api/elizaos/plugin.json \
    > elizaos/keeperkit-plugin.json
```

## 2 · Reference it in your character

```jsonc
{
  "name": "Treasurer",
  "plugins": [
    "./elizaos/keeperkit-plugin.json"
  ],
  "settings": {
    "secrets": {
      "KEEPERHUB_API_KEY": "kh_…"
    }
  }
}
```

## 3 · How dispatch works

Each ElizaOS action is wired to call back into the KeeperKit demo server's
`/keeperkit/dispatch` endpoint with `{"tool": "...", "arguments": {...}}`.
That endpoint forwards to the same shared tool registry used by the
LangChain and CrewAI adapters — no duplicate definitions.

If you want ElizaOS to talk to KeeperHub directly (skipping the bridge),
fork the descriptor and replace each action's `dispatch.url` with the
matching KeeperHub REST endpoint. The names and parameters stay identical.
