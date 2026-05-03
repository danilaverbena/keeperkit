# KeeperKit ↔ KeeperHub — Builder Feedback

> Submitted to the **KeeperHub Builder Feedback Bounty** (ETHGlobal
> OpenAgents). Author: KeeperKit team. Built against the KeeperHub public
> API at `https://app.keeperhub.com/api`, organisation API key
> (`kh_…`), May 2026. Findings come from a real end-to-end integration
> shipped at <https://github.com/danilaverbena/keeperkit> and live on
> <http://178.104.45.97:8420>.

This file is intentionally specific. Each item is something we hit while
shipping, with a screenshot-worthy reproducer where possible, and a
concrete suggestion. We hope it's useful — KeeperHub is genuinely the
nicest "execution layer for agents" we've integrated against this
hackathon, so this is feedback in the spirit of "we want to ship more
on it".

---

## TL;DR for KeeperHub PMs

* **Marketing pages and the public REST surface drift.** The marketing
  copy describes a CRUD-style execution platform (`POST /api/execute`,
  workflow CRUD over REST), but the real public API is a **catalogue of
  callable workflows** under `/api/mcp/workflows/{slug}/call` with x402
  billing. We rebuilt our SDK once when we discovered this. A 1-page
  "API at a glance" doc would have saved us ~1 hour.
* **The 402 flow is great, but the failure mode is silent.** When a
  paid workflow gets called without `X-Payment`, we get HTTP 402 with a
  base64-encoded descriptor in `x-payment-requirements`. There is no
  human-readable JSON in the body for non-MCP clients. We had to base64-
  decode and inspect the header before our agent could reason about it.
  Adding `Content-Type: application/json` with the same descriptor in the
  body would let plain HTTP clients render a useful error without the
  base64 step.
* **`inputSchema` quality varies a lot across workflows.** Some are crisp
  JSON Schema; others have `additionalProperties: false` but no
  `required`, or use plain English in `description` for things that
  should be enums. Tightening these would let LLMs auto-fill arguments
  more reliably.
* **No way to discover supported chains for a write workflow before
  calling it.** We can call `keeperhub_list_workflows` and see
  `category` / `chain` for some entries but the field is inconsistent.
* **The `kh_…` key works for both the MCP server and the REST API**,
  which is great. But the docs we found never said this out loud — we
  guessed and tried.

The rest of this doc walks through specific friction points and feature
requests with reproducers.

---

## 1 · Friction points hit while integrating

### 1.1 Marketing surface ≠ public API surface

* **Where**: <https://keeperhub.com> landing page + docs.
* **What we expected (from marketing)**:
  - `POST /api/workflows` → create a workflow programmatically
  - `POST /api/execute` → run an arbitrary action (transfer, contract write)
  - `GET /api/action-schemas` → discover available actions
* **What's actually there (from `GET /api/openapi`)**:
  - `GET /api/mcp/workflows` → list a curated **catalogue** of callable workflows
  - `POST /api/mcp/workflows/{slug}/call` → invoke a specific catalogued workflow
  - `GET /api/workflows` → org-scoped workflow list (different shape!)
  - `GET /api/integrations` → wallet integrations
  - No `POST /api/execute`, no `POST /api/workflows`, no `/api/action-schemas` (returns 404).
* **Impact**: We shipped an SDK against the marketing-implied API, then
  rebuilt it after seeing the real OpenAPI. ~1 hour of rework + a fully
  rewritten test suite.
* **Suggestion**: Either (a) align marketing to "catalogue of callable
  workflows" framing or (b) ship a minimal public CRUD that matches the
  marketing claims. We strongly prefer (a) — the catalogue model is
  cleaner and more agent-friendly. A single "for builders, your API is
  this" page on the marketing site (linking to `/api/openapi`) would
  have made this obvious.

### 1.2 x402 payment descriptor lives only in a header

When you call a paid workflow without `X-Payment`:

```
HTTP/1.1 402 Payment Required
www-authenticate: Payment id="…", x-payment="<descriptor base64>"
x-payment-requirements: <descriptor base64>
content-type: application/json
content-length: 2

{}
```

* **Friction**: A naive HTTP client logging the response body sees `{}`
  and thinks "empty server error". You have to know to look at the
  `x-payment-requirements` header, base64-decode it, and parse JSON.
* **Suggestion**: Mirror the descriptor into the JSON body too. Most
  agent frameworks log bodies, not headers. KeeperKit handles this in
  `_decode_x402_header`, but every other integrator will also have to
  write that code.

### 1.3 No `id` / `slug` distinction in catalogue listing

Workflows have both an `id` (`5667q8uw1rq4y723t548n`) and a `listedSlug`
(`defi-position-aggregator-ethereum`). Calling endpoints uses the slug,
but lots of fields in the catalogue refer to the id. A note like "you
will only ever pass `listedSlug` to `/call`; `id` is internal" would
save a confused first request.

### 1.4 `inputSchema` is sometimes too loose for an LLM

Examples we hit:
* `{"type": "object", "properties": {}, "additionalProperties": false}` —
  fine, agent calls with `{}`.
* `{"type": "object", "required": ["wallet"], "properties": {"wallet": {"type": "string", "description": "Wallet address (0x...) to aggregate DeFi positions for. Must be a valid Ethereum-compatible EVM address."}}}` —
  great, the description is enough for the LLM to fill in a checksummed
  address.
* But several `write` workflows have schemas like
  `{"type": "object"}` with no `required` / `properties` — the LLM can't
  guess. We had to special-case these with prompt-time docs.
* **Suggestion**: A schema-quality lint inside the KeeperHub Studio
  before publishing a workflow. Even just "your inputSchema has no
  `description` on top-level properties" as a warning would help.

### 1.5 Discoverability of chain support per workflow

For write workflows we couldn't reliably tell from the catalogue which
chain they target without reading the workflow body. The existing
`workflowType` field is good (`read` / `write`); please add a
top-level `chain` (or `chains: [...]`) field to every catalogue entry.

### 1.6 Listing endpoint pagination

`GET /api/mcp/workflows` returns the full catalogue in one shot today.
For a few-dozen-workflow catalogue this is fine, but at 200+ workflows
it'll start to be expensive. Adding `?limit=&cursor=` (cursor pagination
is much friendlier for agents than offset) would future-proof this.

### 1.7 No "describe schema for slug X" lightweight endpoint

If we already know the slug (e.g. agent learned it from a prior list
call) and just want the input schema, we currently have to fetch the
**entire** OpenAPI spec or list the **entire** catalogue. A
`GET /api/mcp/workflows/{slug}/schema` (just the inputSchema JSON) would
let us hot-reload tool definitions cheaply.

### 1.8 Local development needs a mock or sandbox

We built `MockKeeperHubClient` ourselves so we could run tests offline,
but a first-party "sandbox" that mirrors the catalogue and returns
plausible synthetic outputs would be much more useful — particularly
for paid workflows where you don't want to burn USDC on a CI test run.
Even a `?dryRun=true` query parameter that returns the canned `output`
shape from the OpenAPI spec would be transformative for builders.

---

## 2 · Feature requests

### 2.1 Per-workflow auth scoping

Right now an organisation API key can call **any** workflow in the org.
For multi-agent systems you sometimes want "this agent can only call
read-only workflows" or "this agent can only call workflows under the
`/payments/*` namespace". Scoped keys (e.g. `kh_workflow_<slug>_…`) or a
`Subset` policy parameter on key creation would let us hand a key to a
sub-agent without giving it the keys to the kingdom.

### 2.2 Streaming execution updates

`POST /call` returns a final `{executionId, status, output}` payload. For
long-running workflows (multi-tx batches) it would be useful to either
stream Server-Sent Events from the same endpoint or expose a
`GET /api/mcp/workflows/{slug}/executions/{id}/events`. Otherwise we
have to poll, and the poll endpoint isn't documented.

### 2.3 First-class x402 retry helper

x402 settlement clients (agentcash, openclaw, custom signers) all need
the same dance: receive 402, decode descriptor, settle on-chain, retry
with `X-Payment`. KeeperHub could ship a tiny helper SDK
(`keeperhub-x402-py` / `keeperhub-x402-ts`) that wraps the retry. Today
every integrator implements this loop themselves.

### 2.4 OpenAPI spec includes pricing fields per workflow

The catalogue listing has `priceUsdcPerCall`, but the OpenAPI spec for
each `POST /call` endpoint doesn't include this in the spec metadata.
Adding `x-price-usdc` (or even just embedding it into the description)
would let LLMs reason about cost before calling.

### 2.5 ElizaOS / LangChain / CrewAI plugin templates from KeeperHub itself

The reason KeeperKit exists is that there was no first-party adapter for
these frameworks. We're happy to keep KeeperKit alive, but a "downstream
SDK" badge on the marketing site or a quickstart link from the docs
would help builders find it (or build their own).

### 2.6 Webhook on workflow publish

So we can rebuild our agent's tool catalogue automatically when a new
workflow is published. Today `POST /api/tools/_refresh` on our demo
server has to be triggered manually.

---

## 3 · What worked really well

To balance the friction list:

* **The OpenAPI spec is excellent and honest.** Once we found it
  (`GET /api/openapi`), it described every endpoint correctly — schemas
  matched real responses, discriminators were typed. This is rarer than
  it should be.
* **`helloworld` is a great smoke test.** Free, no inputs, predictable
  output. Every public API should have one.
* **Error responses include actionable messages.** Not just "Bad
  Request" — we got "address must be a valid 0x-prefixed hex string,
  20 bytes long" which is exactly what an agent needs.
* **The MCP server is a thoughtful primitive.** We don't lean on it in
  KeeperKit (we go straight to REST so we can layer our own retry and
  framework adapters), but the existence of an MCP-shaped surface is the
  right call.
* **Onboarding is fast.** Sign up → org → API key → first call took us
  ~3 minutes. Most "agent-platform" sponsors at this hackathon take 15+.

---

## 4 · Reproducers

All reproducers ran against `https://app.keeperhub.com/api` with a
real `kh_…` org key, May 1 2026.

```bash
# 1.1 — marketing-implied endpoints don't exist
curl -fsS -H "Authorization: Bearer $KEEPERHUB_API_KEY" \
  https://app.keeperhub.com/api/action-schemas
# → curl: (22) The requested URL returned error: 404

# 1.2 — paid workflow returns 402 with body `{}` and descriptor in header
curl -isS -X POST -H "Authorization: Bearer $KEEPERHUB_API_KEY" \
  -H "content-type: application/json" \
  -d '{"address":"0x000000000000000000000000000000000000dEaD"}' \
  https://app.keeperhub.com/api/mcp/workflows/aave-v3-health-check/call \
  | sed -n '1,/^$/p;$p'
# → HTTP/1.1 402 Payment Required
# → x-payment-requirements: <base64>
# → www-authenticate: Payment id="…"
# → {}

# 1.5 — `helloworld` works first try, no auth needed beyond the key
curl -fsS -X POST -H "Authorization: Bearer $KEEPERHUB_API_KEY" \
  -H "content-type: application/json" -d '{}' \
  https://app.keeperhub.com/api/mcp/workflows/helloworld/call
# → {"executionId":"…","status":"success",
#    "output":{"result":{"message":"Hello World!"},"success":true}}
```

---

## 5 · About KeeperKit

We built KeeperKit to give the LangChain / CrewAI / ElizaOS communities
a one-import experience for KeeperHub. The full code (Apache-2.0 // MIT)
and a live demo are at:

* **GitHub**: <https://github.com/danilaverbena/keeperkit>
* **Live demo**: <http://178.104.45.97:8420> (mock + heuristic mode by
  default; add a `KEEPERHUB_API_KEY` and any LLM key in `.env` to run
  against the real API).
* **Tool catalogue**: 5 static tools (discover / call / openapi / org /
  integrations) + one auto-generated tool per discoverable workflow.
* **Tests**: 30 offline tests covering mock + REST + langchain + elizaos.

Thanks to the KeeperHub team for shipping a real, working public API
during a hackathon — it's not a given, and it made this build possible
in a single afternoon. Happy to chat about any of the above on Telegram
or to file PRs against the docs site.
