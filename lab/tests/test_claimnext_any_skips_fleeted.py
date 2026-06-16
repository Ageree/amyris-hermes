"""CONVEX-INTEGRATION: cutover coexistence — claimNextAny SKIPS fleeted users.

Proves the keystone that lets the shared "bridge" worker and the per-user GCP fleet
run SAFELY at the same time (and enables a gradual, loss-free cutover):

  Once user A is flipped to the fleet (agentInstances.desired="running"), the shared
  worker's `messages:claimNextAny` must NEVER claim A's messages — they are reserved
  for A's OWN container via `claimNextForUser`. Otherwise the shared worker would
  MIS-ROUTE A (serve without A's container state/logins). B, not fleeted, stays
  shared-claimable (existing behavior, covered by test_messages_claim_by_user).

Why a real deployment: the skip reads the live by_desired_status index and the
by_status scan together inside one mutation. This drives that exact path.

Runs against live dev WITH the shared worker active, so it is double-discriminating
for a broken skip: a broken skip shows up EITHER as claimNextAny returning A's row
(assertion 1) OR as the shared worker stealing A's row so claimNextForUser(A) then
returns None (assertion 2).

Auto-skipped unless RUN_CONVEX_E2E=1 (+ CONVEX_URL / WORKER_SECRET; dev sets
ALLOW_TEST_SEED=1). Uses throwaway tt-*@test.invalid tenants, cleaned up in finally.

Run: `RUN_CONVEX_E2E=1 CONVEX_URL=... WORKER_SECRET=... python3 -m pytest -q \
      lab/tests/test_claimnext_any_skips_fleeted.py`
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


def _claim_for_user(convex, ws, user_id, attempts=8, delay=0.25):
    for _ in range(attempts):
        c = convex.mutation(
            "messages:claimNextForUser", {"workerSecret": ws, "userId": user_id})
        if c is not None:
            return c
        time.sleep(delay)
    return None


@pytest.mark.convex_e2e
def test_claim_next_any_skips_fleeted_user():
    convex, ws = _ctx()
    seed = _seed(convex, ws, f"skip-{uuid.uuid4().hex[:8]}")
    try:
        # Flip A to the per-user fleet (desired="running"); B stays shared.
        convex.mutation(
            "fleet:requestInstance", {"workerSecret": ws, "userId": seed["userA"]})

        # (1) Direct skip: none of MY claimNextAny calls may return A's row. The
        # shared worker is also polling claimNextAny in parallel; A's row staying
        # queued throughout (skipped by every caller) is the property under test.
        for _ in range(8):
            c = convex.mutation("messages:claimNextAny", {"workerSecret": ws})
            if c is not None:
                assert c["userId"] != seed["userA"], \
                    "claimNextAny claimed a FLEETED user's row — mis-route!"
            time.sleep(0.25)

        # (2) A's row stays RESERVED for A's container even with the shared worker
        # live: it must still be claimable by claimNextForUser(A). If the skip were
        # broken, the shared worker would have stolen it above and this returns None.
        claimed_a = _claim_for_user(convex, ws, seed["userA"])
        assert claimed_a is not None, \
            "fleeted user's row was stolen by the shared worker — skip is broken"
        assert claimed_a["userId"] == seed["userA"]
    finally:
        _cleanup(convex, ws, seed)
