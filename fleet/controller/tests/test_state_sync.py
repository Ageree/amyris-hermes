"""Tests for state_sync.py — all gcloud calls mocked via injectable runner."""
from __future__ import annotations

import subprocess
from typing import Callable
from unittest.mock import MagicMock

import pytest

import re

from state_sync import StateSync, _EXCLUDE_REGEX


def _exclude_value(cmd):
    """Pull the regex passed to --exclude out of an rsync argv."""
    i = cmd.index("--exclude")
    return cmd[i + 1]


def _ok_run(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")


def _fail_run(*args, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="fake error")


class TestRehydrate:
    def test_rehydrate_returns_true_on_success(self, tmp_path):
        ss = StateSync("my-bucket", local_root=str(tmp_path), run_cmd=_ok_run)
        assert ss.rehydrate("user1") is True

    def test_rehydrate_returns_false_on_failure(self, tmp_path):
        ss = StateSync("my-bucket", local_root=str(tmp_path), run_cmd=_fail_run)
        assert ss.rehydrate("user1") is False

    def test_rehydrate_creates_local_bind_mount_dir(self, tmp_path):
        # Bug C5: the bind-mount SOURCE must exist (owned by the controller uid,
        # which equals the container's non-root uid 10001) BEFORE docker run, or the
        # container gets EACCES on HERMES_HOME. rehydrate creates it as itself.
        ss = StateSync("my-bucket", local_root=str(tmp_path), run_cmd=_ok_run)
        ss.rehydrate("user1")
        assert (tmp_path / "user1").is_dir()

    def test_rehydrate_calls_gcloud_storage_rsync(self, tmp_path):
        calls = []
        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        ss = StateSync("my-bucket", local_root=str(tmp_path), run_cmd=recording_run)
        ss.rehydrate("user1")

        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[0] == "gcloud"
        assert "rsync" in cmd
        assert "gs://my-bucket/tenants/user1/" in cmd
        assert f"{tmp_path}/user1/" in cmd

    def test_rehydrate_excludes_lockfiles(self, tmp_path):
        calls = []
        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        ss = StateSync("my-bucket", local_root=str(tmp_path), run_cmd=recording_run)
        ss.rehydrate("user1")

        # The exclude must be a VALID Python regex (a glob like "*.lock" crashes
        # gcloud with "nothing to repeat") that matches the lock/WAL/journal/
        # singleton files but spares real state files.
        rx = re.compile(_exclude_value(calls[0]))  # raises if not a valid regex
        for f in ("foo.lock", "default/SingletonLock", "hermes.db-journal", "hermes.db-wal"):
            assert rx.match(f), f"exclude regex should drop {f!r}"
        for keep in ("hermes.db", "config.json", "logins.json"):
            assert not rx.match(keep), f"exclude regex must NOT drop {keep!r}"

    def test_rehydrate_failsoft_on_subprocess_exception(self, tmp_path):
        def raising_run(*a, **kw):
            raise OSError("gcloud not found")

        ss = StateSync("my-bucket", local_root=str(tmp_path), run_cmd=raising_run)
        result = ss.rehydrate("user1")
        assert result is False


class TestMirror:
    def test_mirror_returns_true_on_success(self):
        ss = StateSync("my-bucket", run_cmd=_ok_run)
        assert ss.mirror("user1") is True

    def test_mirror_returns_false_on_failure(self):
        ss = StateSync("my-bucket", run_cmd=_fail_run)
        assert ss.mirror("user1") is False

    def test_mirror_src_is_local_dst_is_gcs(self):
        calls = []
        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        ss = StateSync("my-bucket", local_root="/mydata", run_cmd=recording_run)
        ss.mirror("userX")

        cmd = calls[0]
        # src = local, dst = gcs
        assert "/mydata/userX/" in cmd
        assert "gs://my-bucket/tenants/userX/" in cmd
        # src comes BEFORE dst
        local_idx = next(i for i, c in enumerate(cmd) if "/mydata/userX/" in c)
        gcs_idx = next(i for i, c in enumerate(cmd) if "gs://" in c)
        assert local_idx < gcs_idx

    def test_mirror_excludes_singleton_lock(self):
        calls = []
        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        ss = StateSync("my-bucket", run_cmd=recording_run)
        ss.mirror("userY")
        rx = re.compile(_exclude_value(calls[0]))
        assert rx.match("default/SingletonLock")

    def test_mirror_excludes_wal_files(self):
        calls = []
        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        ss = StateSync("my-bucket", run_cmd=recording_run)
        ss.mirror("userZ")
        rx = re.compile(_exclude_value(calls[0]))
        assert rx.match("hermes.db-wal")
        assert rx.match("hermes.db-journal")

    def test_quiesce_before_mirror_ordering(self):
        """Verify the mirror() call itself doesn't stop anything —
        that's the caller's responsibility.  Mirror is a pure push."""
        operations = []
        def recording_run(cmd, **kwargs):
            operations.append(("rsync", cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        ss = StateSync("my-bucket", run_cmd=recording_run)
        # Simulate: caller stops container THEN calls mirror
        operations.append(("stop", None))  # pre-recorded by caller
        ss.mirror("u1")

        assert operations[0][0] == "stop"
        assert operations[1][0] == "rsync"


class TestStateSyncInit:
    def test_empty_bucket_raises(self):
        with pytest.raises(ValueError):
            StateSync("")

    def test_bucket_name_stripped(self):
        ss = StateSync("  my-bucket  ")
        assert ss._bucket == "my-bucket"
