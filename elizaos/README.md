# ElizaOS plugin descriptor

[`keeperkit-plugin.json`](keeperkit-plugin.json) is the action plugin
descriptor consumed by an ElizaOS character. It's auto-generated from the
shared tool catalogue in
[`src/keeperkit/tools/_common.py`](../src/keeperkit/tools/_common.py).

## Regenerate

```bash
python -c "from keeperkit.tools.elizaos import write_elizaos_plugin; \
           write_elizaos_plugin('elizaos/keeperkit-plugin.json', \
                                base_url='https://app.keeperhub.com/api')"
```

## Reference it from a character

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

Each action's `dispatch.url` points back at the KeeperKit demo server's
`/keeperkit/dispatch` endpoint, which forwards into the same registry the
LangChain and CrewAI adapters use. If you'd rather have ElizaOS hit the
KeeperHub REST API directly, fork the descriptor and replace each action's
`dispatch.url` with the matching upstream endpoint — names and parameters
stay identical.
