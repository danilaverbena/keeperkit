# KeeperKit architecture

## Components

```
                     ┌────────────────────────────────────┐
                     │      KEEPERKIT TOOL CATALOGUE      │
                     │     src/keeperkit/tools/_common    │
                     │  STATIC_TOOL_SPECS (5 always-on)   │
                     │  + build_workflow_tools(client)    │
                     │    auto-generates 1 ToolSpec per   │
                     │    workflow returned by            │
                     │    GET /api/mcp/workflows          │
                     └──┬───────────┬──────────────────┬──┘
                        │           │                  │
              ┌─────────▼──┐  ┌─────▼──────┐    ┌──────▼─────┐
              │ langchain  │  │  crewai    │    │  elizaos   │
              │ adapter    │  │  adapter   │    │  plugin    │
              │ Structured │  │  BaseTool  │    │  json      │
              │ Tool       │  │            │    │  generator │
              └─────────┬──┘  └────────┬───┘    └────────┬───┘
                        │              │                  │
                        ▼              ▼                  ▼
                  ┌─────────────────────────────────────────┐
                  │     KeeperHubClient / Mock              │
                  │     • list_workflows()                  │
                  │     • call_workflow(slug, body, …)      │
                  │     • get_openapi() / list_org_…        │
                  │     • _decode_x402_header()             │
                  └────────────────┬────────────────────────┘
                                   │
            ┌──────────────────────┴──────────────────────┐
            │                                             │
            ▼                                             ▼
  ┌─────────────────────┐                     ┌──────────────────────┐
  │  KeeperHub public   │                     │  In-memory mock      │
  │  REST API           │                     │  (representative     │
  │  app.keeperhub.com  │                     │   catalogue + 402    │
  │  /api               │                     │   payment flow)      │
  └─────────────────────┘                     └──────────────────────┘
```

## Data flow at runtime

1. The agent (LangChain ReAct, CrewAI agent, ElizaOS character) decides
   to invoke a tool, e.g. `keeperhub_aave_v3_health_check`.
2. The framework adapter validates the arguments using the JSON Schema
   declared in `_common.py` (which was copied verbatim from the
   workflow's `inputSchema`) and calls `safe_dispatch(spec, client, ...)`.
3. `safe_dispatch` invokes `spec.dispatch(client, **kwargs)`. For
   per-workflow tools this is a closure over `client.call_workflow(slug,
   body)`.
4. `KeeperHubClient`:
   * adds `Authorization: Bearer kh_…` and (when supplied) `X-Payment`,
   * sends `POST /api/mcp/workflows/{slug}/call`,
   * applies retry/backoff for transient 429/5xx and connection errors,
   * maps status codes to typed exceptions:
     - `401` → `KeeperHubAuthError`
     - `402` → `KeeperHubPaymentRequired` (with `.x402` descriptor)
     - `404` → `KeeperHubNotFoundError`
     - `4xx` → `KeeperHubValidationError`
     - `5xx` → `KeeperHubAPIError`
5. `safe_dispatch` catches each of these and returns a structured dict
   so the LLM doesn't have to handle Python exceptions:
   ```python
   {"ok": True, "data": {...}}
   {"ok": False, "error": "payment_required", "x402": {...}, "amount_usdc": "10000", ...}
   {"ok": False, "error": "KeeperHubAuthError", "status": 401, ...}
   ```
6. KeeperHub itself handles the actual workflow side: simulation,
   reliable execution, payment settlement, audit logs, and emits the
   final `{executionId, status, output}` payload.

## Why a shared catalogue

Defining each tool once means:

* every framework agrees on names, descriptions, and parameter shapes —
  if you debug a prompt with LangChain, the same prompt works with
  CrewAI;
* documentation, the ElizaOS plugin descriptor, and `/api/elizaos/plugin.json`
  stay in lockstep with the runtime;
* adding a new framework is a 50-line file, not a 500-line file.

## Mock vs real client

The mock client (`MockKeeperHubClient`) implements the same surface as
the real one, including:

* a representative `DEFAULT_CATALOGUE` of 5 workflows (free + paid),
* 402 payment-required raising for paid workflows when no `x_payment`
  token is supplied (and acceptance of any `x_payment` for retry),
* deterministic synthetic outputs per workflow slug,
* OpenAPI generation matching real-API shape.

Switching between them is one line. The demo server picks automatically
based on `KEEPERHUB_API_KEY` and exposes a "force mock" toggle in the
dashboard for live demos that should never touch a real chain.

## Extending KeeperKit

The catalogue is auto-generated, so 90% of the time you add no code at
all — KeeperHub publishes a new workflow, you call `_refresh` and your
agent picks it up.

To add a **new static tool** (something that's not a single workflow
call — e.g. a multi-step helper):

1. Append a `ToolSpec` to `STATIC_TOOL_SPECS` in
   `src/keeperkit/tools/_common.py`, with a `dispatch` closure that
   coordinates the calls you need.
2. The LangChain factory, CrewAI factory, and ElizaOS descriptor pick
   it up automatically.
