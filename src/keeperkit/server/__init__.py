"""KeeperKit demo server (FastAPI).

Exposes:
* a small static dashboard at ``/``,
* a JSON dispatch endpoint at ``/api/tools/{name}`` for testing tools without
  spinning up an LLM,
* an LLM-driven agent endpoint at ``/api/agent/run`` that uses LangChain +
  the KeeperKit tool factory to satisfy a user's natural-language request.
"""
