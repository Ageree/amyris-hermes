"""Thin, fail-soft Convex wrapper for the fleet:* calls a WORKER needs (M6).

Only the subset of fleet:* that the worker itself calls is implemented here.
The controller has its own client and is not this module's concern.

Design rule: EVERY function in this module is FAIL-SOFT — it must never raise
into the always-on worker loop. All exceptions are swallowed and logged.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("worker.fleet")


def heartbeat(
    convex: Any,
    worker_secret: str,
    user_id: str,
) -> Optional[str]:
    """Send a fleet heartbeat for `user_id` and return the desired state string.

    Returns the `desired` field from the Convex response ("running", "stopped",
    or None when absent). Returns None on ANY error so the worker loop is never
    interrupted by a control-plane hiccup (fail-soft by design).

    Args:
        convex: A ConvexClient instance (or any object with a `.mutation` method).
        worker_secret: The shared WORKER_SECRET token.
        user_id: The tenant's userId (scoped_user_id from WorkerConfig).

    Returns:
        "running" | "stopped" | None
    """
    if not user_id:
        # Guard: never call Convex with a blank userId — it's a logic error but
        # must not propagate (fail-soft).
        log.warning("heartbeat called with blank user_id; skipping")
        return None
    try:
        result = convex.mutation(
            "fleet:heartbeat",
            {"workerSecret": worker_secret, "userId": user_id},
        )
        if not isinstance(result, dict):
            log.debug("fleet:heartbeat returned non-dict %r for %s", result, user_id)
            return None
        desired = result.get("desired")
        return desired if isinstance(desired, str) else None
    except Exception:
        log.exception("fleet:heartbeat failed for %s (non-fatal)", user_id)
        return None
