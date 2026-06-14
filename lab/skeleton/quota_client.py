"""Thin quota-gate client (M5, design §6).

Wraps the Convex `quota.ts` mutations the worker calls right after claim:
`checkAndReserve` (reserve one unit before any model call), `recordUsage` (audit
row after a turn), `releaseReserve` (refund on a hard failure).

Two failure philosophies, per the design:
  - FAIL OPEN on a transport / Convex error — a control-plane hiccup must NEVER
    lock paying users out, so `check_and_reserve` returns an allow sentinel.
  - FAIL CLOSED on a CLEAN over-quota verdict — the worker (not this module)
    turns that into a friendly upsell and runs no lane.

Synthetic (`resume:` / `e2e`) and operator/legacy (userId-less) turns are
UNMETERED; the worker decides that before calling here.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("worker.quota")

# Returned when Convex is unreachable / malformed: the worker proceeds (fail open).
# `fail_open` lets the caller know NOT to record/release (nothing was reserved).
def _fail_open() -> dict:
    return {
        "allowed": True,
        "fail_open": True,
        "tier": None,
        "remaining": -1,
        "msgQuota": -1,
        "periodEnd": 0,
    }


def is_synthetic(handle: str) -> bool:
    """Connect-resume + e2e turns are not charged (avoid double-charging the
    connect flow / polluting real usage)."""
    h = handle or ""
    return h.startswith("resume:") or h.startswith("e2e")


def check_and_reserve(convex: Any, worker_secret: str, user_id: str) -> dict:
    """Reserve one unit. Returns the Convex verdict dict, or a fail-open sentinel
    on ANY error. The verdict always has `allowed: bool`; on a clean deny it also
    carries `reason` ('over_quota' | 'canceled' | 'no_entitlement')."""
    try:
        res = convex.mutation(
            "quota:checkAndReserve",
            {"workerSecret": worker_secret, "userId": user_id},
        )
        if not isinstance(res, dict) or "allowed" not in res:
            log.warning("checkAndReserve returned unexpected %r; failing open", res)
            return _fail_open()
        return res
    except Exception:
        log.exception("checkAndReserve failed for %s; failing open", user_id)
        return _fail_open()


def record_usage(
    convex: Any,
    worker_secret: str,
    user_id: str,
    *,
    message_id: Optional[str] = None,
    lane: Optional[str] = None,
    channel: Optional[str] = None,
    units: int = 1,
) -> None:
    """Append one usageEvents audit row. Best-effort — never raises (the turn
    already succeeded; a missing audit row must not fail the user)."""
    args: dict = {"workerSecret": worker_secret, "userId": user_id, "units": units}
    if message_id:
        args["messageId"] = message_id
    if lane:
        args["lane"] = lane
    if channel:
        args["channel"] = channel
    try:
        convex.mutation("quota:recordUsage", args)
    except Exception:
        log.exception("recordUsage failed for %s (non-fatal)", user_id)


def release_reserve(convex: Any, worker_secret: str, user_id: str) -> None:
    """Refund a reserved unit after a HARD turn failure (undelivered turn).
    Best-effort — never raises."""
    try:
        convex.mutation(
            "quota:releaseReserve",
            {"workerSecret": worker_secret, "userId": user_id},
        )
    except Exception:
        log.exception("releaseReserve failed for %s (non-fatal)", user_id)


def upsell_text(tier: Optional[str], upgrade_url: str) -> str:
    """Friendly lowercase over-quota message (brand voice). Includes the upgrade
    link when configured; otherwise points at the period reset."""
    base = "you've hit your message limit for this period."
    if upgrade_url:
        return f"{base} upgrade for more headroom: {upgrade_url}"
    return f"{base} it resets at the start of your next cycle — talk soon."
