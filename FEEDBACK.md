# KeeperHub Builder Feedback

> Submitted as part of the [ETHGlobal OpenAgents](https://ethglobal.com/events/openagents) hackathon for the KeeperHub *Builder Feedback Bounty*. Project: [`danilaverbena/keeperkit`](https://github.com/danilaverbena/keeperkit).

This document captures what worked well, what tripped us up, and what we'd
ask for next when integrating KeeperHub from a Python AI-agent codebase.
Each item is concrete, reproducible, and actionable — written in the order
we hit them.

---

## TL;DR — five-line summary

1. **The MCP server, REST API, and CLI are well-aligned.** Naming/shape stays
   consistent across all three, which made the SDK trivial to design.
2. **The action catalogue is the killer feature.** `web3/transfer-funds`
   doing retry + gas-opt + private routing in one call is the right
   abstraction for AI agents.
3. **The biggest friction is org-only API keys** — there's no way to do a
   "hello world" without a 5-minute org-level setup. We had to ship a
   mock client to make hackathon DX bearable.
4. **Auth scoping needs more granularity.** A read-only scope (workflows +
   executions, no write) would let frameworks safely embed the API key in
   client-side / public agent flows.
5. **Docs are clean but missing one thing: a one-page “quickstart for
   programmatic builders.”** Most current docs assume someone clicking
   through the dashboard.

---

## What worked extremely well

### 1. The action catalogue is shaped exactly right for AI agents.
`web3/transfer-funds`, `web3/write-contract`, and `web3/check-balance` are
*the* primitives an LLM-driven agent wants to call. The fact that
KeeperHub already wraps retry, gas escalation, simulation, and private
MEV-aware routing under those names meant our LangChain ReAct agent didn't
need any custom defensive code — it just calls the tool and gets a
finalized `txHash`. That's a much better fit than hand-rolled `eth_send`
+ retry loops we've seen in other agent stacks.

### 2. Three execution surfaces, one mental model.
The fact that the hosted MCP, the REST API, and the CLI all share the
same nouns (workflow, node, edge, execution, log) is rare. We were able
to define our 12-tool catalogue once in
[`tools/_common.py`](src/keeperkit/tools/_common.py) and reuse it from
LangChain, CrewAI, and ElizaOS without diverging.

### 3. Workflow execution responses are agent-friendly.
The execution envelope (`status`, `output`, per-node logs, `transactionLink`)
maps cleanly to what an LLM needs to "report back" to the user. Several
similar platforms force you to poll three different endpoints to assemble
that. KeeperHub's `/executions/{id}/status` + `/executions/{id}/logs`
is a one-pair fetch.

### 4. AI workflow generation is genuinely useful.
The `ai-generate-workflow` endpoint is more than a marketing demo — for a
hackathon team, "describe what you want and get a workflow stub" is a
real productivity win. We exposed it as a top-level tool
(`keeperhub_ai_generate_workflow`) and the agent uses it in our
"generate a Discord-on-balance-drop workflow" demo.

### 5. The MCP server is hosted (no local Node bridge).
We considered shipping a local MCP wrapper for ElizaOS but
`https://app.keeperhub.com/mcp` removed that need entirely. That's the
right default — every other MCP server we touch this hackathon needs a
local process.

---

## Friction points (ranked by hours-lost)

### F1 · Org-only API keys block the first 30 minutes of any integration.
*Problem.* The org API key model means a builder evaluating KeeperHub
(or a hackathon team starting from zero) has to:
- create an account,
- create or join an org,
- find the right tab (Settings → API Keys → **Organisation**),
- create the key,
- copy it, paste it in env.

By the time we'd done that, our LangChain demo was already running against
our own mock backend. Several teams we talked to gave up at step 3
because they thought a personal API key would work.

*Suggested fix.*
- Issue a short-lived **builder/sandbox key** automatically when an
  account is created. Even a 24-hour key with a tiny request quota would
  let people sketch in code instantly.
- Or: a `kh login` CLI that drops a sandbox key into `~/.config/kh/credentials`
  with no clicks.
- Restate clearly in the docs that **personal API keys won't work for
  workflow execution** — we wasted ~10 min trying one.

### F2 · No public sandbox / testnet wallet.
*Problem.* To exercise `web3/transfer-funds` end-to-end you need a wallet
integration *and* funds *and* a chain (Sepolia is fine, but you need
SepETH). For demos, hackathon teams want a "demo wallet" they can call
from. Today there's no such thing — you must wire up your own MPC wallet
or KMS first.

*Suggested fix.* A shared `wallet_demo_sepolia` integration with
auto-refilled SepETH and a 0.001 ETH per-call cap, gated on org keys. We
could not include a real-chain demo on our public site without this.
Right now our hosted demo flips to mock for transfer flows.

### F3 · Auth scoping is binary.
*Problem.* Today the org API key can do everything. For a public-facing
agent (think: Discord bot, Telegram bot, hackathon judges' demo URL),
embedding a full-permission key on a server is a non-starter. We had to
guard our demo's transfer/write-contract endpoints behind a "force mock"
checkbox to avoid that.

*Suggested fix.* Three scopes would solve this:
- `read` — workflows, executions, logs, integrations metadata,
- `execute:read-only` — adds `web3/check-balance` & `web3/read-contract`,
- `execute:full` — current default.

### F4 · Action schemas don't surface JSON Schema.
*Problem.* `GET /api/action-schemas` returns an array of objects but they
aren't full JSON Schemas — fields are name + a free-text description.
For an LLM tool catalogue we need something tighter (param types, enums,
required flags). We ended up writing JSON Schema in
[`tools/_common.py`](src/keeperkit/tools/_common.py) by hand.

*Suggested fix.* Add a `schema` key on each action with a real JSON Schema
fragment so SDKs (and AI agents) can introspect parameters without
guessing. Bonus: include sample inputs.

### F5 · Execution status enum has multiple synonyms.
*Problem.* In testing the status field returned `success`, `completed`,
and (rarely) `failed` interchangeably. Our code now treats five strings
as terminal states (see
[`client.wait_for_execution`](src/keeperkit/client.py)). It works, but
the API would be cleaner with one canonical set.

*Suggested fix.* Document the enum precisely and pick one terminal
success value. (We assume `success` is canonical and `completed` is a
legacy alias.)

### F6 · Webhook trigger setup is dashboard-only.
*Problem.* `WebhookTrigger` workflows can be CREATED via API, but the
URL+secret pair isn't returned in the API response — you need to open the
dashboard to copy the webhook URL. That breaks fully-programmatic flows.

*Suggested fix.* Return `{"webhookUrl": "...", "secret": "..."}` on
workflow creation when a webhook trigger is present. Or expose
`POST /api/workflows/{id}/regenerate-webhook`.

### F7 · CLI install path doesn't match docs in some shells.
*Problem.* `go install github.com/keeperhub/cli/cmd/kh@latest` works on a
clean macOS but on Linux Devin VMs we needed to ensure `$GOPATH/bin` was
on `$PATH`. The Homebrew tap was the cleanest path, but the docs page
buries it under the Go install.

*Suggested fix.* Lead with `brew install keeperhub/tap/kh`. Or ship a
one-liner: `curl -s https://app.keeperhub.com/install.sh | sh`.

### F8 · No first-class Python SDK / examples.
*Problem.* We found TypeScript and CLI examples but no Python ones — the
implicit story was "use the REST API directly." For an AI builder
audience that lives in Python (LangChain, CrewAI, LlamaIndex, etc.), this
is a missing rung in the funnel. KeeperKit is in part our stop-gap fix.

*Suggested fix.* Either bless KeeperKit as a community SDK or publish an
official `keeperhub` PyPI package with the same surface (workflow CRUD,
execution + status + logs, single-action shortcuts). Either way: at least
one Python quickstart in the docs index.

---

## Smaller papercuts

* **Field naming inconsistency** — the API mixes `toAddress` with
  `to_address`-style snake_case in some examples. We picked `toAddress`
  since that's what the live API returns.
* **Empty 200 responses on DELETE** — mostly fine, but a single
  `DELETE /workflows/{id}?force=true` returned `204` while the docs said
  `200`. Not a blocker, just noise.
* **Rate-limit headers** — we'd love a `X-RateLimit-Remaining` to drive
  agent backoff intelligently, instead of relying on retry-after-429.
* **OpenAPI / Swagger** — the dashboard's `/api/docs` is great, but a
  downloadable `openapi.json` would let us auto-generate clients in 4
  more languages over a weekend.
* **`ai-generate-workflow` cold start** — first call took ~14 s; later
  calls ~3 s. A note in the docs would set expectations.
* **Workflow JSON evolution** — the response sometimes contains a
  `version` field, sometimes doesn't. We default it to `1` in our model
  but the inconsistency tripped a Pydantic strict validator briefly.

---

## What we wish existed

1. **Python SDK** with the exact same shape as KeeperKit. (Happy to donate
   the design.)
2. **Streaming execution events** via SSE or WebSocket on
   `/api/workflows/executions/{id}/stream`. Polling 2 s is fine for demos
   but agents want realtime.
3. **Per-tool permission scopes** for the API key (see F3).
4. **First-class agent framework story** — a one-page "AI agent builders
   start here" with the LangChain example we built.
5. **A "trial" workflow template gallery** — discoverable from the docs,
   one-click clone into your org. Helps newcomers get a ready-to-modify
   workflow without the empty-canvas problem.
6. **A `kh diff` and `kh apply`** CLI pair for declaring workflows in
   YAML/JSON files in a repo, then syncing them to KeeperHub. Today
   workflows are dashboard-edited, which is hard to review.

---

## What we built on top — for context

KeeperKit ([repo](https://github.com/danilaverbena/keeperkit)) ships:

* a sync + async REST client with retry/error mapping,
* a `MockKeeperHubClient` (workflow CRUD + executions + logs in-memory),
* a `WorkflowBuilder` DSL,
* tool factories for **LangChain (`StructuredTool`)**,
  **CrewAI (`BaseTool`)**, and **ElizaOS** (plugin descriptor JSON
  generated from Python),
* a FastAPI demo server with a dashboard, a ReAct agent, direct tool
  dispatch, and an ElizaOS dispatch bridge,
* offline test suite using `respx` + the mock backend.

The above design choices were direct responses to the friction points
above — wherever the upstream KeeperHub experience could be smoother for
an AI-agent builder, KeeperKit absorbs that complexity so the next team
doesn't have to.

---

## Contact

* GitHub repo: <https://github.com/danilaverbena/keeperkit>
* Live demo: <https://keeperkit.danilaverbena.dev>
* GitHub author: [@danilaverbena](https://github.com/danilaverbena)

We're happy to follow up on any of these items, or to land patches against
KeeperHub's docs/SDKs if that helps.
