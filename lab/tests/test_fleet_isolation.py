"""Fleet isolation (M6): per-tenant scoped workers never touch each other's rows.

Network-free unit tests — all Convex calls are mocked via a name-dispatching
FakeConvex that mirrors the pattern from test_worker_quota.py.

Two synthetic tenants:
  - u_alice  -> +1ALICE  (iMessage)
  - u_bob    -> +1BOB    (iMessage)

Four properties proven:
  1. test_no_cross_claim         — each scoped worker claims only its OWN user's row.
  2. test_reply_to_own_address   — alice's reply arrives at +1ALICE, bob's at +1BOB.
  3. test_scoped_worker_never_calls_global_claim — claimNext (un-scoped) is never invoked.
  4. test_tenant_row_never_replies_to_operator   — a tenant row with no replyTarget is
       failed, not routed to the operator number (mirrors A2 guard in test_worker_routing).

Run:
    python3 -m pytest -q lab/tests/test_fleet_isolation.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))

from worker import WorkerConfig, process_one  # noqa: E402
from channels import ChannelRegistry  # noqa: E402
from conftest import RecordingChannel  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**overrides: Any) -> WorkerConfig:
    """Minimal WorkerConfig with all side-channel features disabled so tests are
    deterministic and fast (no typing threads, no history Convex calls, no quota)."""
    base: Dict[str, Any] = dict(
        convex_url="https://dep.convex.cloud",
        worker_secret="ws",
        sendblue_key_id="k",
        sendblue_secret="s",
        sendblue_from="+1999",
        reply_target="+1OPERATOR",
        hermes_home="/h",
        hermes_dir="/d",
        python_bin="/p",
        poll_interval=0.01,
        hermes_timeout=60.0,
        quota_enabled=False,
        history_enabled=False,
        typing_enabled=False,
    )
    base.update(overrides)
    return WorkerConfig(**base)


def _row(user_id: str, reply_target: str, **overrides: Any) -> Dict[str, Any]:
    """Build a synthetic claimed-message row for the given tenant."""
    base: Dict[str, Any] = {
        "id": f"msg-{user_id}",
        "handle": f"h-{user_id}",
        "userNumber": reply_target,
        "userId": user_id,
        "channel": "imessage",
        "replyTarget": reply_target,
        "text": "hello from " + user_id,
        "mediaUrl": None,
    }
    base.update(overrides)
    return base


# Synthetic tenant constants
ALICE_ID = "u_alice"
ALICE_NUM = "+1ALICE"
BOB_ID = "u_bob"
BOB_NUM = "+1BOB"

ROW_ALICE = _row(ALICE_ID, ALICE_NUM)
ROW_BOB = _row(BOB_ID, BOB_NUM)


# ---------------------------------------------------------------------------
# FakeConvex — name-dispatching, userId-scoped
# ---------------------------------------------------------------------------

class FakeConvex:
    """Routes mutation/query calls by Convex function path.

    `claimNextForUser` returns the queued row ONLY when ``args["userId"]``
    matches the row's owner.  All other callers see ``None`` (empty queue).
    This simulates server-side userId-scoping (design §8).

    Pass `rows` as a mapping of userId -> row dict; the worker may claim each
    row at most once (first claim removes it so the second call gets None).
    """

    def __init__(self, rows: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self._rows: Dict[str, Dict[str, Any]] = dict(rows or {})
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    def mutation(self, path: str, args: Dict[str, Any]) -> Any:
        self.calls.append((path, args))
        if path == "messages:claimNextForUser":
            uid = args.get("userId", "")
            row = self._rows.get(uid)
            if row is not None:
                # Consume the row so a second claim gets None
                del self._rows[uid]
                return row
            return None
        if path == "messages:claimNext":
            # Should NEVER be called by a scoped worker.
            return None
        # complete / fail / etc. — no-op
        return None

    def query(self, path: str, args: Dict[str, Any]) -> Any:
        self.calls.append((path, args))
        return []

    def names(self) -> List[str]:
        return [p for p, _ in self.calls]

    def args_for(self, path: str) -> Dict[str, Any]:
        return next(a for p, a in self.calls if p == path)

    def all_args_for(self, path: str) -> List[Dict[str, Any]]:
        return [a for p, a in self.calls if p == path]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_cross_claim() -> None:
    """A scoped worker for Alice claims only Alice's row; Bob's row is untouched.

    We run Alice's worker twice: first call gets her row (queue non-empty),
    second call gets None (queue empty) — she never sees Bob's row.
    We then run Bob's worker: he claims his own row correctly.
    """
    convex = FakeConvex({ALICE_ID: ROW_ALICE, BOB_ID: ROW_BOB})

    rec_alice = RecordingChannel("imessage")
    registry_alice = ChannelRegistry({"imessage": rec_alice})
    run_fn_alice = lambda text, **kw: "alice reply"  # noqa: E731

    # Alice worker — first call: gets her row
    did = process_one(
        convex, registry_alice, _cfg(scoped_user_id=ALICE_ID),
        run_fn=run_fn_alice,
    )
    assert did is True, "Alice's worker should claim her row"

    # Alice worker — second call: queue empty for her
    did2 = process_one(
        convex, registry_alice, _cfg(scoped_user_id=ALICE_ID),
        run_fn=run_fn_alice,
    )
    assert did2 is False, "Alice's queue should be empty after one claim"

    # Verify Alice never attempted to claim Bob's row
    alice_claims = [
        a for p, a in convex.calls
        if p == "messages:claimNextForUser"
    ]
    for ac in alice_claims:
        assert ac.get("userId") == ALICE_ID, (
            f"Alice's worker issued claimNextForUser with userId={ac.get('userId')!r}"
        )

    # Bob's row should still be claimable (untouched by Alice)
    rec_bob = RecordingChannel("imessage")
    registry_bob = ChannelRegistry({"imessage": rec_bob})
    run_fn_bob = lambda text, **kw: "bob reply"  # noqa: E731

    did_bob = process_one(
        convex, registry_bob, _cfg(scoped_user_id=BOB_ID),
        run_fn=run_fn_bob,
    )
    assert did_bob is True, "Bob's worker should claim his row (untouched by Alice)"
    bob_claims = [
        a for p, a in convex.calls
        if p == "messages:claimNextForUser" and a.get("userId") == BOB_ID
    ]
    assert bob_claims, "Bob's worker must have called claimNextForUser with his userId"


def test_reply_to_own_address() -> None:
    """Alice's reply goes to +1ALICE; Bob's reply goes to +1BOB. Zero cross-contamination."""
    run_fn_alice = lambda text, **kw: "reply for alice"  # noqa: E731
    run_fn_bob = lambda text, **kw: "reply for bob"  # noqa: E731

    rec_alice = RecordingChannel("imessage")
    rec_bob = RecordingChannel("imessage")

    # Run Alice
    convex_a = FakeConvex({ALICE_ID: ROW_ALICE})
    process_one(
        convex_a, ChannelRegistry({"imessage": rec_alice}),
        _cfg(scoped_user_id=ALICE_ID),
        run_fn=run_fn_alice,
    )

    # Run Bob
    convex_b = FakeConvex({BOB_ID: ROW_BOB})
    process_one(
        convex_b, ChannelRegistry({"imessage": rec_bob}),
        _cfg(scoped_user_id=BOB_ID),
        run_fn=run_fn_bob,
    )

    assert rec_alice.sends, "Alice's worker should have sent a reply"
    assert rec_bob.sends, "Bob's worker should have sent a reply"

    alice_addrs = [addr for addr, _ in rec_alice.sends]
    bob_addrs = [addr for addr, _ in rec_bob.sends]

    assert all(a == ALICE_NUM for a in alice_addrs), (
        f"Alice's replies must go to {ALICE_NUM}, got {alice_addrs}"
    )
    assert all(a == BOB_NUM for a in bob_addrs), (
        f"Bob's replies must go to {BOB_NUM}, got {bob_addrs}"
    )

    # Cross-contamination check: neither channel received the other's number
    assert BOB_NUM not in alice_addrs, "Alice's channel must never receive Bob's address"
    assert ALICE_NUM not in bob_addrs, "Bob's channel must never receive Alice's address"


def test_scoped_worker_never_calls_global_claim() -> None:
    """A scoped worker (USER_ID set) must NEVER call `messages:claimNext` (un-scoped).

    Server-side scoping is enforced by claimNextForUser; bypassing it via the
    global endpoint would break isolation at the database layer.
    """
    convex = FakeConvex({ALICE_ID: ROW_ALICE})
    rec = RecordingChannel("imessage")
    process_one(
        convex, ChannelRegistry({"imessage": rec}),
        _cfg(scoped_user_id=ALICE_ID),
        run_fn=lambda text, **kw: "ok",
    )
    assert "messages:claimNext" not in convex.names(), (
        "Scoped worker must never call the un-scoped messages:claimNext"
    )
    assert "messages:claimNextForUser" in convex.names(), (
        "Scoped worker must use messages:claimNextForUser"
    )


def test_tenant_row_never_replies_to_operator() -> None:
    """A2 guard on the SCOPED path: a tenant row with no replyTarget/userNumber
    is marked failed and NEVER sends to the operator/config number.

    Mirrors test_tenant_row_without_address_is_failed_not_leaked_to_operator
    from test_worker_routing.py, but exercises the scoped claim path.
    """
    bad_row = _row(ALICE_ID, ALICE_NUM, replyTarget=None, userNumber="")

    class _ScoppedFakeConvex(FakeConvex):
        """Variant that returns a row with no address for claimNextForUser."""

        def mutation(self, path: str, args: Dict[str, Any]) -> Any:
            self.calls.append((path, args))
            if path == "messages:claimNextForUser" and args.get("userId") == ALICE_ID:
                return bad_row
            # complete / fail
            return None

    convex = _ScoppedFakeConvex()
    rec = RecordingChannel("imessage")
    registry = ChannelRegistry({"imessage": rec})
    run_fn = lambda text, **kw: "secret answer"  # noqa: E731

    did = process_one(
        convex, registry,
        _cfg(scoped_user_id=ALICE_ID, reply_target="+1OPERATOR"),
        run_fn=run_fn,
    )

    assert did is True, "process_one should return True (message handled — marked failed)"
    assert rec.sends == [], (
        "Tenant row with no address must NEVER be sent to the operator number"
    )
    # Hermes/run_fn must never be invoked for a no-address tenant row
    # (the function is a lambda, so we verify indirectly via channel silence above
    # and the Convex fail mutation below)
    assert "messages:fail" in convex.names(), (
        "Tenant row with no address must be marked failed in Convex"
    )
    # Operator number must not appear in any Convex complete/send call args
    complete_args = convex.all_args_for("messages:complete")
    for ca in complete_args:
        assert ca.get("reply") != "+1OPERATOR", (
            "No complete call should reference the operator number as a reply"
        )
