# KeeperKit

> 🛠️ Unified [KeeperHub](https://keeperhub.com) plugin for **LangChain**, **CrewAI**, and **ElizaOS** — give your AI agent reliable onchain execution in one import.

[![Live demo](https://img.shields.io/badge/live%20demo-keeperkit.danilaverbena.dev-2dff7d?style=flat-square)](https://keeperkit.danilaverbena.dev)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white&style=flat-square)](pyproject.toml)
[![ETHGlobal OpenAgents](https://img.shields.io/badge/built%20for-ETHGlobal%20OpenAgents-orange?style=flat-square)](https://ethglobal.com/events/openagents/prizes/keeperhub)

KeeperKit is the missing glue between modern AI agent frameworks and
[KeeperHub](https://keeperhub.com), the execution and reliability layer powering
[Sky Protocol](https://sky.money) (formerly MakerDAO). Drop it into any
LangChain / CrewAI / ElizaOS agent and onchain transactions get retry
discipline, gas escalation, simulation-before-submit, MEV-aware private
routing, and a queryable audit trail — without rewriting your agent.

```text
┌──────────────────────────────────────────────────────┐
│  Your agent (LangChain · CrewAI · ElizaOS · custom)  │
└───────────────────────┬──────────────────────────────┘
                        │  one import
            ┌───────────▼─────────────┐
            │  KeeperKit tool catalog │
            │  (12 tools, shared      │
            │   spec + JSON schema)   │
            └───────────┬─────────────┘
                        │  HTTP / MCP
                ┌───────▼───────┐
                │   KeeperHub   │  retry · gas opt · MEV-private routing
                │   execution   │  audit trail · x402 / MPP payments
                │     layer     │
                └───────┬───────┘
                        │
                ┌───────▼────────┐
                │  EVM chains    │  Ethereum · Base · Arbitrum · Polygon · …
                └────────────────┘
```

---

## Why?

KeeperHub already exposes a polished MCP server and REST API. But:

* every framework wants tools shaped a little differently,
* every team wires retry/error-handling slightly differently,
* signing up for an API key takes a few minutes, which is too long for the
  first hour of a hackathon.

KeeperKit fixes all three:

| Pain | KeeperKit answer |
|---|---|
| Boilerplate per framework | One tool catalog, three adapters (`build_langchain_tools`, `build_crewai_tools`, ElizaOS plugin descriptor). |
| Reliability | Outer retry + backoff on top of KeeperHub's own retry. Exception types map to HTTP status. |
| Local DX | `MockKeeperHubClient` is a drop-in stand-in: workflow CRUD, executions, logs, even AI-generated workflows. Ship code on a plane. |
| ElizaOS friction | One Python call generates the action descriptor JSON your character imports. No Node toolchain needed. |
| Demo / proof | `python -m keeperkit.server` boots a dashboard with a ReAct agent, direct tool dispatch, and live KeeperHub status. |

---

## Install

```bash
# Core SDK + framework adapters
pip install "keeperkit[langchain,crewai] @ git+https://github.com/danilaverbena/keeperkit"

# Or for local development
git clone https://github.com/danilaverbena/keeperkit && cd keeperkit
pip install -e ".[langchain,crewai,server,dev]"
```

KeeperKit is intentionally minimal at the core (`httpx` + `pydantic` +
`anyio`); the framework adapters are optional extras.

---

## 30-second tour

```python
from keeperkit import KeeperHubClient
from keeperkit.tools.langchain import build_langchain_tools
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

client = KeeperHubClient.from_env()           # reads KEEPERHUB_API_KEY
tools  = build_langchain_tools(client)        # 12 KeeperHub tools
agent  = create_react_agent(ChatOpenAI(model="gpt-4o-mini"), tools)

agent.invoke({"messages": [(
    "user",
    "Send 0.01 ETH to 0xabc… on Sepolia, then tell me the tx hash.",
)]})
```

The agent will call `keeperhub_get_wallet_integration` → `keeperhub_transfer_funds`
→ `keeperhub_get_execution_status`, and KeeperHub takes care of the rest.

### CrewAI

```python
from keeperkit import KeeperHubClient
from keeperkit.tools.crewai import build_crewai_tools
from crewai import Agent

client = KeeperHubClient.from_env()
trader = Agent(
    role="Onchain trader",
    goal="Execute trades reliably on Sepolia.",
    tools=build_crewai_tools(client),
    backstory="Always delegate execution to KeeperHub.",
)
```

### ElizaOS

```bash
# Generate the plugin descriptor your character file imports.
python - <<'PY'
from keeperkit.tools.elizaos import write_elizaos_plugin
write_elizaos_plugin("./elizaos/keeperkit-plugin.json")
PY
```

Then add it to your character:

```jsonc
{
  "name": "Treasurer",
  "plugins": ["./elizaos/keeperkit-plugin.json"],
  "settings": { "secrets": { "KEEPERHUB_API_KEY": "kh_…" } }
}
```

See [`examples/elizaos_plugin.md`](examples/elizaos_plugin.md) for the full
guide.

---

## Tool catalogue

All adapters share the same 12 tools, defined in
[`keeperkit/tools/_common.py`](src/keeperkit/tools/_common.py):

| Tool | What it does |
|---|---|
| `keeperhub_list_workflows` | List configured workflows in your org. |
| `keeperhub_get_workflow` | Fetch a workflow's full nodes + edges. |
| `keeperhub_execute_workflow` | Trigger a stored workflow with optional inputs. |
| `keeperhub_get_execution_status` | Poll execution state + per-node progress. |
| `keeperhub_get_execution_logs` | Audit trail with tx hashes, durations, errors. |
| `keeperhub_check_balance` | Read native balance on any supported EVM chain. |
| `keeperhub_transfer_funds` | Send native token via KeeperHub's reliable path. |
| `keeperhub_write_contract` | Call a state-changing contract function reliably. |
| `keeperhub_list_action_schemas` | Discover available KeeperHub actions. |
| `keeperhub_ai_generate_workflow` | Use KeeperHub's LLM to spawn a workflow from prose. |
| `keeperhub_get_wallet_integration` | Resolve the wallet ID needed for write actions. |
| (more added over time) | — |

---

## The mock client

```python
from keeperkit import MockKeeperHubClient
from keeperkit.tools.langchain import build_langchain_tools

client = MockKeeperHubClient()                # zero credentials needed
tools  = build_langchain_tools(client)
```

The mock matches the real client's surface 1:1: workflow CRUD, executions
with deterministic `txHash` / `transactionLink`, logs, action schemas, AI
generation. Every framework adapter accepts it — so you can write your demo
flow before anyone on your team has signed up for KeeperHub.

When you're ready to hit the real API, swap one line:

```diff
- client = MockKeeperHubClient()
+ client = KeeperHubClient.from_env()
```

…or set `KEEPERHUB_API_KEY` and use the demo server: it auto-detects the
mode and shows a badge in the UI.

---

## The demo server

```bash
cp .env.example .env
$EDITOR .env                                  # add KEEPERHUB_API_KEY (optional)
pip install -e ".[server]"
python -m keeperkit.server                    # serves at http://0.0.0.0:8000
```

What you get:

* **Dashboard** at `/` — live status badge, prompt box, direct tool dispatch.
* **`POST /api/agent/run`** — LangChain ReAct agent. Auto-picks OpenAI,
  Anthropic, Google Gemini, Groq, DeepSeek, OpenRouter, Mistral, Together, or
  Ollama based on which API key is set; falls back to an LLM-less heuristic
  if none are configured.
* **`POST /api/tools/{name}`** — one-shot dispatch to any KeeperKit tool.
* **`GET /api/elizaos/plugin.json`** — live ElizaOS plugin descriptor.
* **`POST /keeperkit/dispatch`** — bridge endpoint for the ElizaOS plugin.
* **`/docs`** — full OpenAPI spec.

---

## Configuration

### Getting a KeeperHub API key

1. Sign up / log in at <https://keeperhub.com>.
2. Open or create an **Organization** (top-right menu — *Personal* keys cannot
   execute workflows).
3. **Settings → API Keys → Organisation tab → New API Key.**
4. Copy the `kh_…` token into `KEEPERHUB_API_KEY`.

Without a key, KeeperKit runs against the in-memory `MockKeeperHubClient` so
you can demo end-to-end with no external dependencies.

### Picking an LLM

KeeperKit's demo agent is built on LangChain — **any** chat model works.
The server auto-detects whichever provider key is in your environment, in
this priority order:

`anthropic → google → groq → deepseek → openrouter → mistral → together → ollama → openai`

| Provider | Env var | Free tier? | Where to get a key |
|---|---|---|---|
| **OpenAI** | `OPENAI_API_KEY` | paid | <https://platform.openai.com/api-keys> |
| **Anthropic Claude** | `ANTHROPIC_API_KEY` | trial credits | <https://console.anthropic.com/settings/keys> |
| **Google Gemini** | `GOOGLE_API_KEY` | **yes** | <https://aistudio.google.com/app/apikey> |
| **Groq** | `GROQ_API_KEY` | **yes (fast)** | <https://console.groq.com/keys> |
| **DeepSeek** | `DEEPSEEK_API_KEY` | cheap paid | <https://platform.deepseek.com/api_keys> |
| **OpenRouter** | `OPENROUTER_API_KEY` | pay-as-you-go, 200+ models | <https://openrouter.ai/keys> |
| **Mistral** | `MISTRAL_API_KEY` | trial credits | <https://console.mistral.ai/api-keys> |
| **Together AI** | `TOGETHER_API_KEY` | trial credits | <https://api.together.xyz/settings/api-keys> |
| **Ollama (local)** | `OLLAMA_BASE_URL` | **free, runs locally** | <https://ollama.com> |

Override either the provider or the model explicitly:

```bash
export KEEPERKIT_LLM_PROVIDER=groq
export KEEPERKIT_LLM_MODEL=llama-3.1-8b-instant
```

The `[server]` extra bundles `langchain-openai`, `langchain-anthropic`,
`langchain-google-genai`, and `langchain-groq` so the most common providers
work out of the box. For Mistral / Ollama install the matching extra
(`pip install -e ".[mistral]"`, `".[ollama]"`).

### All env vars

| Env var | Default | What it does |
|---|---|---|
| `KEEPERHUB_API_KEY` | — | `kh_…` org key. Without it, the demo runs in mock mode. |
| `KEEPERHUB_BASE_URL` | `https://app.keeperhub.com/api` | Override for self-hosted KeeperHub. |
| `KEEPERKIT_MODE` | `real` | Set to `mock` to force the in-memory backend. |
| `KEEPERKIT_LLM_PROVIDER` | auto | Pin a provider (`openai`, `anthropic`, `google`, `groq`, `deepseek`, `openrouter`, `mistral`, `together`, `ollama`). |
| `KEEPERKIT_LLM_MODEL` | provider-specific | Override the chat model for the active provider. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | — | Standard OpenAI knobs. `OPENAI_BASE_URL` lets you point at LM Studio / vLLM / LiteLLM / Azure OpenAI proxies. |
| `ANTHROPIC_API_KEY` | — | Enables Claude. |
| `GOOGLE_API_KEY` | — | Enables Gemini. |
| `GROQ_API_KEY` | — | Enables Groq. |
| `DEEPSEEK_API_KEY` | — | Enables DeepSeek (via OpenAI-compatible endpoint). |
| `OPENROUTER_API_KEY` | — | Enables OpenRouter (via OpenAI-compatible endpoint). |
| `MISTRAL_API_KEY` | — | Enables Mistral. |
| `TOGETHER_API_KEY` | — | Enables Together AI. |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | — | Use a local Ollama server. |
| `KEEPERKIT_HOST` | `0.0.0.0` | Bind host for the demo server. |
| `KEEPERKIT_PORT` | `8000` | Bind port for the demo server. |

---

## Development

```bash
pip install -e ".[langchain,crewai,server,dev]"
pytest -q                                # mock + langchain + REST error tests
ruff check src tests
```

The test suite uses [respx](https://github.com/lundberg/respx) to fake the
KeeperHub REST API so you can run it offline. Mock-backed integration tests
live in `tests/test_mock.py`.

---

## How this maps to KeeperHub's hackathon prize

This project targets the [KeeperHub Best Use prize](https://ethglobal.com/events/openagents/prizes/keeperhub)
on **both** focus areas:

* **Focus area 1 — Innovative Use:** the demo server's heuristic + ReAct
  agent shows KeeperHub turning into the execution backbone of a generic
  agent framework. The ElizaOS plugin descriptor is generated dynamically
  from the same shared catalogue.
* **Focus area 2 — Integration:** ready-to-use plugin/SDK integrations for
  three of the active builder communities listed in the prize description
  (LangChain, CrewAI, ElizaOS). Plus the
  [Builder Feedback Bounty](FEEDBACK.md) submission with concrete
  reproducible findings.

---

## Repo layout

```
keeperkit/
├── src/keeperkit/
│   ├── client.py            # sync + async REST client w/ retry + error mapping
│   ├── mock.py              # in-memory backend
│   ├── workflow.py          # WorkflowBuilder DSL
│   ├── models.py            # pydantic models
│   ├── exceptions.py        # KeeperHubAPIError hierarchy
│   ├── tools/
│   │   ├── _common.py       # shared 12-tool catalogue
│   │   ├── langchain.py     # StructuredTool factory
│   │   ├── crewai.py        # crewai.tools.BaseTool factory
│   │   └── elizaos.py       # plugin descriptor generator
│   └── server/              # FastAPI demo + dashboard
├── examples/                # langchain / crewai / elizaos / quickstart
├── tests/                   # pytest suite (offline)
├── deploy/                  # systemd + nginx for production
├── FEEDBACK.md              # KeeperHub Builder Feedback Bounty submission
└── README.md                # this file
```

---

## License

MIT © 2025 KeeperKit contributors.
