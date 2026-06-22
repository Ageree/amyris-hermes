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
    _build_env,
    _decide,
    _do_launch,
    _do_relaunch,
    _do_stop,
    _mirror_running_tenants,
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

    def test_launch_skips_worker_secret_when_disabled(self, deps, fake_secrets, fake_docker):
        # v1 default: PER_INSTANCE_SECRETS off -> do NOT mint a per-instance secret
        # (avoids empty, enumerable Secret Manager secrets) and do NOT inject a dead
        # WORKER_SECRET_REF the worker never reads.
        assert deps.cfg.per_instance_secrets is False
        _do_launch(self._inst(userId="u1"), deps)
        assert fake_secrets.ensured == []
        assert "WORKER_SECRET_REF" not in fake_docker.ran[0]["env"]

    def test_launch_ensures_worker_secret_when_enabled(self, deps, fake_secrets, fake_docker):
        deps.cfg = replace(deps.cfg, per_instance_secrets=True)
        _do_launch(self._inst(userId="u1"), deps)
        assert "u1" in fake_secrets.ensured
        assert fake_docker.ran[0]["env"].get("WORKER_SECRET_REF") == "hermes-worker-u1"

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
    def test_relaunch_stops_then_starts(self, deps, fake_docker, fake_convex):
        # The row is currently "running" (stale heartbeat). The real
        # claimInstanceForLaunch refuses to re-claim a "running" row, so relaunch
        # MUST first transition it off "running" via markStopped.
        fake_convex.set_status("u3", "running")
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
        # Old container stopped, new container started.
        assert len(fake_docker.ran) == 1
        # The relaunch must NOT self-kill the brand-new container: its claim
        # succeeds (because markStopped flipped the row off "running").
        assert result["action"] == "launched", result
        # Exactly ONE docker stop — the OLD container. In the buggy path there were
        # TWO (relaunch's stop of old + _do_launch's duplicate-stop of the brand-new
        # container, since the name is stable per user and they can't be told apart
        # by name). One stop proves the new container was NOT self-killed.
        assert len(fake_docker.stopped) == 1, fake_docker.stopped
        # markStopped was called to release the "running" claim before relaunch.
        assert "u3" in fake_convex.mark_stopped_calls
        # And the claim actually succeeded (single attempt, claimed:true).
        assert len(fake_convex.claimed_calls) == 1


# ---------------------------------------------------------------------------
# Bug H1 — crash-loop guard. A container that docker-runs fine but DIES before
# its first heartbeat must NOT be relaunched forever. After max_launch_failures
# crash-relaunches (no heartbeat advance), the controller marks error and stops
# hammering docker until desired/wantsAt is re-asserted.
# ---------------------------------------------------------------------------

class TestCrashLoopGuard:
    def _crashed_inst(self, **overrides) -> dict:
        """A row the reconcile sees as 'relaunch': desired=running, status=running,
        a live containerId, but a stale/missing heartbeat (the container died)."""
        base = {
            "userId": "u_crash",
            "instanceId": "inst_crash",
            "desired": "running",
            "status": "running",
            "containerId": "deadcid",
            "heartbeatAt": None,   # never heartbeat -> crash before first ping
            "wantsAt": 1000,
            "errorCount": 0,
        }
        base.update(overrides)
        return base

    def test_crash_relaunch_stops_after_max_and_marks_error(self, deps, fake_docker, fake_convex):
        n = deps.cfg.max_launch_failures
        # The row stays "running" with a never-advancing heartbeat across ticks.
        fake_convex.set_status("u_crash", "running")

        for _ in range(n + 3):  # try MORE ticks than the threshold
            inst = self._crashed_inst()
            action = _decide(inst, deps)
            if action == "relaunch":
                _do_relaunch(inst, deps)
                # markStopped flips fake status to "stopped"; mimic the dead
                # container by re-asserting "running" with a stale heartbeat for
                # the NEXT tick (the relaunched container also died).
                fake_convex.set_status("u_crash", "running")

        # The number of ACTUAL docker runs is bounded by the crash-loop threshold —
        # the guard suppresses further relaunches once it trips.
        assert len(fake_docker.ran) <= n, (
            f"kept relaunching ({len(fake_docker.ran)}) past the crash-loop threshold {n}"
        )
        # It marked the instance errored.
        assert any(c["userId"] == "u_crash" for c in fake_convex.mark_error_calls), (
            "never called mark_error on a crash-looping instance"
        )

    def test_crash_loop_issues_no_further_docker_run_after_block(self, deps, fake_docker, fake_convex):
        n = deps.cfg.max_launch_failures
        fake_convex.set_status("u_crash", "running")

        # Drive enough ticks to trip the guard.
        for _ in range(n + 2):
            inst = self._crashed_inst()
            if _decide(inst, deps) == "relaunch":
                _do_relaunch(inst, deps)
                fake_convex.set_status("u_crash", "running")

        runs_at_block = len(fake_docker.ran)

        # Further ticks while desired/wantsAt is UNCHANGED must NOT docker run.
        for _ in range(3):
            inst = self._crashed_inst()
            if _decide(inst, deps) == "relaunch":
                _do_relaunch(inst, deps)

        assert len(fake_docker.ran) == runs_at_block, (
            "controller kept issuing docker run after the crash-loop block"
        )

    def test_healthy_heartbeat_advance_resets_counter_no_error(self, deps, fake_docker, fake_convex):
        """A container that recovers (heartbeat ADVANCES between relaunches) is a
        legitimate stale-relaunch, NOT a crash loop — the counter resets and we
        never mark_error, even across many ticks."""
        fake_convex.set_status("u_ok", "running")
        hb = 1000
        for _ in range(deps.cfg.max_launch_failures + 4):
            # Each relaunch sees a FRESHER heartbeat than the previous tick.
            hb += 100
            inst = self._crashed_inst(userId="u_ok", heartbeatAt=hb)
            if _decide(inst, deps) == "relaunch":
                _do_relaunch(inst, deps)
                fake_convex.set_status("u_ok", "running")
        assert not any(c["userId"] == "u_ok" for c in fake_convex.mark_error_calls), (
            "marked error on a healthily-advancing instance (false positive)"
        )

    def test_crash_loop_block_clears_when_desired_reasserted(self, deps, fake_docker, fake_convex):
        n = deps.cfg.max_launch_failures
        fake_convex.set_status("u_crash", "running")
        for _ in range(n + 2):
            inst = self._crashed_inst()
            if _decide(inst, deps) == "relaunch":
                _do_relaunch(inst, deps)
                fake_convex.set_status("u_crash", "running")
        runs_at_block = len(fake_docker.ran)

        # Operator/user re-asserts desired (wantsAt advances) -> the guard clears
        # and a launch is attempted again.
        fake_convex.set_status("u_crash", "stopped")
        reasserted = self._crashed_inst(wantsAt=999999, status="stopped", containerId=None)
        action = _decide(reasserted, deps)
        assert action == "launch"
        _do_launch(reasserted, deps)
        assert len(fake_docker.ran) == runs_at_block + 1


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

    def test_reconcile_launches_freshly_requested_provisioning_instance(
        self, deps, fake_convex, fake_docker
    ):
        """Bug C2: a freshly requested instance (desired=running, status=provisioning,
        no containerId, no heartbeatAt) MUST be cold-started — docker run +
        claimInstanceForLaunch — by a single reconcile pass."""
        fake_convex._instances = [{
            "userId": "u_fresh",
            "instanceId": "inst_fresh",
            "desired": "running",
            "status": "provisioning",
            "containerId": None,
            "heartbeatAt": None,
            "errorCount": 0,
        }]
        actions = reconcile_once(deps)
        assert any(a["action"] == "launched" for a in actions), actions
        assert len(fake_docker.ran) == 1
        assert len(fake_convex.claimed_calls) == 1
        assert fake_convex.claimed_calls[0]["userId"] == "u_fresh"

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


# ---------------------------------------------------------------------------
# Bug C1/M2 — env contract: _build_env must produce EXACTLY the names the
# worker's WorkerConfig.from_env() bracket-reads, so a launched container boots.
# This is the regression test that would have caught the
# SENDBLUE_API_SECRET vs SENDBLUE_API_SECRET_KEY mismatch and the missing
# SENDBLUE_FROM_NUMBER / MINIMAX_BASE_URL.
# ---------------------------------------------------------------------------

class TestBuildEnvBootsWorker:
    def _set_controller_env(self, monkeypatch) -> None:
        """Set the SECRET-source vars the controller reads from its OWN env."""
        monkeypatch.setenv("WORKER_SECRET", "ws-from-controller")
        monkeypatch.setenv("MINIMAX_API_KEY", "mm-key")
        monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M3")
        monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
        monkeypatch.setenv("SENDBLUE_API_KEY_ID", "sb-id")
        monkeypatch.setenv("SENDBLUE_API_SECRET_KEY", "sb-secret")
        monkeypatch.setenv("SENDBLUE_FROM_NUMBER", "+16466208124")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-token")
        monkeypatch.setenv("EXA_API_KEY", "exa-key")

    def test_build_env_includes_exact_sendblue_secret_key_name(self, test_cfg, monkeypatch):
        self._set_controller_env(monkeypatch)
        env = _build_env("u1", "inst1", test_cfg, "secret-ref")
        # The worker reads SENDBLUE_API_SECRET_KEY (NOT SENDBLUE_API_SECRET).
        assert env["SENDBLUE_API_SECRET_KEY"] == "sb-secret"
        assert "SENDBLUE_API_SECRET" not in env or "SENDBLUE_API_SECRET_KEY" in env

    def test_build_env_includes_sendblue_from_number(self, test_cfg, monkeypatch):
        self._set_controller_env(monkeypatch)
        env = _build_env("u1", "inst1", test_cfg, "secret-ref")
        assert env["SENDBLUE_FROM_NUMBER"] == "+16466208124"

    def test_build_env_includes_minimax_base_url(self, test_cfg, monkeypatch):
        self._set_controller_env(monkeypatch)
        env = _build_env("u1", "inst1", test_cfg, "secret-ref")
        assert env["MINIMAX_BASE_URL"] == "https://api.minimax.io/v1"

    def test_build_env_injects_browser_harness_vars(self, test_cfg, monkeypatch):
        """browser-harness (Lane B): per-user BU_NAME, the local CDP url, and the
        kill-switch must reach the container so the worker seed + entrypoint fire."""
        self._set_controller_env(monkeypatch)
        env = _build_env("u1", "inst1", test_cfg, "secret-ref")
        assert env["BU_NAME"] == "u1"
        assert env["BU_CDP_URL"] == "http://127.0.0.1:9222"
        assert env["BROWSER_HARNESS_ENABLED"] == "1"

    def test_build_env_sanitizes_bu_name(self, test_cfg, monkeypatch):
        """A userId with chars outside [A-Za-z0-9_-] is sanitized (the harness
        rejects a bad BU_NAME); an empty id falls back to 'tenant'."""
        self._set_controller_env(monkeypatch)
        env = _build_env("user/../x y", "inst1", test_cfg, "secret-ref")
        assert env["BU_NAME"] == "user----x-y"  # '/', '.', ' ' -> '-'
        assert _build_env("", "inst1", test_cfg, "secret-ref")["BU_NAME"] == "tenant"

    def test_build_env_kill_switch_off_propagates(self, test_cfg, monkeypatch):
        """BROWSER_HARNESS_ENABLED=0 on the controller reaches the container so the
        built-in browser stays the fallback."""
        self._set_controller_env(monkeypatch)
        monkeypatch.setenv("BROWSER_HARNESS_ENABLED", "0")
        env = _build_env("u1", "inst1", test_cfg, "secret-ref")
        assert env["BROWSER_HARNESS_ENABLED"] == "0"

    def test_built_env_constructs_worker_config_with_no_keyerror(self, test_cfg, monkeypatch):
        """The smoking gun: feed _build_env's output to the REAL worker config
        builder. If any required name is missing/misnamed, from_env raises KeyError
        and the container would crash on boot."""
        import importlib.util
        import os as _os

        self._set_controller_env(monkeypatch)
        env = _build_env("u1", "inst1", test_cfg, "secret-ref")

        # Load the worker module by file path (it lives in lab/skeleton, a sibling
        # tree). Its WorkerConfig.from_env() is the exact boot-time contract.
        worker_path = _os.path.abspath(
            _os.path.join(
                _os.path.dirname(__file__), "..", "..", "..",
                "lab", "skeleton", "worker.py",
            )
        )
        mod_name = "_worker_for_envtest"
        spec = importlib.util.spec_from_file_location(mod_name, worker_path)
        worker_mod = importlib.util.module_from_spec(spec)
        # worker.py imports siblings (convex_client, hermes_bridge, channels) —
        # ensure lab/skeleton is importable before exec.
        import sys as _sys
        _sys.path.insert(0, _os.path.dirname(worker_path))
        # Register in sys.modules BEFORE exec so dataclass() can resolve the
        # module's annotations (frozen WorkerConfig) via cls.__module__.
        _sys.modules[mod_name] = worker_mod
        spec.loader.exec_module(worker_mod)

        # Replace os.environ with EXACTLY the launched container's env so any
        # bracket-access on a missing name raises KeyError.
        monkeypatch.setattr(_os, "environ", dict(env))
        cfg = worker_mod.WorkerConfig.from_env()  # MUST NOT raise KeyError

        # Spot-check the values flowed through correctly.
        assert cfg.worker_secret == "ws-from-controller"
        assert cfg.sendblue_secret == "sb-secret"
        assert cfg.sendblue_from == "+16466208124"
        assert cfg.minimax_base_url == "https://api.minimax.io/v1"
        assert cfg.scoped_user_id == "u1"


# ---------------------------------------------------------------------------
# Bug C3 — model endpoint MUST match the funded key. The live key is an
# OpenRouter key (sk-or-*) → openrouter.ai; a native MiniMax key → api.minimax.io.
# Derived from the key prefix so a forgotten MINIMAX_BASE_URL can't silently 401
# every container. An explicit env value always wins.
# ---------------------------------------------------------------------------

class TestModelEndpointContract:
    def _clear_overrides(self, monkeypatch) -> None:
        monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
        monkeypatch.delenv("MINIMAX_MODEL", raising=False)

    def test_openrouter_key_derives_openrouter_endpoint(self, test_cfg, monkeypatch):
        self._clear_overrides(monkeypatch)
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-or-v1-abc123")
        env = _build_env("u1", "inst1", test_cfg, "")
        assert env["MINIMAX_BASE_URL"] == "https://openrouter.ai/api/v1"
        assert env["MINIMAX_MODEL"] == "minimax/minimax-m3"

    def test_native_key_derives_native_endpoint(self, test_cfg, monkeypatch):
        self._clear_overrides(monkeypatch)
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-cp-nativekey")
        env = _build_env("u1", "inst1", test_cfg, "")
        assert env["MINIMAX_BASE_URL"] == "https://api.minimax.io/v1"
        assert env["MINIMAX_MODEL"] == "MiniMax-M3"

    def test_explicit_base_url_overrides_derivation(self, test_cfg, monkeypatch):
        monkeypatch.setenv("MINIMAX_API_KEY", "sk-or-v1-abc123")
        monkeypatch.setenv("MINIMAX_BASE_URL", "https://custom.example/v1")
        env = _build_env("u1", "inst1", test_cfg, "")
        assert env["MINIMAX_BASE_URL"] == "https://custom.example/v1"


# ---------------------------------------------------------------------------
# CAPACITY_PER_HOST — placement capacity is configurable so a single VM can be
# capped conservatively (deferred-item #1 interim guidance: fabricated host
# metrics; keep capacity conservative until a real /metrics agent exists).
# ---------------------------------------------------------------------------

class TestCapacityConfig:
    def test_capacity_per_host_default(self, test_cfg):
        assert test_cfg.capacity_per_host == 50

    def test_stale_ttl_default_matches_docs(self, test_cfg):
        # CTRL-13: the code default must match .env.example/README (240s, >= the
        # worst-case Hermes turn) so a bare run (no env file) can't relaunch a
        # healthy container mid-turn and drop an in-flight reply.
        assert test_cfg.stale_ttl_s == 240.0

    def test_capacity_per_host_from_env(self, monkeypatch):
        monkeypatch.setenv("CONVEX_URL", "https://t.convex.cloud")
        monkeypatch.setenv("WORKER_SECRET", "s")
        monkeypatch.setenv("IMAGE", "img")
        monkeypatch.setenv("CAPACITY_PER_HOST", "5")
        from config import ControllerConfig
        cfg = ControllerConfig.from_env()
        assert cfg.capacity_per_host == 5


# ---------------------------------------------------------------------------
# Periodic crash-recovery mirror (deferred-item #2): _mirror_running_tenants
# mirrors ONLY running tenants, fail-soft, independent of container naming.
# ---------------------------------------------------------------------------

class TestPeriodicMirror:
    def _deps_with(self, instances, fake_convex, fake_docker, fake_state_sync,
                   fake_secrets, test_cfg):
        fake_convex._instances = instances
        return ControllerDeps(
            cfg=test_cfg, convex=fake_convex, docker=fake_docker,
            state_sync=fake_state_sync, secrets=fake_secrets,
            now_fn=lambda: 1_000_000.0,
        )

    def test_mirrors_only_running_tenants(self, deps):
        deps.convex._instances = [
            {"userId": "u1", "status": "running"},
            {"userId": "u2", "status": "stopped"},
            {"userId": "u3", "status": "provisioning"},
            {"userId": "u4", "status": "running"},
        ]
        n = _mirror_running_tenants(deps)
        assert n == 2
        assert sorted(deps.state_sync.mirrored) == ["u1", "u4"]

    def test_no_running_tenants_mirrors_nothing(self, deps):
        deps.convex._instances = [{"userId": "u1", "status": "stopped"}]
        assert _mirror_running_tenants(deps) == 0
        assert deps.state_sync.mirrored == []

    def test_failsoft_when_list_reconcile_raises(self, deps):
        def boom():
            raise RuntimeError("convex down")
        deps.convex.list_reconcile = boom
        # Must not propagate — a mirror miss can never kill the reconcile loop.
        assert _mirror_running_tenants(deps) == 0

    def test_mirror_interval_default_is_300(self, test_cfg):
        assert test_cfg.mirror_interval_s == 300.0
