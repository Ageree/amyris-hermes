"""Tests for the fleet controller reconcile logic.

All network / docker / gcloud calls are mocked via injected fakes.
"""
from __future__ import annotations

import time
from dataclasses import replace
from typing import Iterator

import pytest

from controller import (
    ControllerDeps,
    _decide,
    _do_launch,
    _do_relaunch,
    _do_stop,
    reconcile_once,
    run,
)


# ---------------------------------------------------------------------------
# _decide tests
# ---------------------------------------------------------------------------

class TestDecide:
    def _inst(self, **overrides) -> dict:
        base = {
            "userId": "u1",
            "instanceId": "inst1",
            "desired": "running",
            "status": "stopped",
            "containerId": None,
            "heartbeatAt": None,
            "lastActiveAt": None,
            "errorCount": 0,
        }
        base.update(overrides)
        return base

    def test_desired_running_status_stopped_no_container_is_launch(self, deps):
        inst = self._inst(desired="running", status="stopped", containerId=None)
        assert _decide(inst, deps) == "launch"

    def test_desired_running_status_provisioning_no_container_is_launch(self, deps):
        inst = self._inst(desired="running", status="provisioning", containerId=None)
        assert _decide(inst, deps) == "launch"

    def test_desired_running_status_error_no_container_is_launch(self, deps):
        inst = self._inst(desired="running", status="error", containerId=None)
        assert _decide(inst, deps) == "launch"

    def test_desired_running_status_running_no_heartbeat_is_relaunch(self, deps):
        inst = self._inst(desired="running", status="running", containerId="c1", heartbeatAt=None)
        assert _decide(inst, deps) == "relaunch"

    def test_desired_running_status_running_stale_heartbeat_is_relaunch(self, deps):
        # now_fn = 1_000_000.0 s, stale_ttl = 90 s -> anything older than 999_910_000 ms is stale
        stale_ms = (1_000_000.0 - 200) * 1000  # 200s ago → stale
        inst = self._inst(desired="running", status="running", containerId="c1", heartbeatAt=stale_ms)
        assert _decide(inst, deps) == "relaunch"

    def test_desired_running_status_running_fresh_heartbeat_is_noop(self, deps):
        fresh_ms = (1_000_000.0 - 10) * 1000  # 10s ago — within 90s TTL
        inst = self._inst(desired="running", status="running", containerId="c1", heartbeatAt=fresh_ms)
        assert _decide(inst, deps) == "noop"

    def test_desired_stopped_with_container_is_stop(self, deps):
        inst = self._inst(desired="stopped", status="running", containerId="c1")
        assert _decide(inst, deps) == "stop"

    def test_desired_stopped_no_container_is_noop(self, deps):
        inst = self._inst(desired="stopped", status="stopped", containerId=None)
        assert _decide(inst, deps) == "noop"


# ---------------------------------------------------------------------------
# Launch action tests
# ---------------------------------------------------------------------------

class TestDoLaunch:
    def _inst(self, **overrides) -> dict:
        base = {
            "userId": "u1",
            "instanceId": "inst1",
            "desired": "running",
            "status": "stopped",
            "containerId": None,
            "heartbeatAt": None,
            "errorCount": 0,
        }
        base.update(overrides)
        return base

    def test_launch_calls_docker_run(self, deps, fake_docker, fake_convex):
        result = _do_launch(self._inst(), deps)
        assert result["action"] == "launched"
        assert len(fake_docker.ran) == 1

    def test_launch_env_includes_user_id_and_scoped_mode(self, deps, fake_docker):
        _do_launch(self._inst(userId="user42"), deps)
        env = fake_docker.ran[0]["env"]
        assert env["USER_ID"] == "user42"
        assert env["WORKER_MODE"] == "scoped"

    def test_launch_env_excludes_allowed_user_number(self, deps, fake_docker):
        _do_launch(self._inst(), deps)
        env = fake_docker.ran[0]["env"]
        assert "ALLOWED_USER_NUMBER" not in env

    def test_launch_calls_claim_for_launch(self, deps, fake_convex):
        _do_launch(self._inst(userId="u1"), deps)
        assert len(fake_convex.claimed_calls) == 1
        assert fake_convex.claimed_calls[0]["userId"] == "u1"

    def test_launch_claim_false_stops_duplicate(self, deps, fake_docker, fake_convex):
        fake_convex.claim_returns = False
        result = _do_launch(self._inst(userId="u1"), deps)
        assert result["action"] == "launch_duplicate_stopped"
        # Container was started then stopped
        assert len(fake_docker.ran) == 1
        assert len(fake_docker.stopped) == 1

    def test_launch_docker_failure_increments_failure_count(self, deps, fake_docker):
        fake_docker.run_should_fail = True
        result = _do_launch(self._inst(userId="u1"), deps)
        assert result["action"] == "launch_failed"
        assert deps.failure_counts.get("u1", 0) == 1

    def test_launch_max_failures_calls_mark_error(self, deps, fake_docker, fake_convex):
        fake_docker.run_should_fail = True
        deps.failure_counts["u1"] = deps.cfg.max_launch_failures - 1
        _do_launch(self._inst(userId="u1"), deps)
        assert len(fake_convex.mark_error_calls) == 1
        assert fake_convex.mark_error_calls[0]["userId"] == "u1"

    def test_launch_rehydrates_state(self, deps, fake_state_sync):
        _do_launch(self._inst(userId="u1"), deps)
        assert "u1" in fake_state_sync.rehydrated

    def test_launch_ensures_worker_secret(self, deps, fake_secrets):
        _do_launch(self._inst(userId="u1"), deps)
        assert "u1" in fake_secrets.ensured

    def test_launch_secret_ref_in_env(self, deps, fake_docker):
        _do_launch(self._inst(userId="u1"), deps)
        env = fake_docker.ran[0]["env"]
        assert env.get("WORKER_SECRET_REF") == "hermes-worker-u1"

    def test_launch_mounts_user_dir(self, deps, fake_docker):
        _do_launch(self._inst(userId="u1"), deps)
        mounts = fake_docker.ran[0]["mounts"]
        assert any("u1" in m for m in mounts)


# ---------------------------------------------------------------------------
# Stop action tests
# ---------------------------------------------------------------------------

class TestDoStop:
    def _inst(self, **overrides) -> dict:
        base = {
            "userId": "u2",
            "instanceId": "inst2",
            "desired": "stopped",
            "status": "running",
            "containerId": "fakecid0001",
        }
        base.update(overrides)
        return base

    def test_stop_calls_docker_stop(self, deps, fake_docker):
        _do_stop(self._inst(), deps)
        assert len(fake_docker.stopped) == 1

    def test_stop_mirrors_state_after_stopping(self, deps, fake_state_sync, fake_docker):
        stop_order = []
        original_stop = fake_docker.stop
        original_mirror = fake_state_sync.mirror

        def recording_stop(name):
            stop_order.append("stop")
            return original_stop(name)

        def recording_mirror(uid):
            stop_order.append("mirror")
            return original_mirror(uid)

        fake_docker.stop = recording_stop
        fake_state_sync.mirror = recording_mirror

        _do_stop(self._inst(userId="u2"), deps)
        # stop must come before mirror
        assert stop_order.index("stop") < stop_order.index("mirror")

    def test_stop_calls_mark_stopped(self, deps, fake_convex):
        _do_stop(self._inst(userId="u2"), deps)
        assert "u2" in fake_convex.mark_stopped_calls

    def test_stop_result_action(self, deps):
        result = _do_stop(self._inst(userId="u2"), deps)
        assert result["action"] == "stopped"
        assert result["userId"] == "u2"


# ---------------------------------------------------------------------------
# Stale heartbeat / relaunch tests
# ---------------------------------------------------------------------------

class TestStaleRelaunch:
    def test_relaunch_stops_then_starts(self, deps, fake_docker):
        inst = {
            "userId": "u3",
            "instanceId": "inst3",
            "desired": "running",
            "status": "running",
            "containerId": "oldcid",
            "heartbeatAt": (1_000_000.0 - 200) * 1000,
            "errorCount": 0,
        }
        result = _do_relaunch(inst, deps)
        assert len(fake_docker.stopped) >= 1
        assert len(fake_docker.ran) == 1


# ---------------------------------------------------------------------------
# reconcile_once integration tests
# ---------------------------------------------------------------------------

class TestReconcileOnce:
    def test_reconcile_processes_launch_instance(self, deps, fake_convex, fake_docker):
        fake_convex._instances = [{
            "userId": "u1",
            "instanceId": "inst1",
            "desired": "running",
            "status": "stopped",
            "containerId": None,
            "heartbeatAt": None,
            "errorCount": 0,
        }]
        actions = reconcile_once(deps)
        assert any(a["action"] == "launched" for a in actions)

    def test_reconcile_processes_stop_instance(self, deps, fake_convex, fake_docker):
        fake_convex._instances = [{
            "userId": "u2",
            "instanceId": "inst2",
            "desired": "stopped",
            "status": "running",
            "containerId": "fakecid",
            "heartbeatAt": None,
            "errorCount": 0,
        }]
        actions = reconcile_once(deps)
        assert any(a["action"] == "stopped" for a in actions)

    def test_reconcile_noop_for_healthy_running(self, deps, fake_convex, fake_docker):
        fresh_ms = (1_000_000.0 - 10) * 1000
        fake_convex._instances = [{
            "userId": "u3",
            "instanceId": "inst3",
            "desired": "running",
            "status": "running",
            "containerId": "fakecid",
            "heartbeatAt": fresh_ms,
            "errorCount": 0,
        }]
        actions = reconcile_once(deps)
        assert len(actions) == 0   # noop produces no entries

    def test_reconcile_continues_on_per_instance_exception(self, deps, fake_convex):
        """An error in one instance must not abort processing of others."""
        fake_convex._instances = [
            # This will blow up because userId is missing
            {"desired": "running", "status": "stopped", "containerId": None},
            # This is a valid noop — should still be processed
            {
                "userId": "u4",
                "instanceId": "inst4",
                "desired": "stopped",
                "status": "stopped",
                "containerId": None,
                "heartbeatAt": None,
                "errorCount": 0,
            },
        ]
        # Should not raise
        actions = reconcile_once(deps)
        # At least the second instance was processed (resulted in noop = no action entry)
        # and the first produced an error entry
        error_actions = [a for a in actions if a.get("action") == "error"]
        assert len(error_actions) >= 1


# ---------------------------------------------------------------------------
# run() loop immortality test
# ---------------------------------------------------------------------------

class TestRunLoop:
    def test_run_loop_never_dies_on_reconcile_exception(self, test_cfg):
        """run() must swallow RuntimeError exceptions from reconcile_once and keep looping.

        After MAX_EXCEPTION_CALLS exceptions the patched function raises _StopLoop
        (a BaseException, not Exception) which escapes the except-Exception handler
        and terminates the loop for test purposes.
        """
        import unittest.mock as mock
        import controller as ctrl_module

        call_count = {"n": 0}
        stop_after = 3

        def exploding_reconcile(d):
            call_count["n"] += 1
            if call_count["n"] < stop_after:
                raise RuntimeError("simulated reconcile failure")
            raise _StopLoop()

        original_reconcile = ctrl_module.reconcile_once
        ctrl_module.reconcile_once = exploding_reconcile
        try:
            with mock.patch("time.sleep", return_value=None):
                with pytest.raises(_StopLoop):
                    ctrl_module.run(test_cfg)
        finally:
            ctrl_module.reconcile_once = original_reconcile

        # reconcile_once was called stop_after times
        assert call_count["n"] == stop_after

    def test_run_once_flag_exits_after_single_pass(self, test_cfg):
        """--once must run exactly one pass and return."""
        import unittest.mock as mock
        import controller as ctrl_module

        called = {"n": 0}

        def counting_reconcile(d):
            called["n"] += 1
            return []

        original = ctrl_module.reconcile_once
        ctrl_module.reconcile_once = counting_reconcile
        try:
            with mock.patch("time.sleep", return_value=None):
                ctrl_module.run(test_cfg, once=True)
        finally:
            ctrl_module.reconcile_once = original

        assert called["n"] == 1


class _StopLoop(BaseException):
    """Sentinel to break an otherwise-infinite loop in tests.

    Must be BaseException (not Exception) so it escapes the
    `except Exception` handler inside run() and propagates up.
    """
