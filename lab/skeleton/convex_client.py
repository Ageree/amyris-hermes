"""Thin Convex HTTP API client for the brain-side worker (P1C).

The durable queue lives in Convex as plain public functions gated by a
WORKER_SECRET *argument* (see control-plane/convex/messages.ts) — not by Convex
auth. So the brain reaches them over Convex's stable HTTP API with nothing but
`requests`: no Node client, no admin key, no auth header.

Verified live against dev:zany-tapir-501 (2026-06-08):
  POST {base}/api/query    body {"path","args","format":"json"} -> {"status","value"}
  POST {base}/api/mutation same shape; errors come back as
       {"status":"error","errorMessage": "..."} with HTTP 200, so we must
       inspect the body status, not just the HTTP code.
"""
from __future__ import annotations

from typing import Any

import requests


class ConvexClient:
    """Minimal Convex function caller over the public HTTP API."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        if not base_url:
            raise ValueError("ConvexClient requires a base_url")
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def query(self, path: str, args: dict[str, Any]) -> Any:
        return self._call("query", path, args)

    def mutation(self, path: str, args: dict[str, Any]) -> Any:
        return self._call("mutation", path, args)

    def _call(self, kind: str, path: str, args: dict[str, Any]) -> Any:
        url = f"{self._base}/api/{kind}"
        r = requests.post(
            url,
            json={"path": path, "args": args, "format": "json"},
            timeout=self._timeout,
        )
        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"Convex {kind} {path} HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        if body.get("status") != "success":
            raise RuntimeError(
                f"Convex {kind} {path} error: {body.get('errorMessage', body)}"
            )
        return body.get("value")
