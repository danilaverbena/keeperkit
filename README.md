# KeeperKit

> 🛠️ Unified [KeeperHub](https://keeperhub.com) plugin for **LangChain**, **CrewAI**, and **ElizaOS** — give your AI agent typed access to every KeeperHub workflow, with built-in [x402](https://x402.org) payment-required handling, in one import.

[![Live demo](https://img.shields.io/badge/live%20demo-178.104.45.97%3A8420-2dff7d?style=flat-square)](http://178.104.45.97:8420)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white&style=flat-square)](pyproject.toml)
[![ETHGlobal OpenAgents](https://img.shields.io/badge/built%20for-ETHGlobal%20OpenAgents-orange?style=flat-square)](https://ethglobal.com/events/openagents/prizes/keeperhub)

KeeperKit is the missing glue between modern AI agent frameworks and
[KeeperHub](https://keeperhub.com)'s public workflow catalogue. KeeperHub
exposes a curated set of callable workflows (DeFi reads, payments, write
transactions) under `POST /api/mcp/workflows/{slug}/call` — KeeperKit turns
each one into a typed tool your LangChain / CrewAI / ElizaOS agent can call
directly.

```text
┌──────────────────────────────────────────────────────┐
│  Your agent (LangChain · CrewAI · ElizaOS · custom)  │
└───────────────────────┬──────────────────────────────┘
                        │  one import
            ┌───────────▼──────────────┐
            │  KeeperKit tool catalogue│
            │  • 5 static (discover/   │
            │    call/openapi/integ.)  │
            │  • 1 per workflow,       │
            │    auto-generated from   │
            │    /api/mcp/workflows    │
            └───────────┬──────────────┘
                        │  HTTP
                ┌───────▼───────┐
                │   KeeperHub   │  catalogue · simulate · retry · audit
                │   workflows   │  + x402 micropayments (USDC on Base)
                └───────┬───────┘
                        │
                ┌───────▼───────────────┐
                │  EVM chains           │  Ethereum · Base · Optimism · …
                └───────────────────────┘
```

---

## Why?

KeeperHub already exposes a polished public REST + MCP layer. The pain
points KeeperKit removes:

| Pain | KeeperKit answer |
|---|---|
| Each framework wants tools shaped a little differently | One shared `ToolSpec`, three thin adapters (`build_langchain_tools`, `build_crewai_tools`, `build_elizaos_plugin_descriptor`). |
| Tools drift behind the workflow catalogue | Tools are **auto-generated** from `GET /api/mcp/workflows` at build time — new workflow = new tool, no code change. |
| Paid (x402) workflows return HTTP 402 with a base64 descriptor | KeeperKit decodes it, raises `KeeperHubPaymentRequired`, and exposes `.x402` and `.amount_usdc` so your agent / x402 settlement layer can route the payment. |
| Local DX | `MockKeeperHubClient` ships a representative catalogue with free + paid workflows so you can run the full `safe_dispatch` / 402 flow offline. |
| Hackathon-grade demo | `python -m keeperkit.server` boots a FastAPI dashboard + ReAct agent + ElizaOS bridge in one command. |

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
tools  = build_langchain_tools(client)        # 5 static + 1 per workflow
agent  = create_react_agent(ChatOpenAI(model="gpt-4o-mini"), tools)

agent.invoke({"messages": [(
    "user",
    "Check the Aave v3 health factor for 0xabc… and warn me if liquidation risk is high.",
)]})
```

Behind the scenes the agent inspects `keeperhub_list_workflows`, picks
`keeperhub_aave_v3_health_check`, calls it with the typed `address` arg,
and reads the `executionId` + `output` back. Paid workflows surface
`{ok: false, error: "payment_required", x402: {...}, amount_usdc: ...}`
so your x402 client can settle and replay with the `X-Payment` header.

### CrewAI

```python
from keeperkit import KeeperHubClient
from keeperkit.tools.crewai import build_crewai_tools
from crewai import Agent

client = KeeperHubClient.from_env()
trader = Agent(
    role="Onchain ops",
    goal="Use KeeperHub workflows to monitor and act on DeFi positions.",
    tools=build_crewai_tools(client),
    backstory="Always delegate execution to KeeperHub.",
)
```

### ElizaOS

```bash
# Generate the plugin descriptor your character file imports.
python - <<'PY'
from keeperkit import KeeperHubClient
from keeperkit.tools.elizaos import write_elizaos_plugin
write_elizaos_plugin("./elizaos/keeperkit-plugin.json",
                     client=KeeperHubClient.from_env())
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

KeeperKit exposes two layers of tools, all defined in
[`keeperkit/tools/_common.py`](src/keeperkit/tools/_common.py):

### Static tools (always present)

| Tool | What it does |
|---|---|
| `keeperhub_list_workflows` | Discover the public workflow catalogue (`GET /api/mcp/workflows`). Returns slug, input schema, price, type, chain. |
| `keeperhub_call_workflow` | Universal escape hatch: call any workflow by slug with a free-form body. Forwards `X-Payment` if supplied. |
| `keeperhub_get_openapi` | Fetch the full OpenAPI 3.1 spec for the public API. |
| `keeperhub_list_org_workflows` | List workflows scoped to your organization (`GET /api/workflows`). |
| `keeperhub_list_integrations` | List wallet integrations attached to your org. |

### Auto-generated per-workflow tools

For every workflow returned by `GET /api/mcp/workflows`, KeeperKit creates a
typed tool whose:

* **name** is `keeperhub_<slug-as-ident>` (e.g. `keeperhub_aave_v3_health_check`)
* **JSON schema** is copied verbatim from the workflow's `inputSchema`
* **description** includes the workflow type (`read` / `write`), price, and chain
* **dispatch** is a closure that calls `client.call_workflow(slug, body)` and
  routes 402 errors through `safe_dispatch()` so the agent gets a clean
  `{ok: false, error: "payment_required", x402: {...}}` response.

This means the agent's tool surface follows the catalogue automatically —
add a new workflow on KeeperHub and your agent picks it up on next
restart.

---

## Handling paid workflows (x402)

KeeperHub bills paid workflows via [x402](https://x402.org): the server
returns `HTTP 402` with a base64-encoded payment descriptor in the
`x-payment-requirements` header. KeeperKit decodes it for you:

```python
from keeperkit import KeeperHubClient
from keeperkit.exceptions import KeeperHubPaymentRequired

client = KeeperHubClient.from_env()
try:
    client.call_workflow("aave-v3-health-check", {"address": "0x..."})
except KeeperHubPaymentRequired as exc:
    # exc.x402 is the decoded descriptor
    print("amount:", exc.amount_usdc, "atomic USDC")
    print("network:", exc.x402["accepts"][0]["network"])
    print("payTo:", exc.x402["accepts"][0]["payTo"])
    # → settle via your x402 client (agentcash, openclaw, custom signer)
    # → then replay with X-Payment header:
    client.call_workflow("aave-v3-health-check", {"address": "0x..."},
                         x_payment="<base64 settlement token>")
```

When the agent calls a paid tool, `safe_dispatch` converts the exception
into a structured response so the LLM can reason about it (e.g. "this is
$0.01 — pay or skip?") rather than crash.

---

## The mock client

```python
from keeperkit import MockKeeperHubClient
from keeperkit.tools.langchain import build_langchain_tools

client = MockKeeperHubClient()                # zero credentials needed
tools  = build_langchain_tools(client)
```

The mock matches the real client's surface 1:1: catalogue, OpenAPI,
`call_workflow` with deterministic `executionId`, full 402 flow, org
endpoints. Every framework adapter accepts it — so you can write your demo
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

* **Dashboard** at `/` — backend / LLM / tool count badges, live agent box,
  per-tool dispatch panels.
* **`POST /api/agent/run`** — LangChain ReAct agent over the full catalogue.
  Auto-picks OpenAI, Anthropic, Google Gemini, Groq, DeepSeek, OpenRouter,
  Mistral, Together, or Ollama based on which API key is set; falls back
  to a deterministic heuristic when no LLM key is configured.
* **`POST /api/tools/{name}`** — one-shot dispatch to any KeeperKit tool
  (static or per-workflow).
* **`POST /api/tools/_refresh`** — re-discover the workflow catalogue
  without restarting (handy after publishing a new workflow on KeeperHub).
* **`GET /api/elizaos/plugin.json`** — live ElizaOS plugin descriptor that
  includes one action per discoverable workflow.
* **`POST /keeperkit/dispatch`** — bridge endpoint for the ElizaOS plugin.
* **`/docs`** — full OpenAPI spec.

Live demo (mock + heuristic, no LLM key required):
**<http://178.104.45.97:8420>**.

---

## Configuration

### Getting a KeeperHub API key

1. Sign up / log in at <https://keeperhub.com>.
2. Open or create an **Organization** (top-right menu — *Personal* keys cannot
   call workflows).
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

### All env vars

| Env var | Default | What it does |
|---|---|---|
| `KEEPERHUB_API_KEY` | — | `kh_…` org key. Without it, the demo runs in mock mode. |
| `KEEPERHUB_BASE_URL` | `https://app.keeperhub.com/api` | Override for self-hosted KeeperHub. |
| `KEEPERKIT_MODE` | `real` | Set to `mock` to force the in-memory backend. |
| `KEEPERKIT_LLM_PROVIDER` | auto | Pin a provider (`openai`, `anthropic`, `google`, `groq`, `deepseek`, `openrouter`, `mistral`, `together`, `ollama`). |
| `KEEPERKIT_LLM_MODEL` | provider-specific | Override the chat model for the active provider. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | — | Standard OpenAI knobs. `OPENAI_BASE_URL` lets you point at LM Studio / vLLM / LiteLLM / Azure OpenAI proxies. |
| `KEEPERKIT_HOST` | `0.0.0.0` | Bind host for the demo server. |
| `KEEPERKIT_PORT` | `8000` | Bind port for the demo server. |

---

## Development

```bash
pip install -e ".[langchain,crewai,server,dev]"
pytest -q                                # mock + langchain + REST + elizaos
ruff check src tests
```

The test suite uses [respx](https://github.com/lundberg/respx) to fake the
KeeperHub REST API so you can run it offline. Mock-backed integration
tests live in `tests/test_mock.py`. Captured real-API snapshots in
`tests/fixtures/` keep the mock honest.

---

## How this maps to KeeperHub's hackathon prize

This project targets the [KeeperHub Best Use prize](https://ethglobal.com/events/openagents/prizes/keeperhub)
on **both** focus areas:

* **Focus area 1 — Innovative Use:** the demo server's heuristic + ReAct
  agent shows KeeperHub turning into the execution backbone of a generic
  agent framework, with full x402 payment-required handling so paid
  workflows are reasoned about instead of crashing.
* **Focus area 2 — Integration:** ready-to-use plugin/SDK integrations for
  three of the active builder communities listed in the prize description
  (LangChain, CrewAI, ElizaOS) — all sharing one auto-generated tool
  catalogue. Plus the [Builder Feedback Bounty](FEEDBACK.md) submission
  with concrete reproducible findings from a real integration.

---

## Repo layout

```
keeperkit/
├── src/keeperkit/
│   ├── client.py            # sync + async REST client + x402 decoding
│   ├── mock.py              # in-memory backend with full 402 flow
│   ├── exceptions.py        # KeeperHubAPIError + KeeperHubPaymentRequired
│   ├── tools/
│   │   ├── _common.py       # ToolSpec + safe_dispatch + auto-generation
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
