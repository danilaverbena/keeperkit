# KeeperKit — submission narrative

> Drop-in plugin that turns the entire **KeeperHub workflow catalogue** into typed tools for **LangChain, CrewAI, and ElizaOS** agents — with built-in `x402` payment handling, auto-discovery, and a live demo.

* **Repo:** <https://github.com/danilaverbena/keeperkit>
* **Live demo:** <http://178.104.45.97:8420/>
* **License:** MIT
* **Languages:** Python 3.10+ (core SDK), TypeScript-friendly JSON descriptor (ElizaOS)

---

## Short pitch (≤ 280 chars)

KeeperKit is the missing SDK between AI agent frameworks and KeeperHub.
One import → your LangChain / CrewAI / ElizaOS agent gets typed tools
for every KeeperHub workflow, native `x402` payment handling, and
catalog-aware tool generation that updates itself.

---

## What does it do?

KeeperKit is a Python plugin that takes the **public KeeperHub workflow
catalogue** (`GET /api/mcp/workflows`) and exposes it to AI agent
frameworks as a typed, framework-native tool catalogue:

* **LangChain** — `build_langchain_tools(client)` returns ready-to-use `StructuredTool` instances.
* **CrewAI** — `build_crewai_tools(client)` returns `BaseTool` instances.
* **ElizaOS** — `write_elizaos_plugin(path, client=…)` writes a JSON plugin descriptor that the character file imports.

A single shared `ToolSpec` definition feeds all three adapters, so
naming, schemas, and behaviour stay identical across frameworks.

A FastAPI demo server (`python -m keeperkit.server`) wires this all up
into an interactive dashboard with a LangChain ReAct agent, direct
per-tool dispatch, and an `/api/elizaos/plugin.json` endpoint that
returns the live descriptor.

---

## What pain points does it solve?

KeeperHub already exposes a polished public REST + MCP layer. The
friction it doesn't solve, KeeperKit does:

1. **No first-party agent SDK.** Every team integrating KeeperHub
   writes its own LangChain/CrewAI/Eliza wrappers, with the usual
   drift in naming, error mapping, and retry policy.
2. **Tool catalogues drift behind the workflow catalogue.** If you
   hardcode tools, every new KeeperHub workflow means a code change.
   KeeperKit **auto-generates one tool per workflow** from
   `inputSchema` at build time — your agent picks up new workflows on
   the next restart, no code change needed.
3. **`HTTP 402 Payment Required` is silent.** Paid workflows return an
   empty `{}` body and stash a base64-encoded x402 descriptor in the
   `x-payment-requirements` header. A naive HTTP client sees nothing
   useful and crashes. KeeperKit decodes the header, raises
   `KeeperHubPaymentRequired` with `.x402` and `.amount_usdc`, and the
   tool's structured response (`{"ok": false, "error": "payment_required",
   "x402": {...}, "amount_usdc": "10000"}`) is something an LLM can
   *reason about* — pay, skip, or escalate.
4. **Paywall blocks local development.** Sign-up + API key + USDC for
   x402 = an hour you don't have during a hackathon. KeeperKit's
   `MockKeeperHubClient` ships a representative free + paid workflow
   catalogue with the **full 402 / X-Payment retry flow** in memory,
   so your demo runs offline, on a plane, on CI.
5. **LLM-provider lock-in.** Most agent demos pin OpenAI. KeeperKit
   detects whichever of **9 providers** has a key in the environment
   (Anthropic → Google → Groq → DeepSeek → OpenRouter → Mistral →
   Together → Ollama → OpenAI) and instantiates the right LangChain
   chat model — Groq's free Llama 3.3 70B runs the live demo today.

---

## What makes it unique?

* **Catalogue-tracking tool surface.** Most agent SDKs hardcode their
  toolset. KeeperKit's tool surface is a **live function of
  KeeperHub's public catalogue** — `build_workflow_tools(client)`
  reads `/api/mcp/workflows` and emits one typed `ToolSpec` per
  workflow, copying its `inputSchema` verbatim. No drift. No `__init__`
  rewrites when KeeperHub publishes a new workflow.
* **x402 as a first-class agent concern.** This is the only agent
  toolkit we know of that decodes the x402 payment-required descriptor
  and exposes it to the LLM as a *structured tool result*, not as a
  Python exception. The agent reads "this is $0.01 USDC on Base" and
  decides what to do, instead of crashing.
* **One catalogue, three frameworks, no drift.** Every tool is defined
  exactly once. LangChain, CrewAI, and ElizaOS adapters are 50-line
  files that consume the same `ToolSpec` set. Names, descriptions, and
  parameter shapes are guaranteed identical across frameworks — debug
  a prompt with LangChain, ship it with CrewAI.
* **Submitted Builder Feedback.** Alongside the SDK, we shipped a
  detailed [`FEEDBACK.md`](FEEDBACK.md) targeting the $250 Builder
  Feedback Bounty: 8 reproducible friction points, 6 feature requests,
  curl-level reproducers, and a TL;DR for the KeeperHub PMs. This is
  the kind of feedback an integration partner would actually act on.

---

## Technologies

| Layer | Stack |
|---|---|
| Core SDK | Python 3.10+, `httpx` (sync + async), `pydantic`, `anyio` |
| Demo server | FastAPI + Uvicorn, Jinja2 templates, vanilla JS dashboard |
| Agent runtime | LangChain + LangGraph (ReAct prebuilt), heuristic fallback |
| Framework adapters | LangChain `StructuredTool`, CrewAI `BaseTool`, ElizaOS plugin descriptor (JSON) |
| LLM auto-detection | 9 providers via `langchain-{openai,anthropic,google-genai,groq,mistralai}` etc. |
| Testing | `pytest` + `respx` (HTTP fakes); 31 offline tests, GitHub Actions on Python 3.10 / 3.11 / 3.12 |
| Deployment | systemd unit + Nginx-aware install script; live on `178.104.45.97:8420` |
| Protocols | KeeperHub public REST API (`/api/mcp/workflows/{slug}/call`), `x402` (HTTP 402 → base64 descriptor → settlement → retry with `X-Payment`) |

---

## Demo flow (90 seconds)

1. Open <http://178.104.45.97:8420/> — backend badge says `mode: real`,
   LLM badge says `groq`, tool count badge says `tools: 23`.
2. Type into the agent box: *"Call the aave-v3-health-check workflow on
   0x9c8f005ab27adb94f3d49020a15722db2fcd9f27 and explain what
   KeeperHub returned."*
3. The agent (LangChain ReAct over Llama 3.3 70B):
   1. Lists the catalogue,
   2. Picks `aave-v3-health-check`,
   3. Receives `HTTP 402 payment_required`,
   4. Reads the decoded x402 descriptor,
   5. Explains in natural language: *"KeeperHub returned a
      payment_required error. The x402 descriptor specifies 10,000
      atomic USDC on Base, payable to 0x650a09bc…. To proceed, settle
      with your x402 client and replay with the X-Payment header."*
4. The same prompt works against the `MockKeeperHubClient` with no
   credentials at all — useful for offline judges.

---

## Hackathon prize fit

Targeting the [KeeperHub Best Use prize](https://ethglobal.com/events/openagents/prizes/keeperhub)
on **both** focus areas:

* **Focus 1 — Innovative Use.** End-to-end agent that reasons about
  payment-required errors via the structured x402 descriptor instead
  of crashing. A measurable behavioural improvement over what every
  current KeeperHub demo does.
* **Focus 2 — Integration.** Production-grade SDK + adapter for three
  of the agent communities mentioned in the prize description
  (LangChain, CrewAI, ElizaOS), shared catalogue, hosted live demo,
  comprehensive test suite, deploy script.

Plus the **$250 Builder Feedback Bounty** via [`FEEDBACK.md`](FEEDBACK.md).

---

## What's next

* **First-class x402 settlement helper.** Today we surface the
  descriptor to the agent; next iteration ships a tiny Python helper
  that wraps "decode → settle on Base → replay with X-Payment" with
  pluggable signers (agentcash, openclaw, custom).
* **Webhook-driven catalogue refresh.** Right now we re-discover the
  catalogue on `_refresh` or restart. With a `workflow.published`
  webhook from KeeperHub, the agent's tool surface would update in
  real time.
* **CrewAI `Process` template + ElizaOS character template.** A
  one-command `keeperkit init crew` / `keeperkit init eliza` that
  emits a working agent skeleton on top of the catalogue.
