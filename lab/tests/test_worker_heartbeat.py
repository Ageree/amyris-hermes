"""Fleet heartbeat integration in the worker (M6). Network-free.

Tests the _maybe_heartbeat helper and its integration into run_loop:

  1. In scoped mode (scoped_user_id set), heartbeat fires once per iteration.
  2. In legacy mode (no scoped_user_id), heartbeat is never called.
  3. A heartbeat that raises does NOT crash the loop (fail-soft / swallowed).
  4. HEARTBEAT_ENABLED=False (heartbeat_enabled=False) bypasses the call entirely.

Uses the FakeConvex name-dispatch pattern from test_worker_quota.py.
`_maybe_heartbeat` is the recommended seam (unit-testable without run_loop).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import WorkerConfig, _maybe_heartbeat  # noqa: E402


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
        history_enabled=False,
        quota_enabled=False,
        typing_enabled=False,
        heartbeat_enabled=True,
    )
    base.update(over)
    return WorkerConfig(**base)


class FakeConvex:
    """Routes mutation/query by path name; records all calls."""

    def __init__(self, heartbeat_result=None):
        self.calls: list = []
        self._heartbeat_result = heartbeat_result

    def mutation(self, path: str, args: dict):
        self.calls.append((path, args))
        if path == "fleet:heartbeat":
            r = self._heartbeat_result
            if isinstance(r, BaseException):
                raise r
            return r
        # Default for claim/complete/fail/etc.
        return None

    def query(self, path: str, args: dict):
        self.calls.append((path, args))
        return []

    def names(self) -> list:
        return [p for p, _ in self.calls]

    def args_for(self, path: str) -> dict:
        return next(a for p, a in self.calls if p == path)


# ---------------------------------------------------------------------------
# 1. Scoped mode: heartbeat fires with correct userId
# ---------------------------------------------------------------------------

def test_scoped_heartbeat_fires_with_user_id():
    """In scoped mode, _maybe_heartbeat calls fleet:heartbeat with the right userId."""
    convex = FakeConvex(heartbeat_result={"desired": "running"})
    cfg = _cfg(scoped_user_id="u_alice")

    _maybe_heartbeat(convex, cfg)

    assert "fleet:heartbeat" in convex.names(), "fleet:heartbeat was not called"
    sent_args = convex.args_for("fleet:heartbeat")
    assert sent_args["userId"] == "u_alice"
    assert sent_args["workerSecret"] == "ws"


# ---------------------------------------------------------------------------
# 2. Legacy mode: heartbeat is NOT called when no scoped_user_id
# ---------------------------------------------------------------------------

def test_legacy_heartbeat_not_called():
    """In legacy mode (no scoped_user_id), _maybe_heartbeat does nothing."""
    convex = FakeConvex()
    cfg = _cfg(scoped_user_id="")

    _maybe_heartbeat(convex, cfg)

    assert "fleet:heartbeat" not in convex.names()


# ---------------------------------------------------------------------------
# 3. Heartbeat that raises does NOT propagate (fail-soft)
# ---------------------------------------------------------------------------

def test_heartbeat_exception_is_swallowed():
    """A crashing heartbeat must not raise out of _maybe_heartbeat."""
    convex = FakeConvex(heartbeat_result=RuntimeError("convex unreachable"))
    cfg = _cfg(scoped_user_id="u_bob")

    # Must not raise:
    result = _maybe_heartbeat(convex, cfg)
    assert result is None  # fail-soft returns None


# ---------------------------------------------------------------------------
# 4. heartbeat_enabled=False bypasses the call
# ---------------------------------------------------------------------------

def test_heartbeat_disabled_bypasses_call():
    """HEARTBEAT_ENABLED=0 / heartbeat_enabled=False skips the fleet call."""
    convex = FakeConvex(heartbeat_result={"desired": "running"})
    cfg = _cfg(scoped_user_id="u_carol", heartbeat_enabled=False)

    _maybe_heartbeat(convex, cfg)

    assert "fleet:heartbeat" not in convex.names()


# ---------------------------------------------------------------------------
# 5. "stopped" desired state is returned and logged (no crash)
# ---------------------------------------------------------------------------

def test_heartbeat_stopped_desired_returns_value():
    """A 'stopped' desired response is returned without crashing."""
    convex = FakeConvex(heartbeat_result={"desired": "stopped"})
    cfg = _cfg(scoped_user_id="u_dave")

    result = _maybe_heartbeat(convex, cfg)

    assert result == "stopped"
