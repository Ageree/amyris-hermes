"""Proper web search for the Eve/Hermes tool layer — a thin, dependency-light
client over the Exa REST API (https://docs.exa.ai).

Stdlib only (urllib + json), so it runs anywhere a Python 3.9+ exists with no
pip install. Two public capabilities:

  web_search(query, num_results=5) -> list[dict]   # {title,url,snippet,published?}
  answer(query)                    -> str          # Exa /answer, else top-results synthesis

Plus a tool-style entry point `tool(query, ...)` returning a JSON-serializable
dict, and a __main__ so it doubles as a CLI:  python3 -m features.web_search.exa_search "your query"

The Exa API key is read from the EXA_API_KEY env var, falling back to
~/.hermes-savedlab/.env (the lab's env file). Never hardcoded.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

SEARCH_URL = "https://api.exa.ai/search"
ANSWER_URL = "https://api.exa.ai/answer"
_ENV_FILE = os.path.expanduser("~/.hermes-savedlab/.env")
_TIMEOUT = 30  # seconds; Exa /answer can take ~10-20s


class WebSearchError(RuntimeError):
    """Raised on a transport/HTTP/auth failure talking to Exa."""


def _env_from_file(path: str, key: str) -> Optional[str]:
    """Read KEY=value from a dotenv-style file. Returns None if absent/unreadable."""
    try:
        for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _api_key() -> str:
    key = os.environ.get("EXA_API_KEY") or _env_from_file(_ENV_FILE, "EXA_API_KEY")
    if not key:
        raise WebSearchError(
            "EXA_API_KEY not set (env or ~/.hermes-savedlab/.env). "
            "Get a key at https://dashboard.exa.ai/api-keys"
        )
    return key


def _post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST JSON to Exa with the X-API-Key header; return the parsed JSON body.

    Raises WebSearchError on any HTTP/transport error, surfacing Exa's own error
    text when present so the caller (and logs) see the real cause.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Exa accepts the key via the X-API-Key header (also `Authorization`).
            "X-API-Key": _api_key(),
            "User-Agent": "eve-web-search/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # pragma: no cover - best-effort detail
            pass
        raise WebSearchError(f"Exa HTTP {e.code} at {url}: {detail}") from e
    except urllib.error.URLError as e:
        raise WebSearchError(f"Exa request failed at {url}: {e.reason}") from e


def _snippet(result: dict[str, Any]) -> str:
    """Pull a human-readable snippet out of an Exa result.

    Exa returns text under `highlights` (list) when asked, or `text` (string).
    We request highlights for compact, query-relevant snippets.
    """
    highlights = result.get("highlights")
    if isinstance(highlights, list) and highlights:
        return " ... ".join(h.strip() for h in highlights if h).strip()
    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()[:500]
    return ""


def web_search(query: str, num_results: int = 5) -> list[dict[str, Any]]:
    """Search the web via Exa. Returns a list of result dicts:

        {"title": str, "url": str, "snippet": str, "published": str | None}

    `published` is omitted (None) when Exa has no published date for the result.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("query must be a non-empty string")
    num_results = max(1, min(int(num_results), 25))  # Exa caps; keep it sane

    data = _post(
        SEARCH_URL,
        {
            "query": query,
            "numResults": num_results,
            "type": "auto",  # let Exa pick neural vs keyword
            "contents": {"highlights": {"numSentences": 2, "highlightsPerUrl": 2}},
        },
    )

    out: list[dict[str, Any]] = []
    for r in data.get("results", []) or []:
        url = r.get("url")
        if not url:
            continue  # a result with no URL is useless for an agent
        out.append(
            {
                "title": (r.get("title") or "").strip() or url,
                "url": url,
                "snippet": _snippet(r),
                "published": r.get("publishedDate") or None,
            }
        )
    return out


def answer(query: str) -> str:
    """Get a direct, sourced answer to `query`.

    Tries Exa's /answer endpoint first (an LLM-grounded answer over live search).
    If that endpoint errors (e.g. plan/quota), falls back to synthesizing the top
    web_search snippets into a readable answer so the caller always gets a string.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("query must be a non-empty string")

    try:
        data = _post(ANSWER_URL, {"query": query, "text": False})
        ans = (data.get("answer") or "").strip()
        if ans:
            cites = data.get("citations") or []
            urls = [c.get("url") for c in cites if isinstance(c, dict) and c.get("url")]
            if urls:
                ans += "\n\nSources:\n" + "\n".join(f"- {u}" for u in urls[:5])
            return ans
    except WebSearchError:
        pass  # fall through to synthesis — answer() must still return a string

    # Fallback: synthesize from top search results.
    results = web_search(query, num_results=5)
    if not results:
        return f"No web results found for: {query}"
    lines = [f"Top results for: {query}", ""]
    for i, r in enumerate(results[:5], 1):
        snip = r["snippet"] or "(no snippet)"
        lines.append(f"{i}. {r['title']} — {snip}\n   {r['url']}")
    return "\n".join(lines)


# --- Agent tool-style entry point -------------------------------------------
# A single flat callable an agent/tool-router can wire up. Returns a
# JSON-serializable dict, never raises for normal "no results" cases.

def tool(query: str, num_results: int = 5, want_answer: bool = False) -> dict[str, Any]:
    """Tool entry point for the Eve/Hermes agent layer.

    Args:
        query: the search query (required).
        num_results: how many results to return (default 5).
        want_answer: if true, also include a synthesized `answer` string.

    Returns a dict: {"query", "results": [...], "answer"?: str, "error"?: str}.
    """
    try:
        results = web_search(query, num_results=num_results)
        payload: dict[str, Any] = {"query": query, "results": results}
        if want_answer:
            payload["answer"] = answer(query)
        return payload
    except (WebSearchError, ValueError) as e:
        return {"query": query, "results": [], "error": str(e)}


# OpenAI/Anthropic-style JSON schema so the agent layer can register the tool.
TOOL_SCHEMA = {
    "name": "web_search",
    "description": "Search the live web (via Exa) and get titles, URLs, and snippets. "
    "Set want_answer=true to also get a direct sourced answer.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "num_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 25},
            "want_answer": {"type": "boolean", "default": False},
        },
        "required": ["query"],
    },
}


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python3 -m features.web_search.exa_search <query> [--answer]", file=sys.stderr)
        return 2
    want_answer = "--answer" in argv[2:]
    query = " ".join(a for a in argv[1:] if a != "--answer")
    result = tool(query, want_answer=want_answer)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("results") or result.get("answer") else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
