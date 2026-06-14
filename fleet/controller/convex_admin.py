"""Thin Convex HTTP admin client for the fleet controller.

Uses the same public HTTP API pattern as lab/skeleton/convex_client.py
(POST /api/query and /api/mutation) but gated by a WORKER_SECRET argument
rather than auth headers.

Design choices:
- list_reconcile() is FAIL-SOFT (returns [] on error) — a transient Convex
  hiccup must not crash the reconcile loop.
- Mutation helpers (claim_for_launch, mark_stopped, mark_error, set_desired)
  surface errors to the caller; the loop decides how to handle them.
- urllib.request only — no third-party deps.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ConvexAdminClient:
    """Fleet-controller Convex client.

    Reads WORKER_SECRET from the environment at call time so it never
    appears in __repr__ or log lines.
    """

    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        if not base_url:
            raise ValueError("ConvexAdminClient requires a base_url")
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def list_reconcile(self) -> list[dict]:
        """Return current reconcile snapshot.

        FAIL-SOFT: logs the error and returns [] so the loop keeps running.
        """
        try:
            result = self._query("fleet:listReconcile", self._auth_args())
            if not isinstance(result, list):
                logger.error("fleet:listReconcile returned non-list: %r", result)
                return []
            return result
        except Exception as exc:
            logger.error("fleet:listReconcile failed (will retry): %s", exc)
            return []

    def claim_for_launch(
        self,
        user_id: str,
        host_vm: str,
        container_id: str,
        worker_secret_ref: Optional[str] = None,
    ) -> dict:
        """Attempt to claim a launch slot.

        Returns {"claimed": bool}.  Raises on hard errors.
        """
        args = {
            **self._auth_args(),
            "userId": user_id,
            "hostVm": host_vm,
            "containerId": container_id,
        }
        if worker_secret_ref is not None:
            args["workerSecretRef"] = worker_secret_ref
        return self._mutation("fleet:claimInstanceForLaunch", args)

    def mark_stopped(self, user_id: str) -> None:
        """Mark an instance as stopped in Convex."""
        self._mutation("fleet:markStopped", {**self._auth_args(), "userId": user_id})

    def mark_error(self, user_id: str, error: str) -> dict:
        """Record an error for an instance.

        Returns {"errorCount": int}.
        """
        return self._mutation(
            "fleet:markError",
            {**self._auth_args(), "userId": user_id, "error": error},
        )

    def set_desired(self, user_id: str, desired: str) -> None:
        """Override the desired state of an instance."""
        if desired not in ("running", "stopped"):
            raise ValueError(f"desired must be 'running' or 'stopped', got {desired!r}")
        self._mutation(
            "fleet:setDesired",
            {**self._auth_args(), "userId": user_id, "desired": desired},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_args(self) -> dict:
        """Return the workerSecret arg dict, reading from env at call time."""
        secret = os.environ.get("WORKER_SECRET", "")
        if not secret:
            raise RuntimeError("WORKER_SECRET env var is not set")
        return {"workerSecret": secret}

    def _query(self, path: str, args: dict[str, Any]) -> Any:
        return self._call("query", path, args)

    def _mutation(self, path: str, args: dict[str, Any]) -> Any:
        return self._call("mutation", path, args)

    def _call(self, kind: str, path: str, args: dict[str, Any]) -> Any:
        url = f"{self._base}/api/{kind}"
        payload = json.dumps(
            {"path": path, "args": args, "format": "json"}
        ).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read()[:300].decode(errors="replace")
            raise RuntimeError(f"Convex {kind} {path} HTTP {exc.code}: {raw}") from exc
        except Exception as exc:
            raise RuntimeError(f"Convex {kind} {path} request failed: {exc}") from exc

        if body.get("status") != "success":
            raise RuntimeError(
                f"Convex {kind} {path} error: {body.get('errorMessage', body)}"
            )
        return body.get("value")
