"""LLM auto-detection for the demo agent.

KeeperKit is intentionally model-agnostic — LangChain and CrewAI both work
with any chat model. The demo server resolves *one* concrete chat model at
startup based on which API key is present in the environment, in priority
order. You can also pin a specific provider / model via env vars:

* ``KEEPERKIT_LLM_PROVIDER`` — one of: ``openai``, ``anthropic``, ``google``,
  ``groq``, ``deepseek``, ``openrouter``, ``mistral``, ``together``,
  ``ollama``. If unset, the first provider with a matching API key wins
  (priority: anthropic → google → groq → deepseek → openrouter → mistral →
  together → ollama → openai).
* ``KEEPERKIT_LLM_MODEL`` — overrides the default model for the chosen
  provider.

If no provider can be configured (no keys, no Ollama base URL), the demo
falls back to the LLM-less heuristic agent so the dashboard is still
interactive.
"""

from __future__ import annotations

import os
from typing import Any

ProviderResolver = tuple[Any, str]  # (chat_model, "provider:model")


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


_PROVIDER_PRIORITY = (
    "anthropic",
    "google",
    "groq",
    "deepseek",
    "openrouter",
    "mistral",
    "together",
    "ollama",
    "openai",
)


def _provider_active(name: str) -> bool:
    """Return True if the given provider has the env vars it needs."""
    if name == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if name == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if name == "google":
        return bool(os.environ.get("GOOGLE_API_KEY")
                    or os.environ.get("GEMINI_API_KEY"))
    if name == "groq":
        return bool(os.environ.get("GROQ_API_KEY"))
    if name == "deepseek":
        return bool(os.environ.get("DEEPSEEK_API_KEY"))
    if name == "openrouter":
        return bool(os.environ.get("OPENROUTER_API_KEY"))
    if name == "mistral":
        return bool(os.environ.get("MISTRAL_API_KEY"))
    if name == "together":
        return bool(os.environ.get("TOGETHER_API_KEY"))
    if name == "ollama":
        # Ollama is local — assume "active" only if explicitly opted in.
        return bool(os.environ.get("OLLAMA_BASE_URL"))
    return False


def detect_provider() -> str | None:
    """Return the provider name we'd build, or None if nothing is configured."""
    explicit = _norm(os.environ.get("KEEPERKIT_LLM_PROVIDER"))
    if explicit:
        return explicit if _provider_active(explicit) or explicit == "ollama" else None
    for name in _PROVIDER_PRIORITY:
        if _provider_active(name):
            return name
    return None


def build_llm() -> ProviderResolver | None:
    """Instantiate a LangChain chat model based on the environment.

    Returns ``(chat_model, "provider:model")`` or ``None`` if nothing is
    configured.
    """
    provider = detect_provider()
    if provider is None:
        return None
    return _build_for_provider(provider)


def _build_for_provider(provider: str) -> ProviderResolver:
    model = os.environ.get("KEEPERKIT_LLM_MODEL", "").strip()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        chosen = model or "claude-3-5-haiku-20241022"
        return ChatAnthropic(model=chosen, temperature=0), f"anthropic:{chosen}"

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        # gemini-1.5-flash is being decommissioned through 2025-2026; the
        # 2.0/2.5 flash models are GA on the same free-tier API key. We
        # default to 2.0-flash because it has the broadest tool-calling
        # support and the most generous free quota at time of writing.
        chosen = model or "gemini-2.0-flash"
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        return (ChatGoogleGenerativeAI(model=chosen, temperature=0,
                                       google_api_key=api_key),
                f"google:{chosen}")

    if provider == "groq":
        from langchain_groq import ChatGroq
        chosen = model or "llama-3.3-70b-versatile"
        return ChatGroq(model=chosen, temperature=0), f"groq:{chosen}"

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI
        chosen = model or "deepseek-chat"
        return (ChatOpenAI(model=chosen, temperature=0,
                           api_key=os.environ["DEEPSEEK_API_KEY"],
                           base_url="https://api.deepseek.com/v1"),
                f"deepseek:{chosen}")

    if provider == "openrouter":
        from langchain_openai import ChatOpenAI
        chosen = model or "openai/gpt-4o-mini"
        return (ChatOpenAI(model=chosen, temperature=0,
                           api_key=os.environ["OPENROUTER_API_KEY"],
                           base_url="https://openrouter.ai/api/v1",
                           default_headers={
                               "HTTP-Referer": "https://github.com/danilaverbena/keeperkit",
                               "X-Title": "KeeperKit",
                           }),
                f"openrouter:{chosen}")

    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        chosen = model or "mistral-small-latest"
        return ChatMistralAI(model=chosen, temperature=0), f"mistral:{chosen}"

    if provider == "together":
        from langchain_openai import ChatOpenAI
        chosen = model or "meta-llama/Llama-3.3-70B-Instruct-Turbo"
        return (ChatOpenAI(model=chosen, temperature=0,
                           api_key=os.environ["TOGETHER_API_KEY"],
                           base_url="https://api.together.xyz/v1"),
                f"together:{chosen}")

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        chosen = model or os.environ.get("OLLAMA_MODEL", "llama3.1")
        base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        return (ChatOllama(model=chosen, base_url=base, temperature=0),
                f"ollama:{chosen}")

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        chosen = (model
                  or os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
        kwargs: dict[str, Any] = {"model": chosen, "temperature": 0}
        # Honor a custom OpenAI-compatible endpoint (vLLM, LM Studio, LiteLLM,
        # Azure OpenAI proxy, etc.).
        if base := os.environ.get("OPENAI_BASE_URL"):
            kwargs["base_url"] = base
        return ChatOpenAI(**kwargs), f"openai:{chosen}"

    raise RuntimeError(f"Unknown KEEPERKIT_LLM_PROVIDER: {provider!r}")
