"""LangChain-powered ReAct agent used by the demo server.

We deliberately use ``langgraph.prebuilt.create_react_agent`` because:

1. It ships in ``langgraph`` (already a transitive dep of ``langchain``) and
   gives us a battle-tested ReAct loop without writing our own state machine.
2. It accepts the exact ``StructuredTool``s built by
   :mod:`keeperkit.tools.langchain`.
3. It's async-friendly, so the FastAPI handler can await ``ainvoke`` without
   blocking the event loop.

If the hosting environment doesn't have an OpenAI API key (or another
LangChain-compatible LLM key), we still want the demo dashboard to be
useful, so we expose a deterministic fallback: an LLM-less heuristic agent
that recognizes a few common prompts (balance check, list workflows, transfer
on Sepolia, etc.) and dispatches the appropriate tool directly. This keeps
the demo server functional even without paid LLM credentials.
"""

from __future__ import annotations

import os
import re
from typing import Any

from keeperkit.tools._common import default_dispatch, find_spec

ETH_ADDR = re.compile(r"0x[a-fA-F0-9]{40}")
NETWORK_KEYWORDS = {
    "ethereum": "1", "mainnet": "1", "eth": "1",
    "sepolia": "11155111",
    "base": "8453", "base sepolia": "84532",
    "arbitrum": "42161", "arb": "42161",
    "polygon": "137", "matic": "137",
    "optimism": "10", "op": "10",
    "unichain": "130",
}
AMOUNT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(eth|matic|usdc|usdt|dai|tokens?)?\b", re.I)


def _detect_network(prompt: str) -> str | None:
    p = prompt.lower()
    for keyword, chain_id in NETWORK_KEYWORDS.items():
        if keyword in p:
            return chain_id
    return None


def _heuristic_agent(client: Any, prompt: str) -> dict[str, Any]:
    """Resolve common prompts to direct KeeperHub tool calls, no LLM needed."""
    p = prompt.lower()
    network = _detect_network(prompt) or "11155111"
    addrs = ETH_ADDR.findall(prompt)

    plan: list[dict[str, Any]] = []
    final_answer: str

    if any(w in p for w in ["balance", "баланс"]):
        if addrs:
            spec = find_spec("keeperhub_check_balance")
            res = default_dispatch(client, spec, network=network, address=addrs[0])
            plan.append({"tool": spec.name, "arguments":
                         {"network": network, "address": addrs[0]}, "result": res})
            final_answer = (
                f"Checked balance for {addrs[0]} on chain {network}. "
                f"Result: {res.get('data')}"
            )
        else:
            final_answer = (
                "I'd need a 0x… address to check a balance — paste one in the prompt."
            )

    elif any(w in p for w in ["list workflow", "show workflow", "workflows", "воркфлоу"]):
        spec = find_spec("keeperhub_list_workflows")
        res = default_dispatch(client, spec)
        plan.append({"tool": spec.name, "arguments": {}, "result": res})
        final_answer = (
            f"Found {len(res.get('data') or [])} workflow(s) in this organization."
        )

    elif any(w in p for w in ["action schema", "available action", "what can"]):
        spec = find_spec("keeperhub_list_action_schemas")
        res = default_dispatch(client, spec, category="web3")
        plan.append({"tool": spec.name, "arguments": {"category": "web3"},
                     "result": res})
        final_answer = (
            f"KeeperHub web3 actions you can use: "
            f"{[a.get('actionType') for a in (res.get('data') or [])]}"
        )

    elif any(w in p for w in ["transfer", "send", "отправ"]) and addrs:
        amount_match = AMOUNT_RE.search(prompt)
        amount = amount_match.group(1) if amount_match else "0.001"
        wallet_spec = find_spec("keeperhub_get_wallet_integration")
        wallet_res = default_dispatch(client, wallet_spec)
        wallet_id = (wallet_res.get("data") or {}).get("id", "wallet_default")
        plan.append({"tool": wallet_spec.name, "arguments": {}, "result": wallet_res})

        spec = find_spec("keeperhub_transfer_funds")
        args = {
            "network": network, "to_address": addrs[0],
            "amount": amount, "wallet_id": wallet_id,
        }
        res = default_dispatch(client, spec, **args)
        plan.append({"tool": spec.name, "arguments": args, "result": res})
        final_answer = (
            f"Submitted transfer of {amount} on chain {network} to {addrs[0]} "
            f"via wallet {wallet_id}. Tx info: {res.get('data')}"
        )

    elif "ai" in p or "generate" in p or "create workflow" in p:
        spec = find_spec("keeperhub_ai_generate_workflow")
        res = default_dispatch(client, spec, description=prompt)
        plan.append({"tool": spec.name, "arguments": {"description": prompt},
                     "result": res})
        final_answer = (
            f"Generated workflow: {(res.get('data') or {}).get('name')}."
        )

    else:
        final_answer = (
            "I'm the heuristic fallback (no LLM key configured). "
            "Try prompts like:\n"
            "  • 'Check balance of 0xabc… on Sepolia'\n"
            "  • 'List my KeeperHub workflows'\n"
            "  • 'What web3 actions does KeeperHub support?'\n"
            "  • 'Transfer 0.01 ETH on Sepolia to 0xdef…'\n"
            "  • 'Generate a workflow that sends a daily balance report'\n"
            "Or set OPENAI_API_KEY to enable the full LangChain ReAct agent."
        )

    return {"engine": "heuristic", "final_answer": final_answer, "trace": plan}


async def _langchain_agent(client: Any, prompt: str) -> dict[str, Any]:
    """Full ReAct agent using LangChain + LangGraph."""
    try:
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "Install `langchain` and `langchain-openai` (already in the "
            "[server] extras) to use the LLM-driven agent."
        ) from exc

    from keeperkit.tools.langchain import build_langchain_tools

    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    llm = ChatOpenAI(model=model_name, temperature=0)
    tools = build_langchain_tools(client)

    system_prompt = (
        "You are a hands-on onchain operations agent. You have access to "
        "KeeperHub tools that perform reliable transaction execution: retry, "
        "gas optimization, simulation-before-submit, MEV-aware private "
        "routing, and a full audit trail. Prefer these tools over describing "
        "what you would do — call them. When you need a wallet_id, call "
        "`keeperhub_get_wallet_integration` first. When the user asks you to "
        "send value, transfer tokens, or write to a contract, you MUST route "
        "the action through KeeperHub. Always cite the executionId and "
        "transactionLink in your final answer if the tool returns one."
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

    return {"engine": f"langchain:{model_name}",
            "final_answer": final_answer, "trace": trace}


async def run_agent(client: Any, prompt: str) -> dict[str, Any]:
    """Entry point used by the FastAPI handler.

    Picks the LangChain ReAct agent when an OpenAI key is available, otherwise
    falls back to the LLM-less heuristic so the demo is always interactive.
    """
    has_openai = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if not has_openai:
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
