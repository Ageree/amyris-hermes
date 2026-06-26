"""Minimal REST client for the AgentPhone API (api.agentphone.ai/v1).

Stdlib-only (urllib) on purpose — no `requests` dependency. The base URL and
auth header match the AgentPhone OpenAPI spec: `Authorization: Bearer <key>`.

The key is NEVER hardcoded. Resolution order in `load_key()`:
  1. env var AGENTPHONE_KEY
  2. a dotenv-style file at env var AGENTPHONE_SECRETS_FILE (KEY=VALUE lines)
  3. ~/.hermes-savedlab/.env (the lab default)
"""
from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request

BASE_URL = "https://api.agentphone.ai/v1"
DEFAULT_TIMEOUT = 30
# api.agentphone.ai sits behind Cloudflare, which 1010-bans the default
# "Python-urllib/x.y" User-Agent. Present a normal browser UA instead.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/125.0.0.0 Safari/537.36")


class AgentPhoneError(RuntimeError):
    """Raised when the API returns a non-2xx status (carries status + body)."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"AgentPhone API {status}: {body[:500]}")


def _read_dotenv_value(path: str, key: str) -> str | None:
    p = pathlib.Path(path).expanduser()
    if not p.is_file():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def load_key(secrets_file: str | None = None) -> str:
    """Resolve the AgentPhone API key from env or a dotenv file. Never logs it."""
    key = os.environ.get("AGENTPHONE_KEY")
    if key:
        return key.strip()
    candidates = [secrets_file, os.environ.get("AGENTPHONE_SECRETS_FILE"),
                  "~/.hermes-savedlab/.env"]
    for cand in candidates:
        if not cand:
            continue
        val = _read_dotenv_value(cand, "AGENTPHONE_KEY")
        if val:
            return val
    raise AgentPhoneError(0, "AGENTPHONE_KEY not found in env or secrets file")


def _request(method: str, path: str, *, key: str | None = None,
             body: dict | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict | list:
    """Issue one HTTP request; return parsed JSON. Raises AgentPhoneError on non-2xx."""
    key = key or load_key()
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace") if e.fp else ""
        raise AgentPhoneError(e.code, detail) from None
    except urllib.error.URLError as e:
        raise AgentPhoneError(0, f"network error: {e.reason}") from None


# ---- typed endpoint wrappers -------------------------------------------------

def get_usage(key: str | None = None) -> dict:
    """GET /v1/usage — plan, limits, and usage stats."""
    return _request("GET", "/usage", key=key)  # type: ignore[return-value]


def list_agents(key: str | None = None) -> list:
    """GET /v1/agents — returns the list of agents (unwraps {data,total})."""
    resp = _request("GET", "/agents", key=key)
    return resp["data"] if isinstance(resp, dict) and "data" in resp else resp


def list_voices(key: str | None = None) -> list:
    """GET /v1/agents/voices — returns the list of voice dicts (unwraps {data})."""
    resp = _request("GET", "/agents/voices", key=key)
    return resp["data"] if isinstance(resp, dict) and "data" in resp else resp


def create_agent(name: str, system_prompt: str, language: str = "ru-RU",
                 voice: str | None = None, *, voice_mode: str = "hosted",
                 model_tier: str = "balanced", begin_message: str | None = None,
                 key: str | None = None) -> dict:
    """POST /v1/agents — create an agent persona.

    voice_mode defaults to "hosted" so the built-in LLM drives the call from
    `system_prompt` (no webhook server needed). `language` is a BCP-47 locale
    (e.g. ru-RU). `voice` is an optional voice_id from list_voices().
    """
    if not name or not name.strip():
        raise ValueError("name is required")
    payload: dict = {
        "name": name,
        "systemPrompt": system_prompt,
        "language": language,
        "voiceMode": voice_mode,
        "modelTier": model_tier,
    }
    if voice:
        payload["voice"] = voice
    if begin_message:
        payload["beginMessage"] = begin_message
    return _request("POST", "/agents", key=key, body=payload)  # type: ignore[return-value]


def get_agent(agent_id: str, key: str | None = None) -> dict:
    """GET /v1/agents/{id}."""
    return _request("GET", f"/agents/{agent_id}", key=key)  # type: ignore[return-value]


def delete_agent(agent_id: str, key: str | None = None) -> dict:
    """DELETE /v1/agents/{id}."""
    return _request("DELETE", f"/agents/{agent_id}", key=key)  # type: ignore[return-value]


def place_call(payload: dict, key: str | None = None) -> dict:
    """POST /v1/calls — LOW-LEVEL: actually places a real outbound call.

    Do NOT call this in tests. `book_table(dry_run=False, confirm_real_call=True)`
    is the only intended caller, and only behind an explicit operator flag.
    """
    return _request("POST", "/calls", key=key, body=payload)  # type: ignore[return-value]
