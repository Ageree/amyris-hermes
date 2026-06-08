"""Tests for the typing-indicator keepalive.

Fires are owned by the daemon thread (so they never block the reply path), so the
tests synchronize on `wait_first_fire()` / a bounded poll instead of assuming a
synchronous first fire. interval=60 keeps the timed re-fire from interfering.
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from typing_indicator import TypingKeepalive  # noqa: E402


def _states(sendblue):
    return [c.kwargs.get("state") for c in sendblue.send_typing.call_args_list]


def _wait_until(pred, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def test_start_fires_one_start():
    sb = MagicMock()
    t = TypingKeepalive(sb, "+1555", interval=60.0)
    t.start()
    try:
        assert t.wait_first_fire(2.0)  # thread fires "start" ASAP, off the caller
        first = sb.send_typing.call_args_list[0]
        assert first.args[0] == "+1555"
        assert first.kwargs["state"] == "start"
        assert first.kwargs["max_duration_ms"] == 10000
    finally:
        t.stop()


def test_stop_joins_thread_and_sends_stop():
    sb = MagicMock()
    t = TypingKeepalive(sb, "+1555", interval=60.0)
    t.start()
    t.wait_first_fire(2.0)
    t.stop()
    assert _states(sb)[-1] == "stop"  # last call clears the indicator


def test_poke_refires_start():
    sb = MagicMock()
    t = TypingKeepalive(sb, "+1555", interval=60.0)
    t.start()
    assert t.wait_first_fire(2.0)
    n_before = sb.send_typing.call_count
    t.poke()  # async: thread re-fires "start"
    assert _wait_until(lambda: sb.send_typing.call_count == n_before + 1)
    assert _states(sb)[-1] == "start"
    t.stop()


def test_disabled_does_nothing():
    sb = MagicMock()
    t = TypingKeepalive(sb, "+1555", enabled=False)
    t.start()
    t.poke()
    t.stop()
    sb.send_typing.assert_not_called()


def test_empty_number_disables():
    sb = MagicMock()
    t = TypingKeepalive(sb, "", interval=60.0)
    t.start()
    t.stop()
    sb.send_typing.assert_not_called()


def test_errors_are_swallowed():
    sb = MagicMock()
    sb.send_typing.side_effect = RuntimeError("sendblue down")
    t = TypingKeepalive(sb, "+1555", interval=60.0)
    # none of these may raise
    t.start()
    t.wait_first_fire(2.0)
    t.poke()
    t.stop()


def test_context_manager_starts_and_stops():
    sb = MagicMock()
    with TypingKeepalive(sb, "+1555", interval=60.0) as t:
        assert t.wait_first_fire(2.0)  # ensure "start" lands before "stop"
    states = _states(sb)
    assert states[0] == "start"
    assert states[-1] == "stop"


def test_stop_without_start_is_noop():
    sb = MagicMock()
    t = TypingKeepalive(sb, "+1555")
    t.stop()  # never started
    sb.send_typing.assert_not_called()


def test_poke_after_stop_does_not_refire_start():
    # the check-then-fire race: a poke landing after stop must NOT re-show "…"
    sb = MagicMock()
    t = TypingKeepalive(sb, "+1555", interval=60.0)
    t.start()
    assert t.wait_first_fire(2.0)
    t.stop()
    n = sb.send_typing.call_count
    t.poke()  # no-op now — stop event is set
    # give any errant fire a chance to (not) happen, then assert nothing changed
    assert not _wait_until(lambda: sb.send_typing.call_count != n, 0.3)
    assert sb.send_typing.call_count == n
    assert _states(sb)[-1] == "stop"


def test_double_start_fires_once():
    sb = MagicMock()
    t = TypingKeepalive(sb, "+1555", interval=60.0)
    t.start()
    t.start()  # idempotent
    assert t.wait_first_fire(2.0)
    starts = [s for s in _states(sb) if s == "start"]
    assert len(starts) == 1
    t.stop()
