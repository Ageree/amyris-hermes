"""CONVEX-INTEGRATION (M6): fleet.ts desired-state lifecycle against REAL dev Convex.

Closes the audit gap that fleet.ts had ZERO live coverage (its server behavior was
asserted only by mocked controller tests). Drives the actual WORKER_SECRET-gated
fleet functions over the public HTTP API exactly as the controller + scoped workers
do, proving the desired-state machine + the idle reaper against the live
by_user / by_desired_status / by_status_heartbeat indexes:

  - test_request_claim_heartbeat_reconcile  cold-start upsert → reconcile sees it →
                                            claim → heartbeat → setDesired → markStopped.
  - test_at_most_once_launch                two racing claims for one instance →
                                            EXACTLY one wins (atomic status guard).
  - test_idle_reap_free_not_paid            a free instance idle past the TTL is
                                            reaped (desired→stopped); a paid one is NOT.

Auto-skipped unless RUN_CONVEX_E2E=1 (+ CONVEX_URL / WORKER_SECRET; the dev
deployment sets ALLOW_TEST_SEED=1). Uses THROWAWAY tenants (tt-*@test.invalid) via
the double-gated testing:* seams and reaps them (incl. their agentInstances row) in
a finally — never touches the operator's data.

Run: `RUN_CONVEX_E2E=1 CONVEX_URL=... WORKER_SECRET=... python3 -m pytest -q \
      lab/tests/test_e2e_fleet_lifecycle.py`
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from convex_client import ConvexClient  # noqa: E402

pytestmark = pytest.mark.convex_e2e

IDLE_TTL_FREE_MS = 30 * 60_000  # mirror fleet.ts IDLE_TTL_FREE_MS


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
        pass  # best-effort teardown (also reaps the agentInstances rows)


def _tag(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _reconcile_for(convex, ws, user_id):
    """Return this user's row from listReconcile, or None."""
    rows = convex.query("fleet:listReconcile", {"workerSecret": ws}) or []
    for r in rows:
        if r["userId"] == user_id:
            return r
    return None


def test_request_claim_heartbeat_reconcile():
    """The full desired-state lifecycle over the live indexes."""
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag("life"))
    uid = seed["userA"]
    try:
        # Cold-start upsert: first request CREATES a provisioning row.
        r1 = convex.mutation("fleet:requestInstance", {"workerSecret": ws, "userId": uid})
        assert r1["created"] is True and r1["status"] == "provisioning", r1
        # Idempotent: a second request does NOT create a duplicate.
        r2 = convex.mutation("fleet:requestInstance", {"workerSecret": ws, "userId": uid})
        assert r2["created"] is False and r2["instanceId"] == r1["instanceId"], r2

        # Reconcile sees it as wanted-but-not-yet-running (controller would launch).
        item = _reconcile_for(convex, ws, uid)
        assert item is not None, "requested instance missing from listReconcile"
        assert item["desired"] == "running" and item["status"] == "provisioning", item

        # Controller claims it after a successful docker run.
        claim = convex.mutation("fleet:claimInstanceForLaunch", {
            "workerSecret": ws, "userId": uid, "hostVm": "vm-test", "containerId": "c-abc"})
        assert claim["claimed"] is True, claim

        # Worker heartbeat → desired echoes back so it can drain on reap.
        hb = convex.mutation("fleet:heartbeat", {"workerSecret": ws, "userId": uid})
        assert hb["desired"] == "running", hb

        # Now reconcile shows it actually running (by_status_heartbeat).
        item = _reconcile_for(convex, ws, uid)
        assert item is not None and item["status"] == "running", item
        assert item["containerId"] == "c-abc" and item["hostVm"] == "vm-test", item

        # Flip desired→stopped; heartbeat now tells the worker to drain.
        convex.mutation("fleet:setDesired", {"workerSecret": ws, "userId": uid, "desired": "stopped"})
        hb2 = convex.mutation("fleet:heartbeat", {"workerSecret": ws, "userId": uid})
        assert hb2["desired"] == "stopped", hb2

        # Controller marks it stopped after a clean docker stop.
        convex.mutation("fleet:markStopped", {"workerSecret": ws, "userId": uid})
        item = _reconcile_for(convex, ws, uid)
        # desired=stopped + status=stopped → no longer wanted, no longer running:
        # it drops out of BOTH reconcile index unions.
        assert item is None, f"stopped instance should leave the reconcile set: {item}"
    finally:
        _cleanup(convex, ws, seed)


def test_at_most_once_launch():
    """Two controllers racing the same launch → exactly one claim wins."""
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag("once"))
    uid = seed["userA"]
    try:
        convex.mutation("fleet:requestInstance", {"workerSecret": ws, "userId": uid})
        c1 = convex.mutation("fleet:claimInstanceForLaunch", {
            "workerSecret": ws, "userId": uid, "hostVm": "vm1", "containerId": "c1"})
        c2 = convex.mutation("fleet:claimInstanceForLaunch", {
            "workerSecret": ws, "userId": uid, "hostVm": "vm2", "containerId": "c2"})
        wins = [c for c in (c1, c2) if c["claimed"]]
        assert len(wins) == 1, f"at-most-once launch violated: {c1} {c2}"
        # The winner's container is the one recorded (loser tears its duplicate down).
        item = _reconcile_for(convex, ws, uid)
        assert item is not None and item["containerId"] == "c1", item
    finally:
        _cleanup(convex, ws, seed)


def test_idle_reap_free_not_paid():
    """A free instance idle past the TTL is reaped; a paid one stays warm."""
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag("reap"))
    free_uid = seed["userA"]   # no entitlement → tier "free"
    paid_uid = seed["userB"]   # given a "pro" entitlement → tier "paid"
    try:
        # Make B paid BEFORE requesting its instance so deriveTier picks "paid".
        convex.mutation("testing:testSetEntitlement", {
            "workerSecret": ws, "userId": paid_uid, "tier": "pro",
            "msgQuota": 1000, "msgUsed": 0})

        for uid, host in ((free_uid, "vmF"), (paid_uid, "vmP")):
            convex.mutation("fleet:requestInstance", {"workerSecret": ws, "userId": uid})
            claim = convex.mutation("fleet:claimInstanceForLaunch", {
                "workerSecret": ws, "userId": uid, "hostVm": host, "containerId": f"c-{host}"})
            assert claim["claimed"] is True, (uid, claim)

        # Age BOTH instances past the idle TTL.
        old = int(time.time() * 1000) - (IDLE_TTL_FREE_MS + 60_000)
        for uid in (free_uid, paid_uid):
            bd = convex.mutation("testing:testBackdateInstance", {
                "workerSecret": ws, "userId": uid, "lastActiveAt": old})
            assert bd["ok"] is True, (uid, bd)

        reap = convex.mutation("testing:testReapIdle", {"workerSecret": ws})
        assert reap["reaped"] >= 1, reap

        # Free → reaped (desired flipped to stopped); paid → still warm.
        free_hb = convex.mutation("fleet:heartbeat", {"workerSecret": ws, "userId": free_uid})
        paid_hb = convex.mutation("fleet:heartbeat", {"workerSecret": ws, "userId": paid_uid})
        assert free_hb["desired"] == "stopped", f"free instance not reaped: {free_hb}"
        assert paid_hb["desired"] == "running", f"paid instance was reaped: {paid_hb}"
    finally:
        _cleanup(convex, ws, seed)
