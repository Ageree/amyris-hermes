"""Small stdlib Supermemory client used by tenant workers.

Secrets come only from SUPERMEMORY_API_KEY. Every call is tenant-scoped with a
container tag derived from userId/phone, so memories cannot bleed across users.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("supermemory")

JsonObj = dict[str, Any]


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def tenant_tag(user_key: str) -> str:
    """Stable Supermemory container tag for one tenant."""
    safe = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", user_key.strip())[:96]
    return f"hermes:user:{safe or 'unknown'}"


@dataclass(frozen=True)
class SupermemoryConfig:
    api_key: str = ""
    base_url: str = "https://api.supermemory.ai"
    enabled: bool = True
    write_enabled: bool = True
    search_limit: int = 8
    timeout: float = 10.0

    @classmethod
    def from_env(cls) -> SupermemoryConfig:
        return cls(
            api_key=os.environ.get("SUPERMEMORY_API_KEY", ""),
            base_url=os.environ.get(
                "SUPERMEMORY_BASE_URL", "https://api.supermemory.ai"
            ),
            enabled=_env_flag("SUPERMEMORY_ENABLED", True),
            write_enabled=_env_flag("SUPERMEMORY_WRITE_ENABLED", True),
            search_limit=int(os.environ.get("SUPERMEMORY_SEARCH_LIMIT", "8")),
            timeout=float(os.environ.get("SUPERMEMORY_TIMEOUT", "10.0")),
        )

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.api_key)


class SupermemoryClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.supermemory.ai",
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    @classmethod
    def from_config(cls, cfg: SupermemoryConfig) -> SupermemoryClient | None:
        if not cfg.available:
            return None
        return cls(cfg.api_key, base_url=cfg.base_url, timeout=cfg.timeout)

    def _request(self, method: str, path: str, payload: JsonObj) -> Any:
        if not self._api_key:
            raise RuntimeError("SUPERMEMORY_API_KEY not configured")
        data = json.dumps(payload, ensure_ascii=False).encode()
        req = urllib.request.Request(
            f"{self._base}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raw = exc.read()[:300].decode(errors="replace")
            raise RuntimeError(
                f"supermemory {method} {path} HTTP {exc.code}: {raw}"
            ) from exc
        if not body:
            return None
        return json.loads(body)

    def recall(self, user_key: str, query: str, *, limit: int = 8) -> list[str]:
        tag = tenant_tag(user_key)
        body = {
            "q": query or "user profile preferences facts",
            "limit": limit,
            "containerTag": tag,
            "searchMode": "hybrid",
        }
        for path in ("/v4/search", "/v3/search"):
            try:
                return _texts_from_response(self._request("POST", path, body), limit)
            except Exception as exc:
                log.debug("supermemory recall via %s failed: %s", path, exc)
        return []

    def remember_text(
        self,
        user_key: str,
        content: str,
        *,
        kind: str,
        metadata: JsonObj | None = None,
    ) -> bool:
        text = content.strip()
        if not text:
            return False
        meta: JsonObj = {"kind": kind, **(metadata or {})}
        tag = tenant_tag(user_key)
        custom_id = (
            f"{kind}:{user_key}:{hashlib.sha256(text.encode()).hexdigest()[:32]}"
        )
        candidates = [
            (
                "/v4/memories",
                {
                    "memories": [{"content": text, "metadata": meta}],
                    "containerTag": tag,
                },
            ),
            (
                "/v3/documents",
                {
                    "content": text,
                    "containerTag": tag,
                    "metadata": meta,
                    "customId": custom_id,
                },
            ),
        ]
        for path, body in candidates:
            try:
                self._request("POST", path, body)
                return True
            except Exception as exc:
                log.debug("supermemory write via %s failed: %s", path, exc)
        return False


def _texts_from_response(data: Any, limit: int) -> list[str]:
    items = _response_items(data)
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _extract_text(item)
        if not text:
            continue
        text = re.sub(r"\s+", " ", text).strip()
        if text in seen:
            continue
        seen.add(text)
        out.append(text[:600])
        if len(out) >= limit:
            break
    return out


def _response_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("results", "memories", "documents", "items", "data"):
        val = data.get(key)
        if isinstance(val, list):
            return val
    return []


def _extract_text(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    for key in ("memory", "content", "chunk", "text", "summary", "title"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    doc = item.get("document")
    if isinstance(doc, dict):
        return _extract_text(doc)
    mem = item.get("memory")
    if isinstance(mem, dict):
        return _extract_text(mem)
    return None
