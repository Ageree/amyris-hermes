"""Graceful-shutdown tests for the worker (Bug H3). Network-free.

On `docker stop` (idle-reap / relaunch) the worker must drain cleanly instead of
being SIGKILLed mid-turn:

  1. A SIGTERM/SIGINT sets a module stop flag (threading.Event).
  2. run_loop checks it: it finishes the CURRENT process_one if one is in flight,
     stops claiming NEW work, then exits 0.
  3. A heartbeat result of desired="stopped" also begins draining (same flag).
  4. Signal handling is FAIL-SOFT and the legacy (no-fleet) path still works.
"""
from __future__ import annotations

import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import worker  # noqa: E402
from worker import WorkerConfig, run_loop  # noqa: E402


def _cfg(**over) -> WorkerConfig:
    base = dict(
        convex_url="https://dep.convex.cloud", worker_secret="ws",
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target="+1555", hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0,
        history_enabled=False, quota_enabled=False, typing_enabled=False,
        heartbeat_enabled=False,
    )
    base.update(over)
    return WorkerConfig(**base)


@pytest.fixture(autouse=True)
def _reset_stop_flag():
    """Each test starts with a clear stop flag and restores it afterward."""
    worker.clear_stop()
    yield
    worker.clear_stop()


# ---------------------------------------------------------------------------
# 1. Stop flag set BEFORE the loop -> no work is ever claimed.
# ---------------------------------------------------------------------------

def test_stop_flag_set_before_loop_claims_nothing():
    worker.request_stop()
    process_fn = MagicMock(return_value=True)
    sleep_fn = MagicMock()
    run_loop(_cfg(), convex=MagicMock(), sendblue=MagicMock(),
             process_fn=process_fn, intent_fn=None, sleep_fn=sleep_fn,
             max_iterations=5)
    process_fn.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Stop flag set DURING a turn -> the in-flight turn completes, then the loop
#    exits without claiming further work.
# ---------------------------------------------------------------------------

def test_stop_during_turn_finishes_current_then_exits():
    calls = {"n": 0}

    def process_fn(convex, channels, cfg):
        calls["n"] += 1
        # Simulate the stop signal arriving WHILE this turn runs.
        worker.request_stop()
        return True  # this message was handled

    sleep_fn = MagicMock()
    run_loop(_cfg(), convex=MagicMock(), sendblue=MagicMock(),
             process_fn=process_fn, intent_fn=None, sleep_fn=sleep_fn,
             max_iterations=10)
    # The in-flight turn ran exactly once; no further claims after stop.
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# 3. heartbeat desired="stopped" begins draining -> no further claims.
# ---------------------------------------------------------------------------

def test_heartbeat_stopped_begins_drain():
    calls = {"n": 0}

    def process_fn(convex, channels, cfg):
        calls["n"] += 1
        return True

    # _maybe_heartbeat returns "stopped" -> run_loop must set the stop flag.
    import unittest.mock as mock
    with mock.patch.object(worker, "_maybe_heartbeat", return_value="stopped"):
        run_loop(_cfg(heartbeat_enabled=True, scoped_user_id="u1"),
                 convex=MagicMock(), sendblue=MagicMock(),
                 process_fn=process_fn, intent_fn=None,
                 sleep_fn=MagicMock(), max_iterations=10)
    # At most ONE claim (the iteration that observed the stopped desired drains
    # immediately); definitely not all 10 iterations.
    assert calls["n"] <= 1


# ---------------------------------------------------------------------------
# 4. The signal handler is fail-soft and sets the flag.
# ---------------------------------------------------------------------------

def test_signal_handler_sets_stop_flag():
    assert not worker.should_stop()
    # Invoke the handler directly (don't actually raise a process signal).
    worker._handle_stop_signal(signal.SIGTERM, None)
    assert worker.should_stop()


def test_install_signal_handlers_is_failsoft(monkeypatch):
    """If signal.signal raises (e.g. called off the main thread), installation
    must NOT propagate — the worker keeps running."""
    def boom(*a, **k):
        raise ValueError("signal only works in main thread")

    monkeypatch.setattr(worker.signal, "signal", boom)
    # Must not raise:
    worker._install_signal_handlers()


# ---------------------------------------------------------------------------
# 5. Legacy (no-fleet) path still works: normal poll/sleep when not stopping.
# ---------------------------------------------------------------------------

def test_legacy_loop_unaffected_when_no_stop():
    process_fn = MagicMock(side_effect=[True, False])
    sleep_fn = MagicMock()
    run_loop(_cfg(), convex=MagicMock(), sendblue=MagicMock(),
             process_fn=process_fn, intent_fn=None, sleep_fn=sleep_fn,
             max_iterations=2)
    assert process_fn.call_count == 2
    sleep_fn.assert_called_once_with(0.01)
