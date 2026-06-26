"""features.web_search — proper web search for the Eve/Hermes tool layer.

Public surface:
    web_search(query, num_results=5) -> list[dict]   # {title,url,snippet,published?}
    answer(query)                    -> str
    tool(query, num_results=5, want_answer=False) -> dict   # agent tool entry point
    TOOL_SCHEMA                      # JSON schema for tool registration
"""
from .exa_search import TOOL_SCHEMA, WebSearchError, answer, tool, web_search

__all__ = ["web_search", "answer", "tool", "TOOL_SCHEMA", "WebSearchError"]
