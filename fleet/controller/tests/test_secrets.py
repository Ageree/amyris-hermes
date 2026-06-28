"""Tests for secrets.py — Secret Manager create-if-absent logic."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from secrets import SecretManager, _secret_name


# ---------------------------------------------------------------------------
# _secret_name (pure helper)
# ---------------------------------------------------------------------------

class TestSecretName:
    def test_alphanumeric_user_id(self):
        assert _secret_name("abc123") == "hermes-worker-abc123"

    def test_special_characters_replaced(self):
        # Convex IDs typically look like "j57abc..." but could have underscores
        assert _secret_name("user_id@test") == "hermes-worker-user-id-test"

    def test_empty_string(self):
        assert _secret_name("") == "hermes-worker-"

    def test_hyphens_preserved(self):
        # Hyphens are alphanumeric-safe for Secret Manager
        assert _secret_name("a-b-c") == "hermes-worker-a-b-c"


# ---------------------------------------------------------------------------
# SecretManager.__init__
# ---------------------------------------------------------------------------

class TestSecretManagerInit:
    def test_raises_on_empty_project(self):
        with pytest.raises(ValueError, match="gcp_project"):
            SecretManager("")

    def test_accepts_valid_project(self):
        sm = SecretManager("my-project", run_cmd=lambda *a, **kw: None)
        assert sm._project == "my-project"


# ---------------------------------------------------------------------------
# SecretManager.ensure_worker_secret
# ---------------------------------------------------------------------------

def _ok_run(*args, **kwargs):
    return subprocess.CompletedProcess(args[0], returncode=0, stdout="", stderr="")


def _fail_run(*args, **kwargs):
    return subprocess.CompletedProcess(args[0], returncode=1, stdout="", stderr="not found")


class TestEnsureWorkerSecret:
    def test_returns_name_when_secret_already_exists(self):
        sm = SecretManager("proj", run_cmd=_ok_run)
        name = sm.ensure_worker_secret("user1")
        assert name == "hermes-worker-user1"

    def test_creates_and_returns_name_when_not_exists(self):
        calls = []

        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            # First call is describe (returns NOT_FOUND), second is create
            if "describe" in cmd:
                return subprocess.CompletedProcess(cmd, 1, "", "NOT_FOUND")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        sm = SecretManager("proj", run_cmd=recording_run)
        name = sm.ensure_worker_secret("user1")
        assert name == "hermes-worker-user1"
        # Should have called describe then create
        assert len(calls) == 2
        assert "describe" in calls[0]
        assert "create" in calls[1]

    def test_does_not_create_when_exists(self):
        calls = []

        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        sm = SecretManager("proj", run_cmd=recording_run)
        sm.ensure_worker_secret("user1")
        # Only the describe call — no create
        assert len(calls) == 1
        assert "describe" in calls[0]

    def test_raises_on_create_failure(self):
        call_count = [0]

        def failing_create(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # describe → not found
                return subprocess.CompletedProcess(cmd, 1, "", "NOT_FOUND")
            # create → fails
            return subprocess.CompletedProcess(cmd, 1, "", "permission denied")

        sm = SecretManager("proj", run_cmd=failing_create)
        with pytest.raises(RuntimeError, match="failed"):
            sm.ensure_worker_secret("user1")


# ---------------------------------------------------------------------------
# SecretManager.secret_ref
# ---------------------------------------------------------------------------

class TestSecretRef:
    def test_returns_full_resource_name(self):
        sm = SecretManager("my-project", run_cmd=_ok_run)
        ref = sm.secret_ref("userABC")
        assert ref == "projects/my-project/secrets/hermes-worker-userABC"
