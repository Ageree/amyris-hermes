"""CONVEX-INTEGRATION: per-user claim + history isolation (M1).

Proves the two tenant-isolation properties M1 introduces against a REAL dev
Convex deployment (auto-skipped unless RUN_CONVEX_E2E=1; see conftest.py):

  1. claimNextForUser(userId=A) claims ONLY user A's oldest queued row and
     LEAVES user B's queued row untouched (no cross-tenant claim).
  2. recentForUser(userId=A) returns user A's OWN turns and EXCLUDES user B's —
     no cross-tenant memory bleed.

Why a real deployment: mocked unit tests can't catch a wrong index name or a
missing/incorrect return validator. This drives the live by_status_user /
by_userId indexes through the public HTTP API exactly as the fleet worker will.

Seeding uses the double-gated test helper `testing:seedTwoTenants` (needs
WORKER_SECRET + the dev-only ALLOW_TEST_SEED=1 env) to create two REAL throwaway
tenants; each test cleans them up in a finally. Throwaway-user memory is isolated
by userId, so this never touches the operator's real conversation history.

Run: `RUN_CONVEX_E2E=1 CONVEX_URL=... WORKER_SECRET=... python3 -m pytest -q \
      lab/tests/test_messages_claim_by_user.py`
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

from convex_client import ConvexClient


def _ctx():
    url = os.environ.get("CONVEX_URL")
    ws = os.environ.get("WORKER_SECRET")
    if not url or not ws:
        pytest.skip("CONVEX_URL + WORKER_SECRET required for the real dev deployment")
    return ConvexClient(url), ws


def _seed(convex, ws, tag):
    try:
        return convex.mutation("testing:seedTwoTenants", {"workerSecret": ws, "tag": tag})
    except RuntimeError as e:
        if "test seeding disabled" in str(e):
            pytest.skip("set ALLOW_TEST_SEED=1 on the dev deployment to run this test")
        raise


def _cleanup(convex, ws, seed):
    try:
        convex.mutation("testing:cleanupTenants",
                        {"workerSecret": ws, "userA": seed["userA"], "userB": seed["userB"]})
    except Exception:
        pass  # best-effort teardown


def _claim(convex, ws, user_id, attempts=8, delay=0.25):
    """Claim with a bounded retry — the real worker POLLS in a loop, so a single
    shot immediately after a seed is unrealistically tight (rare read-after-write
    window on the dev deployment under rapid mutations). Returns the claim or None.
    """
    for _ in range(attempts):
        c = convex.mutation(
            "messages:claimNextForUser", {"workerSecret": ws, "userId": user_id})
        if c is not None:
            return c
        time.sleep(delay)
    return None


@pytest.mark.convex_e2e
def test_claim_next_for_user_is_tenant_scoped():
    convex, ws = _ctx()
    seed = _seed(convex, ws, f"claim-{uuid.uuid4().hex[:8]}")
    try:
        claimed_a = _claim(convex, ws, seed["userA"])
        assert claimed_a is not None, "expected to claim user A's queued row"
        assert claimed_a["userId"] == seed["userA"], "claimed another tenant's row!"
        assert "claim-me" in (claimed_a["text"] or "")
        assert claimed_a["replyTarget"], "claimed row must carry a reply target (A2)"

        # B's row must remain queued (A's claim must not have touched it).
        claimed_b = _claim(convex, ws, seed["userB"])
        assert claimed_b is not None, "user B's row must remain claimable (untouched by A)"
        assert claimed_b["userId"] == seed["userB"]
        assert "leave-me" in (claimed_b["text"] or "")
    finally:
        _cleanup(convex, ws, seed)


@pytest.mark.convex_e2e
def test_recent_for_user_excludes_other_tenant():
    convex, ws = _ctx()
    seed = _seed(convex, ws, f"hist-{uuid.uuid4().hex[:8]}")
    try:
        # Claim + complete both turns so they become eligible for recentForUser.
        for who in ("userA", "userB"):
            c = _claim(convex, ws, seed[who])
            assert c is not None
            convex.mutation("messages:complete",
                            {"workerSecret": ws, "id": c["id"], "reply": f"ack {who}"})

        recent_a = convex.query(
            "messages:recentForUser",
            {"workerSecret": ws, "userId": seed["userA"], "limit": 10}) or []
        blob = " ".join((r.get("text") or "") + " " + (r.get("reply") or "") for r in recent_a)

        # Inclusion: A sees its OWN turn. Exclusion: nothing from B bleeds in.
        assert seed["textA"] in blob, "user A's own turn missing from recentForUser"
        assert seed["textB"] not in blob, "user B's turn bled into A's memory!"
        assert "ack userB" not in blob, "user B's reply bled into A's memory!"
    finally:
        _cleanup(convex, ws, seed)
