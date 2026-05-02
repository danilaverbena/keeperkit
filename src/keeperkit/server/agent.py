"""LangChain-powered ReAct agent used by the demo server.

We deliberately use ``langgraph.prebuilt.create_react_agent`` because:

1. It ships in ``langgraph`` (already a transitive dep of ``langchain``) and
   gives us a battle-tested ReAct loop without writing our own state machine.
2. It accepts the exact ``StructuredTool``s built by
   :mod:`keeperkit.tools.langchain` — including the auto-generated per-
   workflow tools.
3. It's async-friendly, so the FastAPI handler can await ``ainvoke`` without
   blocking the event loop.

The model is chosen by :mod:`keeperkit.server.llm` based on which provider
key is present (OpenAI, Anthropic, Google Gemini, Groq, DeepSeek,
OpenRouter, Mistral, Together, Ollama). If no provider can be built we fall
back to a deterministic heuristic agent so the dashboard still works
offline.
"""

from __future__ import annotations

import re
from typing import Any

from keeperkit.server.llm import build_llm, detect_provider
from keeperkit.tools._common import (
    STATIC_TOOL_SPECS,
    build_workflow_tools,
    safe_dispatch,
)

ETH_ADDR = re.compile(r"0x[a-fA-F0-9]{40}")


def _by_name(name: str, specs):
    for s in specs:
        if s.name == name:
            return s
    return None


def _heuristic_agent(client: Any, prompt: str) -> dict[str, Any]:
    """Resolve common prompts to direct KeeperHub tool calls, no LLM needed.

    The heuristic is deliberately small — its job is to keep the demo
    interactive when no LLM key is configured. It will:

    * list / inspect the workflow catalogue
    * call ``helloworld`` (always free, smoke test)
    * call ``aave-v3-health-check`` if the user mentions an address + health
    * call ``defi-position-aggregator-base`` if they mention positions / Base
    * fall back to listing workflows so the user knows what's available
    """
    p = prompt.lower()
    addrs = ETH_ADDR.findall(prompt)

    static = list(STATIC_TOOL_SPECS)
    workflow_specs = build_workflow_tools(client)
    plan: list[dict[str, Any]] = []

    list_spec = _by_name("keeperhub_list_workflows", static)

    final_answer: str

    if "hello" in p or "smoke" in p or "helloworld" in p:
        spec = _by_name("keeperhub_helloworld", workflow_specs)
        if spec is not None:
            res = safe_dispatch(spec, client)
            plan.append({"tool": spec.name, "arguments": {}, "result": res})
            output = (res.get("data") or {}).get("output") or {}
            final_answer = (
                f"Called helloworld → {output.get('result', {}).get('message')}"
            )
        else:
            res = safe_dispatch(list_spec, client)
            plan.append({"tool": list_spec.name, "result": res})
            final_answer = (
                "helloworld not in catalogue. Listed available workflows instead."
            )

    elif any(k in p for k in ["health", "aave", "risk"]) and addrs:
        spec = _by_name("keeperhub_aave_v3_health_check", workflow_specs)
        if spec is not None:
            res = safe_dispatch(spec, client, address=addrs[0])
            plan.append({"tool": spec.name, "arguments": {"address": addrs[0]},
                         "result": res})
            if not res.get("ok") and res.get("error") == "payment_required":
                final_answer = (
                    f"Aave v3 health check is paid (~{res.get('amount_usdc')} "
                    "atomic USDC). Pay via your x402 client and retry with "
                    "the X-Payment header."
                )
            else:
                final_answer = (
                    f"Aave v3 health for {addrs[0]}: {res.get('data')}"
                )
        else:
            final_answer = (
                "aave-v3-health-check not in catalogue here."
            )

    elif any(k in p for k in ["position", "portfolio", "defi"]) and addrs:
        spec = _by_name("keeperhub_defi_position_aggregator_base",
                        workflow_specs)
        if spec is not None:
            res = safe_dispatch(spec, client, wallet=addrs[0])
            plan.append({"tool": spec.name, "arguments": {"wallet": addrs[0]},
                         "result": res})
            final_answer = f"DeFi positions for {addrs[0]} on Base: {res.get('data')}"
        else:
            final_answer = "defi-position-aggregator-base not in catalogue here."

    elif any(k in p for k in ["list", "workflow", "catalogue", "что умеешь"]):
        res = safe_dispatch(list_spec, client)
        plan.append({"tool": list_spec.name, "result": res})
        items = ((res.get("data") or {}).get("items")) or []
        final_answer = (
            f"KeeperHub exposes {len(items)} workflows. Examples: "
            + ", ".join(
                f"`{i.get('listedSlug')}`"
                for i in items[:5]
                if i.get("listedSlug")
            )
            + ("…" if len(items) > 5 else "")
        )

    else:
        res = safe_dispatch(list_spec, client)
        plan.append({"tool": list_spec.name, "result": res})
        items = ((res.get("data") or {}).get("items")) or []
        slugs = [i.get("listedSlug") for i in items if i.get("listedSlug")]
        final_answer = (
            "I'm the heuristic fallback (no LLM key configured). "
            "Set OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY / "
            "GROQ_API_KEY / DEEPSEEK_API_KEY / OPENROUTER_API_KEY / "
            "MISTRAL_API_KEY / TOGETHER_API_KEY (or OLLAMA_BASE_URL) to "
            "enable the LangChain ReAct agent. Meanwhile, try prompts like "
            "'say hello via KeeperHub', 'list KeeperHub workflows', or "
            "'check Aave v3 health for 0x…'. Available slugs: "
            + (", ".join(f"`{s}`" for s in slugs[:8])
               + ("…" if len(slugs) > 8 else "")
               or "(none discoverable from current backend)")
        )

    return {"engine": "heuristic", "final_answer": final_answer, "trace": plan}


async def _langchain_agent(client: Any, prompt: str) -> dict[str, Any]:
    """Full ReAct agent using LangChain + LangGraph."""
    try:
        from langgraph.prebuilt import create_react_agent
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "Install `langgraph` (already in the [server] extras) to use "
            "the LLM-driven agent."
        ) from exc

    from keeperkit.tools.langchain import build_langchain_tools

    resolved = build_llm()
    if resolved is None:
        raise RuntimeError("No LLM provider configured.")
    llm, label = resolved
    tools = build_langchain_tools(client)

    system_prompt = (
        "You are a hands-on onchain operations agent with access to "
        "KeeperHub workflows. Each `keeperhub_*` tool corresponds to a "
        "callable workflow (DeFi reads, write transactions, payments). "
        "Prefer calling these tools over describing what you would do. "
        "If you don't know which workflow to use, call "
        "`keeperhub_list_workflows` first to inspect the catalogue, then "
        "pick the right one and call it directly. If a tool returns "
        "`payment_required`, summarise the x402 descriptor and stop — the "
        "user's x402 client will settle and retry. Always cite the "
        "`executionId` and any onchain link the tool returns."
    )

    agent = create_react_agent(llm, tools, prompt=system_prompt)
    response = await agent.ainvoke({"messages": [("user", prompt)]})

    messages = response.get("messages", [])
    trace = []
    final_answer = ""
    for msg in messages:
        msg_type = getattr(msg, "type", "") or msg.__class__.__name__.lower()
        content = getattr(msg, "content", "")
        tool_calls = getattr(msg, "tool_calls", None) or []
        entry: dict[str, Any] = {"type": msg_type}
        if content:
            entry["content"] = content
        if tool_calls:
            entry["tool_calls"] = [
                {"name": tc.get("name"), "args": tc.get("args")} for tc in tool_calls
            ]
        if msg_type in ("tool",):
            entry["tool_name"] = getattr(msg, "name", None)
        trace.append(entry)
        if msg_type == "ai" and content:
            final_answer = content if isinstance(content, str) else str(content)

    return {"engine": f"langchain:{label}",
            "final_answer": final_answer, "trace": trace}


async def run_agent(client: Any, prompt: str) -> dict[str, Any]:
    """Entry point used by the FastAPI handler.

    Picks the LangChain ReAct agent when any LLM provider is configured,
    otherwise falls back to the LLM-less heuristic so the demo is always
    interactive.
    """
    if detect_provider() is None:
        return _heuristic_agent(client, prompt)
    try:
        return await _langchain_agent(client, prompt)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        fallback = _heuristic_agent(client, prompt)
        fallback["fallback_reason"] = (
            f"LangChain agent failed ({type(exc).__name__}: {exc}); "
            "served heuristic instead."
        )
        return fallback
