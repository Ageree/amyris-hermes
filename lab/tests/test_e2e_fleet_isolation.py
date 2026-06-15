"""CONVEX-INTEGRATION (M7): full-worker fleet isolation against REAL dev Convex.

Drives the ACTUAL worker (process_one) and the live messages:* / fleet seam over
the public HTTP API exactly as a scoped fleet container would — proving the
per-tenant invariants end-to-end, not via mocks:

  - test_no_cross_talk          two scoped workers each reply ONLY to their own
                                tenant's address; zero cross-contamination.
  - test_history_isolation      recentForUser(A) excludes B's turns.
  - test_duplicate_webhook_one_row  a duplicated (channel,handle) dedups to ONE row
                                via the live by_channel_handle index.
  - test_cold_start_drains      a row enqueued with NO worker running is drained
                                once a (freshly constructed) worker starts.

Auto-skipped unless RUN_CONVEX_E2E=1 (+ CONVEX_URL / WORKER_SECRET; the dev
deployment sets ALLOW_TEST_SEED=1). Every test seeds THROWAWAY tenants
(tt-*@test.invalid) via the double-gated testing:* seams and reaps them in a
finally — it never touches the operator's rows, and the scoped workers use
claimNextForUser (NEVER the global claimNext), so they can't steal operator mail.

Run: `RUN_CONVEX_E2E=1 CONVEX_URL=... WORKER_SECRET=... python3 -m pytest -q \
      lab/tests/test_e2e_fleet_isolation.py`
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import WorkerConfig, process_one  # noqa: E402
from channels import ChannelRegistry  # noqa: E402
from convex_client import ConvexClient  # noqa: E402

from conftest import RecordingChannel  # noqa: E402

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


def _tag(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _cfg(convex_url, ws, user_id):
    """A scoped worker config pinned to one tenant. Quota/heartbeat/history/fast
    lane are OFF so the test isolates ROUTING (their own e2e tests cover them);
    the reply text comes from an injected run_fn, not a real model."""
    return WorkerConfig(
        convex_url=convex_url, worker_secret=ws,
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target="+1OPERATOR_SHOULD_NEVER_BE_USED",
        hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0,
        scoped_user_id=user_id,
        typing_enabled=False, quota_enabled=False,
        heartbeat_enabled=False, history_enabled=False, fast_lane_enabled=False,
    )


# Sent by the worker when a turn fails (e.g. a transient complete-mutation error
# on the shared dev deployment) — distinguishable from a real reply so the retry
# below doesn't accept a degraded turn.
_ERROR_REPLY = "Sorry — I hit an error processing that. Try again in a moment."


def _run_one(convex, ws, user_id, reply, attempts=6, delay=0.3):
    """Run the real worker scoped to `user_id` with a recording channel and a
    deterministic reply, retrying until it CLEANLY processes a row. Mirrors the
    worker's own poll loop so a read-after-write lag on the seed (or a rare
    transient on the shared dev deployment) doesn't flake the assertion. Returns
    (RecordingChannel, did) from the successful attempt (or the last attempt)."""
    cfg = _cfg(os.environ["CONVEX_URL"], ws, user_id)
    rec = RecordingChannel("imessage")
    did = False
    for _ in range(attempts):
        rec = RecordingChannel("imessage")
        registry = ChannelRegistry({"imessage": rec})
        # process_one claims (scoped) -> routes -> sends via rec -> completes on dev.
        did = process_one(convex, registry, cfg, run_fn=lambda *a, **k: reply)
        # A clean turn delivered the injected reply (not the error fallback).
        if did and rec.sends and all(body != _ERROR_REPLY for _, body in rec.sends):
            return rec, did
        time.sleep(delay)
    return rec, did


def test_no_cross_talk():
    """Two scoped workers, each replies ONLY to its own tenant's address."""
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag("xtalk"))
    try:
        rec_a, did_a = _run_one(convex, ws, seed["userA"], "reply for A")
        rec_b, did_b = _run_one(convex, ws, seed["userB"], "reply for B")

        assert did_a and did_b, "both scoped workers should have processed a row"
        assert rec_a.sends == [("+1A", "reply for A")], f"A misrouted: {rec_a.sends}"
        assert rec_b.sends == [("+1B", "reply for B")], f"B misrouted: {rec_b.sends}"
        # The decisive cross-talk checks: neither worker ever touched the other's
        # address, and neither fell back to the operator number.
        a_addrs = {addr for addr, _ in rec_a.sends}
        b_addrs = {addr for addr, _ in rec_b.sends}
        assert "+1B" not in a_addrs and "+1A" not in b_addrs, "cross-tenant reply!"
        assert all("OPERATOR" not in addr for addr in a_addrs | b_addrs)
    finally:
        _cleanup(convex, ws, seed)


def test_history_isolation():
    """recentForUser(A) returns A's own turn and EXCLUDES B's (no memory bleed)."""
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag("hist"))
    try:
        # Drain + complete both tenants' turns via the real scoped worker.
        _run_one(convex, ws, seed["userA"], "ack A")
        _run_one(convex, ws, seed["userB"], "ack B")

        recent_a = convex.query(
            "messages:recentForUser",
            {"workerSecret": ws, "userId": seed["userA"], "limit": 10}) or []
        blob = " ".join((r.get("text") or "") + " " + (r.get("reply") or "") for r in recent_a)
        assert seed["textA"] in blob, "A's own turn missing from its history"
        assert seed["textB"] not in blob, "B's turn bled into A's history!"
        assert "ack B" not in blob, "B's reply bled into A's history!"
    finally:
        _cleanup(convex, ws, seed)


def test_duplicate_webhook_one_row():
    """A duplicated (channel, handle) enqueue dedups to ONE row (live index)."""
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag("dup"))
    try:
        handle = f"dup-{uuid.uuid4().hex[:10]}"
        # NOTE: omit mediaUrl entirely — v.optional(v.string()) accepts an ABSENT
        # field or a string, but NOT null; the Python client would send None->null.
        args = {
            "workerSecret": ws, "handle": handle, "userId": seed["userA"],
            "channel": "imessage", "replyTarget": "+1A", "userNumber": "+1A",
            "text": "duplicate delivery",
        }
        first = convex.mutation("testing:testEnqueue", args)
        second = convex.mutation("testing:testEnqueue", args)
        assert first == second, "duplicate webhook created a SECOND row (idempotency broke)"
    finally:
        _cleanup(convex, ws, seed)


def test_cold_start_drains():
    """A row enqueued with NO worker running drains once a worker starts."""
    convex, ws = _ctx()
    seed = _seed(convex, ws, _tag("cold"))
    try:
        # Enqueue a COLD row for A (no worker is polling for it yet).
        handle = f"cold-{uuid.uuid4().hex[:10]}"
        convex.mutation("testing:testEnqueue", {
            "workerSecret": ws, "handle": handle, "userId": seed["userA"],
            "channel": "imessage", "replyTarget": "+1A", "userNumber": "+1A",
            "text": "queued before any worker",
        })
        # The seed also left an earlier queued row for A; drain both with a worker
        # that starts AFTER the rows already exist (the cold-start scenario).
        drained = []
        for _ in range(4):
            rec, did = _run_one(convex, ws, seed["userA"], "drained")
            if did and rec.sends:
                drained.extend(rec.sends)
            else:
                break
            time.sleep(0.1)
        assert drained, "a worker starting after enqueue must drain the cold queue"
        assert all(addr == "+1A" for addr, _ in drained), f"cold drain misrouted: {drained}"
    finally:
        _cleanup(convex, ws, seed)
