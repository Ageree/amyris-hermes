"""Shared pytest fixtures for fleet controller tests.

ALL tests are network-free.  Docker, gcloud, and Convex are mocked via
injectable fakes or monkeypatching.
"""
from __future__ import annotations

import subprocess
import sys
import os
from dataclasses import dataclass, field
from typing import Callable
from unittest.mock import MagicMock

import pytest

# Make the controller package importable from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import ControllerConfig
from controller import ControllerDeps
from convex_admin import ConvexAdminClient
from docker_driver import DockerDriver
from placement import choose_host, host_has_room
from secrets import SecretManager
from state_sync import StateSync


# ---------------------------------------------------------------------------
# Minimal ControllerConfig for tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def test_cfg(monkeypatch) -> ControllerConfig:
    monkeypatch.setenv("CONVEX_URL", "https://test.convex.cloud")
    monkeypatch.setenv("WORKER_SECRET", "test-secret")
    monkeypatch.setenv("IMAGE", "hermes:test")
    monkeypatch.setenv("HOSTS", "host-a,host-b")
    monkeypatch.setenv("GCP_PROJECT", "test-project")
    monkeypatch.setenv("GCS_BUCKET", "test-bucket")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-mm-key")
    monkeypatch.setenv("SENDBLUE_API_KEY_ID", "test-sb-id")
    monkeypatch.setenv("SENDBLUE_API_SECRET", "test-sb-secret")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-tg-token")
    monkeypatch.setenv("EXA_API_KEY", "test-exa-key")
    return ControllerConfig.from_env()


# ---------------------------------------------------------------------------
# Fake Docker driver
# ---------------------------------------------------------------------------

class FakeDockerDriver:
    """Simulates docker CLI without any real subprocess calls."""

    def __init__(self) -> None:
        self.ran: list[dict] = []
        self.stopped: list[str] = []
        self._running: dict[str, bool] = {}   # name -> running
        self._next_id = 0
        # Override to inject failures
        self.run_should_fail: bool = False
        self.run_fail_message: str = "fake docker error"

    def run(self, image: str, name: str, env: dict, mounts=None) -> str:
        if self.run_should_fail:
            raise RuntimeError(self.run_fail_message)
        self._next_id += 1
        cid = f"fakecid{self._next_id:04d}"
        self.ran.append({"image": image, "name": name, "env": env, "mounts": mounts, "id": cid})
        self._running[name] = True
        return cid

    def stop(self, name_or_id: str) -> None:
        self.stopped.append(name_or_id)
        self._running[name_or_id] = False

    def inspect(self, name_or_id: str):
        running = self._running.get(name_or_id, False)
        if not running:
            return None
        return {"State": {"Running": True}}

    def is_running(self, name_or_id: str) -> bool:
        return self._running.get(name_or_id, False)

    def ps(self) -> list[dict]:
        return [
            {"ID": f"id-{name}", "Names": name}
            for name, running in self._running.items()
            if running
        ]


@pytest.fixture()
def fake_docker() -> FakeDockerDriver:
    return FakeDockerDriver()


# ---------------------------------------------------------------------------
# Fake ConvexAdminClient
# ---------------------------------------------------------------------------

class FakeConvexAdmin:
    def __init__(self, instances: list[dict] | None = None) -> None:
        self._instances = instances or []
        self.claimed_calls: list[dict] = []
        self.mark_stopped_calls: list[str] = []
        self.mark_error_calls: list[dict] = []
        self.set_desired_calls: list[dict] = []
        # Override to simulate claim race loss
        self.claim_returns: bool = True
        # Override to simulate errors
        self.claim_should_raise: bool = False

    def list_reconcile(self) -> list[dict]:
        return list(self._instances)

    def claim_for_launch(self, user_id, host_vm, container_id, worker_secret_ref=None):
        self.claimed_calls.append({
            "userId": user_id, "hostVm": host_vm,
            "containerId": container_id, "workerSecretRef": worker_secret_ref,
        })
        if self.claim_should_raise:
            raise RuntimeError("fake claim error")
        return {"claimed": self.claim_returns}

    def mark_stopped(self, user_id: str):
        self.mark_stopped_calls.append(user_id)

    def mark_error(self, user_id: str, error: str):
        self.mark_error_calls.append({"userId": user_id, "error": error})
        return {"errorCount": len(self.mark_error_calls)}

    def set_desired(self, user_id: str, desired: str):
        self.set_desired_calls.append({"userId": user_id, "desired": desired})


@pytest.fixture()
def fake_convex() -> FakeConvexAdmin:
    return FakeConvexAdmin()


# ---------------------------------------------------------------------------
# Fake StateSync
# ---------------------------------------------------------------------------

class FakeStateSync:
    def __init__(self) -> None:
        self.rehydrated: list[str] = []
        self.mirrored: list[str] = []
        self.mirror_should_fail: bool = False

    def rehydrate(self, user_id: str) -> bool:
        self.rehydrated.append(user_id)
        return True

    def mirror(self, user_id: str) -> bool:
        self.mirrored.append(user_id)
        return not self.mirror_should_fail


@pytest.fixture()
def fake_state_sync() -> FakeStateSync:
    return FakeStateSync()


# ---------------------------------------------------------------------------
# Fake SecretManager
# ---------------------------------------------------------------------------

class FakeSecretManager:
    def __init__(self) -> None:
        self.ensured: list[str] = []

    def ensure_worker_secret(self, user_id: str) -> str:
        self.ensured.append(user_id)
        return f"hermes-worker-{user_id}"

    def secret_ref(self, user_id: str) -> str:
        return f"projects/test/secrets/hermes-worker-{user_id}"


@pytest.fixture()
def fake_secrets() -> FakeSecretManager:
    return FakeSecretManager()


# ---------------------------------------------------------------------------
# Composite deps fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def deps(test_cfg, fake_docker, fake_convex, fake_state_sync, fake_secrets):
    return ControllerDeps(
        cfg=test_cfg,
        convex=fake_convex,
        docker=fake_docker,
        state_sync=fake_state_sync,
        secrets=fake_secrets,
        now_fn=lambda: 1_000_000.0,   # fixed epoch for determinism
    )
