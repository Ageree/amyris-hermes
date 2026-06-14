"""CONVEX-INTEGRATION: quota gate (M5, design §6).

Drives the REAL quota.ts mutations against the dev deployment to prove the
atomic reserve + deny semantics that mocks can't catch (a wrong index, a
return-validator drift, the read-modify-write race). Auto-skipped unless
RUN_CONVEX_E2E=1 (+ CONVEX_URL / WORKER_SECRET; dev has ALLOW_TEST_SEED=1).

Each test seeds a throwaway tenant, sets a deterministic entitlement via the
double-gated testing:testSetEntitlement wrapper, then exercises checkAndReserve /
releaseReserve and asserts the verdicts. Teardown reaps the tenant (incl. its
entitlement + usage rows).

Run: `RUN_CONVEX_E2E=1 CONVEX_URL=... WORKER_SECRET=... python3 -m pytest -q \
      lab/tests/test_entitlement_quota.py`
"""
from __future__ import annotations

import os
import uuid

import pytest

from convex_client import ConvexClient

pytestmark = pytest.mark.convex_e2e


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


def _set_entitlement(convex, ws, user_id, *, tier, msg_quota, msg_used, status=None):
    args = {"workerSecret": ws, "userId": user_id, "tier": tier,
            "msgQuota": msg_quota, "msgUsed": msg_used}
    if status is not None:
        args["status"] = status
    return convex.mutation("testing:testSetEntitlement", args)


def _reserve(convex, ws, user_id):
    return convex.mutation("quota:checkAndReserve", {"workerSecret": ws, "userId": user_id})


def _release(convex, ws, user_id):
    return convex.mutation("quota:releaseReserve", {"workerSecret": ws, "userId": user_id})


def _record(convex, ws, user_id):
    return convex.mutation("quota:recordUsage",
                           {"workerSecret": ws, "userId": user_id, "units": 1, "lane": "hermes"})


def _tag():
    return "quota-" + uuid.uuid4().hex[:8]


def test_over_quota_blocks_run():
    """The acceptance keystone: a free user at the cap is denied with over_quota."""
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag())
    try:
        uid = seed["userA"]
        _set_entitlement(convex, ws, uid, tier="free", msg_quota=1, msg_used=0)
        first = _reserve(convex, ws, uid)
        assert first["allowed"] is True
        assert first["remaining"] == 0
        second = _reserve(convex, ws, uid)
        assert second["allowed"] is False
        assert second["reason"] == "over_quota"
        assert second["remaining"] == 0
    finally:
        _cleanup(convex, ws, seed)


def test_reserve_allows_up_to_quota_then_denies():
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag())
    try:
        uid = seed["userA"]
        _set_entitlement(convex, ws, uid, tier="pro", msg_quota=3, msg_used=0)
        remaining = [r["allowed"] for r in (_reserve(convex, ws, uid) for _ in range(3))]
        assert remaining == [True, True, True]
        denied = _reserve(convex, ws, uid)
        assert denied["allowed"] is False
        assert denied["reason"] == "over_quota"
    finally:
        _cleanup(convex, ws, seed)


def test_unlimited_operator_never_blocked():
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag())
    try:
        uid = seed["userA"]
        # msgQuota = -1 (operator sentinel) -> always allowed, never incremented.
        _set_entitlement(convex, ws, uid, tier="max", msg_quota=-1, msg_used=0)
        for _ in range(5):
            r = _reserve(convex, ws, uid)
            assert r["allowed"] is True
            assert r["remaining"] == -1
    finally:
        _cleanup(convex, ws, seed)


def test_canceled_entitlement_is_denied():
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag())
    try:
        uid = seed["userA"]
        _set_entitlement(convex, ws, uid, tier="pro", msg_quota=100, msg_used=0, status="canceled")
        r = _reserve(convex, ws, uid)
        assert r["allowed"] is False
        assert r["reason"] == "canceled"
    finally:
        _cleanup(convex, ws, seed)


def test_release_refunds_a_reserved_unit():
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag())
    try:
        uid = seed["userA"]
        _set_entitlement(convex, ws, uid, tier="free", msg_quota=2, msg_used=0)
        first = _reserve(convex, ws, uid)
        assert first["allowed"] is True and first["remaining"] == 1
        rel = _release(convex, ws, uid)
        assert rel["released"] is True
        # After the refund the next reserve sees the SAME headroom as the first.
        again = _reserve(convex, ws, uid)
        assert again["allowed"] is True and again["remaining"] == 1
    finally:
        _cleanup(convex, ws, seed)


def test_no_entitlement_is_denied():
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag())
    try:
        # seedTwoTenants creates users WITHOUT an entitlement -> clean no_entitlement deny.
        r = _reserve(convex, ws, seed["userB"])
        assert r["allowed"] is False
        assert r["reason"] == "no_entitlement"
    finally:
        _cleanup(convex, ws, seed)


def test_record_usage_after_reserve_succeeds():
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag())
    try:
        uid = seed["userA"]
        _set_entitlement(convex, ws, uid, tier="free", msg_quota=10, msg_used=0)
        assert _reserve(convex, ws, uid)["allowed"] is True
        # recordUsage returns null on success (no raise == pass).
        assert _record(convex, ws, uid) is None
    finally:
        _cleanup(convex, ws, seed)
