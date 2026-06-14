"""CONVEX-INTEGRATION: pairing-token safety (M4).

Proves the four pairing invariants (design §7) against a REAL dev Convex
deployment, driving the EXACT issue/redeem impls through the double-gated
testing:* wrappers over the public HTTP API (auto-skipped unless RUN_CONVEX_E2E=1):

  1. single-use      — a consumed token can't bind a second/different address
                       (re-tap by the same owner+address is an idempotent no-op).
  2. expiring        — a back-dated (TTL-elapsed) token is rejected.
  3. channel-checked — a telegram token can't be redeemed on the imessage path
                       (and vice-versa), even though the row carries both token+code.
  4. cross-user      — binding an external id already owned by ANOTHER user is
                       REJECTED (tenant-hijack guard).

Why a real deployment: mocked unit tests can't catch a wrong index name, a
return-validator drift, or the check-then-bind race. Seeding uses
testing:seedTwoTenants (WORKER_SECRET + dev-only ALLOW_TEST_SEED=1); each test
cleans up its throwaway tenants (which reaps their pairingTokens + channelBindings).

Run: `RUN_CONVEX_E2E=1 CONVEX_URL=... WORKER_SECRET=... python3 -m pytest -q \
      lab/tests/test_pairing.py`
"""
from __future__ import annotations

import os
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


def _mint(convex, ws, user_id, channel):
    return convex.mutation(
        "testing:testIssuePairing",
        {"workerSecret": ws, "userId": user_id, "channel": channel})


def _redeem_tg(convex, ws, token, address):
    return convex.mutation(
        "testing:testRedeemTelegram",
        {"workerSecret": ws, "token": token, "address": address})


def _redeem_im(convex, ws, code, address):
    return convex.mutation(
        "testing:testRedeemImessage",
        {"workerSecret": ws, "code": code, "address": address})


def _addr(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


@pytest.mark.convex_e2e
def test_telegram_token_is_single_use():
    convex, ws = _ctx()
    seed = _seed(convex, ws, f"pair-su-{uuid.uuid4().hex[:8]}")
    try:
        addr = _addr("tg")
        t = _mint(convex, ws, seed["userA"], "telegram")

        first = _redeem_tg(convex, ws, t["token"], addr)
        assert first["ok"] is True and first["userId"] == seed["userA"]

        # Re-tap by the SAME owner+address -> idempotent no-op (not a 2nd binding).
        again = _redeem_tg(convex, ws, t["token"], addr)
        assert again["ok"] is True and again.get("idempotent") is True

        # The consumed token cannot bind a DIFFERENT address.
        other = _redeem_tg(convex, ws, t["token"], _addr("tg"))
        assert other["ok"] is False and other.get("reason") == "already_consumed"
    finally:
        _cleanup(convex, ws, seed)


@pytest.mark.convex_e2e
def test_expired_token_is_rejected():
    convex, ws = _ctx()
    seed = _seed(convex, ws, f"pair-exp-{uuid.uuid4().hex[:8]}")
    try:
        t = _mint(convex, ws, seed["userA"], "telegram")
        # Back-date it past its TTL, then attempt to redeem.
        convex.mutation("testing:testExpirePairing", {"workerSecret": ws, "token": t["token"]})
        res = _redeem_tg(convex, ws, t["token"], _addr("tg"))
        assert res["ok"] is False and res.get("reason") == "expired"
    finally:
        _cleanup(convex, ws, seed)


@pytest.mark.convex_e2e
def test_wrong_channel_is_rejected():
    convex, ws = _ctx()
    seed = _seed(convex, ws, f"pair-ch-{uuid.uuid4().hex[:8]}")
    try:
        # A telegram token carries a code too, but it must NOT redeem on imessage.
        tg = _mint(convex, ws, seed["userA"], "telegram")
        im_attempt = _redeem_im(convex, ws, tg["code"], _addr("+1"))
        assert im_attempt["ok"] is False and im_attempt.get("reason") == "not_found"

        # And an imessage token must NOT redeem on telegram.
        im = _mint(convex, ws, seed["userA"], "imessage")
        tg_attempt = _redeem_tg(convex, ws, im["token"], _addr("tg"))
        assert tg_attempt["ok"] is False and tg_attempt.get("reason") == "not_found"
    finally:
        _cleanup(convex, ws, seed)


@pytest.mark.convex_e2e
def test_cross_user_address_is_rejected():
    convex, ws = _ctx()
    seed = _seed(convex, ws, f"pair-xu-{uuid.uuid4().hex[:8]}")
    try:
        addr = _addr("tg")
        # User A binds the address first.
        ta = _mint(convex, ws, seed["userA"], "telegram")
        bound = _redeem_tg(convex, ws, ta["token"], addr)
        assert bound["ok"] is True and bound["userId"] == seed["userA"]

        # User B mints a fresh token and tries to claim the SAME address -> reject.
        tb = _mint(convex, ws, seed["userB"], "telegram")
        hijack = _redeem_tg(convex, ws, tb["token"], addr)
        assert hijack["ok"] is False and hijack.get("reason") == "address_taken"
    finally:
        _cleanup(convex, ws, seed)


@pytest.mark.convex_e2e
def test_bogus_token_is_not_found():
    convex, ws = _ctx()
    res = _redeem_tg(convex, ws, "this-token-does-not-exist", _addr("tg"))
    assert res["ok"] is False and res.get("reason") == "not_found"
