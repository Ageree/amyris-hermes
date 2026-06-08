#!/usr/bin/env python3
"""Thin Composio v3 REST client. The `ak_` developer key works on REST (NOT the
MCP transport). One source of HTTP truth for connect-links, status, tool exec.

Verified live 2026-06-08 against backend.composio.dev/api/v3."""
from __future__ import annotations

import os
from typing import Any, Optional

import requests

BASE_URL = "https://backend.composio.dev"


class ComposioError(RuntimeError):
    def __init__(self, message: str, *, code: Any = None, slug: str = ""):
        super().__init__(message)
        self.code = code
        self.slug = slug


class NotConnected(ComposioError):
    """The user has no ACTIVE connection for the toolkit the tool needs."""


class ComposioClient:
    def __init__(self, api_key: Optional[str] = None, user_id: Optional[str] = None,
                 base_url: str = BASE_URL, timeout: float = 30.0):
        self._key = api_key if api_key is not None else os.environ.get("COMPOSIO_API_KEY", "")
        if not self._key:
            raise ValueError("ComposioClient requires COMPOSIO_API_KEY")
        self._user = user_id if user_id is not None else os.environ.get("COMPOSIO_USER_ID", "")
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._key, "content-type": "application/json"}

    def _uid(self, user_id: Optional[str]) -> str:
        uid = user_id or self._user
        if not uid:
            raise ValueError("a user_id is required (pass --user-id or set COMPOSIO_USER_ID)")
        return uid

    @staticmethod
    def _raise_for_body(method: str, path: str, r: Any) -> dict:
        try:
            body = r.json()
        except Exception:
            body = {}
        err = body.get("error") if isinstance(body, dict) else None
        if err or not (200 <= r.status_code < 300):
            slug = (err or {}).get("slug", "") if isinstance(err, dict) else ""
            msg = (err or {}).get("message") if isinstance(err, dict) else None
            msg = msg or f"{method} {path} HTTP {r.status_code}: {str(getattr(r, 'text', ''))[:200]}"
            if slug == "ActionExecute_ConnectedAccountNotFound":
                raise NotConnected(msg, code=(err or {}).get("code"), slug=slug)
            raise ComposioError(msg, code=(err or {}).get("code") if isinstance(err, dict) else None, slug=slug)
        return body

    def _get(self, path: str, params: dict) -> dict:
        r = requests.get(f"{self._base}{path}", headers=self._headers, params=params, timeout=self._timeout)
        return self._raise_for_body("GET", path, r)

    def _post(self, path: str, json: dict) -> dict:
        r = requests.post(f"{self._base}{path}", headers=self._headers, json=json, timeout=self._timeout)
        return self._raise_for_body("POST", path, r)

    @staticmethod
    def _slug_of(item: dict) -> str:
        tk = item.get("toolkit")
        if isinstance(tk, dict):
            return str(tk.get("slug", "")).lower()
        return str(tk or "").lower()

    def find_auth_config(self, toolkit: str) -> Optional[str]:
        body = self._get("/api/v3/auth_configs", {})
        for it in body.get("items", []):
            if self._slug_of(it) == toolkit.lower():
                return it.get("id")
        return None

    def ensure_auth_config(self, toolkit: str) -> str:
        existing = self.find_auth_config(toolkit)
        if existing:
            return existing
        body = self._post("/api/v3/auth_configs",
                          {"toolkit": {"slug": toolkit}, "auth_config": {"type": "use_composio_managed_auth"}})
        cfg = body.get("auth_config") if isinstance(body.get("auth_config"), dict) else body
        cid = (cfg or {}).get("id") or body.get("id")
        if not cid:
            raise ComposioError(f"could not create auth_config for {toolkit}: {str(body)[:200]}")
        return cid

    def create_link(self, toolkit: str, user_id: Optional[str] = None) -> dict:
        auth_config_id = self.ensure_auth_config(toolkit)
        body = self._post("/api/v3/connected_accounts/link",
                          {"auth_config_id": auth_config_id, "user_id": self._uid(user_id)})
        return {"redirect_url": body.get("redirect_url"),
                "connected_account_id": body.get("connected_account_id"),
                "expires_at": body.get("expires_at")}

    def connection_status(self, toolkit: str, user_id: Optional[str] = None) -> str:
        body = self._get("/api/v3/connected_accounts",
                         {"user_ids": self._uid(user_id), "toolkit_slugs": toolkit})
        items = [it for it in body.get("items", []) if self._slug_of(it) == toolkit.lower()]
        if not items:
            return "none"
        statuses = [str(it.get("status", "")).upper() for it in items]
        if "ACTIVE" in statuses:
            return "ACTIVE"
        return statuses[0] or "none"

    def list_tools(self, toolkit: str) -> list[str]:
        body = self._get("/api/v3/tools", {"toolkit_slug": toolkit, "limit": 200})
        return [it["slug"] for it in body.get("items", []) if it.get("slug")]

    def execute(self, slug: str, arguments: dict, user_id: Optional[str] = None) -> dict:
        body = self._post(f"/api/v3/tools/execute/{slug}",
                          {"user_id": self._uid(user_id), "arguments": arguments or {}})
        return body
