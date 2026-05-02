# KeeperKit architecture

## Components

```
                     ┌────────────────────────────────────┐
                     │      KEEPERKIT TOOL CATALOGUE      │
                     │     src/keeperkit/tools/_common    │
                     │  one ToolSpec(name, desc, schema)  │
                     │   per KeeperHub operation × 12     │
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
                  │     src/keeperkit/client.py             │
                  │     src/keeperkit/mock.py               │
                  └────────────────┬────────────────────────┘
                                   │
            ┌──────────────────────┴──────────────────────┐
            │                                             │
            ▼                                             ▼
  ┌─────────────────────┐                     ┌──────────────────────┐
  │  KeeperHub REST API │                     │  In-memory mock      │
  │  app.keeperhub.com  │                     │  (tests, demos, no   │
  │                     │                     │   credentials path)  │
  └─────────────────────┘                     └──────────────────────┘
```

## Data flow at runtime

1. The agent (LangChain ReAct, CrewAI agent, ElizaOS character) decides to
   invoke a tool, e.g. `keeperhub_transfer_funds`.
2. The framework adapter validates the arguments using the JSON Schema
   declared in `_common.py` and calls `default_dispatch(client, spec, ...)`.
3. `default_dispatch` looks up the matching method on the client
   (`client.transfer_funds(...)`).
4. `KeeperHubClient`:
   * adds `Authorization: Bearer kh_…`,
   * sends the HTTP request,
   * applies retry/backoff for transient 429/5xx and connection errors,
   * maps status codes to typed exceptions
     (`KeeperHubAuthError`, `KeeperHubNotFoundError`,
     `KeeperHubValidationError`),
   * deserialises the response into a Pydantic model.
5. The result is returned to the agent. The framework adapter wraps it as
   `{"ok": true, "data": ...}` so a downstream LLM doesn't have to parse
   exceptions.
6. KeeperHub itself handles the actual onchain side: simulation, gas
   escalation, MEV-aware private routing, retries on chain reorganisation
   or RPC failover, and emitting per-node logs.

## Why a shared catalogue

Defining each tool once means:

* every framework agrees on names, descriptions, and parameter shapes —
  if you debug a prompt with LangChain, the same prompt is going to work
  with CrewAI;
* documentation and the ElizaOS plugin descriptor stay in lockstep with
  the runtime;
* adding a new framework is a 50-line file, not a 500-line file.

## Mock vs real client

The mock client (`MockKeeperHubClient`) implements the same surface as
the real one, including:

* workflow CRUD,
* execution simulation that returns plausible `txHash`, `transactionLink`,
  per-node durations, and confirmed status,
* AI-generated workflow stubs,
* a default mock wallet integration so write actions don't need extra
  setup.

Switching between them is one line. The demo server picks automatically
based on `KEEPERHUB_API_KEY` and exposes a "force mock" toggle in the
dashboard for live demos that should never touch a real chain.

## Extending KeeperKit

To expose a new KeeperHub operation as an agent tool:

1. Add a method on `KeeperHubClient` (and `MockKeeperHubClient` if you want
   tests/demos to work offline).
2. Append a `ToolSpec` to `KEEPERHUB_TOOL_SPECS` in
   `src/keeperkit/tools/_common.py`.
3. Done — the LangChain factory, CrewAI factory, and ElizaOS descriptor
   pick it up automatically.
