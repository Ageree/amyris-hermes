"""Worker scoped claim routing (M6). Network-free.

Proves process_one's claim-path selection:

  1. A scoped worker (cfg.scoped_user_id="u_alice") uses messages:claimNextForUser
     with userId="u_alice" — NEVER the global messages:claimNext.
  2. The claimed row is processed and a reply is delivered to its replyTarget.
  3. A legacy worker (no scoped_user_id) still uses messages:claimNext.

Uses the FakeConvex name-dispatch pattern from test_worker_quota.py.
All non-claim sidechannels (quota, history, typing, heartbeat) are disabled via
WorkerConfig flags so the test isolates the claim path.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import WorkerConfig, process_one  # noqa: E402


def _cfg(**over) -> WorkerConfig:
    base = dict(
        convex_url="https://dep.convex.cloud",
        worker_secret="ws",
        sendblue_key_id="k",
        sendblue_secret="s",
        sendblue_from="+1999",
        reply_target="+1555",
        hermes_home="/h",
        hermes_dir="/d",
        python_bin="/p",
        poll_interval=0.01,
        hermes_timeout=60.0,
        # Isolate the claim path from side-channel calls:
        quota_enabled=False,
        history_enabled=False,
        typing_enabled=False,
        heartbeat_enabled=False,
    )
    base.update(over)
    return WorkerConfig(**base)


def _claim(**over) -> dict:
    base = {
        "id": "m42",
        "handle": "h42",
        "userNumber": "+1U",
        "userId": "u_alice",
        "channel": "imessage",
        "replyTarget": "+1U",
        "text": "hello",
        "mediaUrl": None,
    }
    base.update(over)
    return base


class FakeConvex:
    """Routes mutation/query by path name. Records all calls."""

    def __init__(self, claim=None):
        self.calls: list = []
        self._claim = claim

    def mutation(self, path: str, args: dict):
        self.calls.append((path, args))
        if path in ("messages:claimNext", "messages:claimNextForUser", "messages:claimNextAny"):
            return self._claim
        return None

    def query(self, path: str, args: dict):
        self.calls.append((path, args))
        return []

    def names(self) -> list:
        return [p for p, _ in self.calls]

    def args_for(self, path: str) -> dict:
        return next(a for p, a in self.calls if p == path)


# ---------------------------------------------------------------------------
# 1. Scoped worker uses claimNextForUser with the right userId
# ---------------------------------------------------------------------------

def test_scoped_worker_uses_claim_next_for_user():
    """A scoped worker calls claimNextForUser (not claimNext) with the tenant userId."""
    convex = FakeConvex(claim=_claim())
    client = MagicMock()
    run_fn = MagicMock(return_value="the answer")

    did = process_one(
        convex, client,
        _cfg(scoped_user_id="u_alice"),
        run_fn=run_fn,
    )

    assert did is True
    names = convex.names()
    assert "messages:claimNextForUser" in names, "expected claimNextForUser call"
    assert "messages:claimNext" not in names, "global claimNext must NOT be used in scoped mode"

    sent = convex.args_for("messages:claimNextForUser")
    assert sent["userId"] == "u_alice"
    assert sent["workerSecret"] == "ws"


# ---------------------------------------------------------------------------
# 2. Claimed row is processed and reply reaches its replyTarget
# ---------------------------------------------------------------------------

def test_scoped_worker_reply_goes_to_claim_reply_target():
    """Reply is delivered to the claimed row's replyTarget, not a hard-coded constant."""
    convex = FakeConvex(claim=_claim(replyTarget="+1Alice"))
    client = MagicMock()
    run_fn = MagicMock(return_value="scoped reply")

    process_one(
        convex, client,
        _cfg(scoped_user_id="u_alice"),
        run_fn=run_fn,
    )

    # run_fn was called (the message was processed)
    run_fn.assert_called_once()
    # The channel send must go to +1Alice (the row's replyTarget), not cfg.reply_target (+1555)
    assert client.send_message.called
    call_args = client.send_message.call_args
    # send_message(address, text) positional or keyword
    target = call_args[0][0] if call_args[0] else call_args[1].get("address") or call_args[1].get("to_number")
    assert target == "+1Alice", f"reply went to {target!r} instead of +1Alice"


# ---------------------------------------------------------------------------
# 3. Legacy worker uses claimNext (no scoped_user_id)
# ---------------------------------------------------------------------------

def test_legacy_worker_uses_global_claim_next():
    """A legacy worker (no scoped_user_id) uses messages:claimNext."""
    convex = FakeConvex(claim=_claim(userId=None))
    client = MagicMock()
    run_fn = MagicMock(return_value="legacy reply")

    did = process_one(
        convex, client,
        _cfg(scoped_user_id=""),
        run_fn=run_fn,
    )

    assert did is True
    names = convex.names()
    assert "messages:claimNext" in names, "expected global claimNext for legacy mode"
    assert "messages:claimNextForUser" not in names, "scoped claim must NOT be used in legacy mode"


# ---------------------------------------------------------------------------
# 4. Scoped worker with empty queue returns False
# ---------------------------------------------------------------------------

def test_scoped_worker_empty_queue_returns_false():
    """When claimNextForUser returns None (empty queue), process_one returns False."""
    convex = FakeConvex(claim=None)
    client = MagicMock()
    run_fn = MagicMock()

    did = process_one(
        convex, client,
        _cfg(scoped_user_id="u_alice"),
        run_fn=run_fn,
    )

    assert did is False
    run_fn.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Shared "bridge" worker uses claimNextAny across all tenants
# ---------------------------------------------------------------------------

def test_shared_worker_uses_claim_next_any():
    """WORKER_MODE=shared claims via claimNextAny (no userId) — never the scoped or
    legacy claim — so ONE worker drains every tenant's queue."""
    convex = FakeConvex(claim=_claim(userId="u_bob", replyTarget="+1Bob"))
    client = MagicMock()
    run_fn = MagicMock(return_value="bridged reply")

    did = process_one(
        convex, client,
        _cfg(worker_mode="shared"),
        run_fn=run_fn,
    )

    assert did is True
    names = convex.names()
    assert "messages:claimNextAny" in names, "expected claimNextAny in shared mode"
    assert "messages:claimNext" not in names, "global legacy claim must NOT be used in shared mode"
    assert "messages:claimNextForUser" not in names, "scoped claim must NOT be used in shared mode"

    sent = convex.args_for("messages:claimNextAny")
    assert sent == {"workerSecret": "ws"}, "shared claim takes ONLY workerSecret (no userId)"


def test_shared_mode_overrides_stray_scoped_user_id():
    """shared is checked first, so an accidental USER_ID does not silently route to
    the per-tenant claim — explicit WORKER_MODE=shared wins."""
    convex = FakeConvex(claim=_claim())
    client = MagicMock()
    run_fn = MagicMock(return_value="ok")

    process_one(
        convex, client,
        _cfg(worker_mode="shared", scoped_user_id="u_alice"),
        run_fn=run_fn,
    )

    names = convex.names()
    assert "messages:claimNextAny" in names
    assert "messages:claimNextForUser" not in names


def test_shared_worker_reply_goes_to_claim_reply_target():
    """A shared worker still routes each reply to the CLAIMED row's own replyTarget
    (per-message A2), so cross-tenant claiming never crosses a reply."""
    convex = FakeConvex(claim=_claim(userId="u_carol", replyTarget="+1Carol"))
    client = MagicMock()
    run_fn = MagicMock(return_value="carol reply")

    process_one(
        convex, client,
        _cfg(worker_mode="shared"),
        run_fn=run_fn,
    )

    assert client.send_message.called
    call_args = client.send_message.call_args
    target = call_args[0][0] if call_args[0] else call_args[1].get("address") or call_args[1].get("to_number")
    assert target == "+1Carol", f"reply went to {target!r} instead of +1Carol"
