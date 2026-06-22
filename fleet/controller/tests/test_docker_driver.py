"""Tests for docker_driver.py — all subprocess calls mocked via injectable runner."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from docker_driver import DockerDriver


# ---------------------------------------------------------------------------
# DockerDriver.run
# ---------------------------------------------------------------------------

class TestDockerRun:
    def test_run_returns_container_id(self):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")

        driver = DockerDriver(run_cmd=fake_run)
        cid = driver.run("image:latest", "my-container", {"KEY": "val"})
        assert cid == "abc123"

    def test_run_constructs_correct_command(self):
        calls = []

        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="cid\n", stderr="")

        driver = DockerDriver(run_cmd=recording_run)
        driver.run("img:v1", "test-name", {"A": "1", "B": "2"})

        cmd = calls[0]
        assert cmd[0] == "docker"
        assert "run" in cmd
        assert "--detach" in cmd
        assert "--name" in cmd
        name_idx = cmd.index("--name")
        assert cmd[name_idx + 1] == "test-name"
        # Env vars
        assert "--env" in cmd
        assert "A=1" in cmd
        assert "B=2" in cmd
        # Image is last
        assert cmd[-1] == "img:v1"

    def test_run_with_mounts(self):
        calls = []

        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="cid\n", stderr="")

        driver = DockerDriver(run_cmd=recording_run)
        driver.run("img", "c1", {}, mounts=["/host:/container:rw"])

        cmd = calls[0]
        assert "--volume" in cmd
        vol_idx = cmd.index("--volume")
        assert cmd[vol_idx + 1] == "/host:/container:rw"

    def test_run_raises_on_failure(self):
        def fail_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error msg")

        driver = DockerDriver(run_cmd=fail_run)
        with pytest.raises(RuntimeError, match="docker run failed"):
            driver.run("img", "c1", {})

    def test_run_strips_container_id_whitespace(self):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="  id123  \n", stderr="")

        driver = DockerDriver(run_cmd=fake_run)
        assert driver.run("img", "c1", {}) == "id123"


# ---------------------------------------------------------------------------
# DockerDriver.stop
# ---------------------------------------------------------------------------

class TestDockerStop:
    def test_stop_calls_docker_stop(self):
        calls = []

        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        driver = DockerDriver(run_cmd=recording_run)
        driver.stop("my-container")

        assert calls[0] == ["docker", "stop", "my-container"]

    def test_stop_does_not_raise_on_failure(self):
        def fail_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not found")

        driver = DockerDriver(run_cmd=fail_run)
        # Should not raise — just logs a warning
        driver.stop("nonexistent")


# ---------------------------------------------------------------------------
# DockerDriver.inspect
# ---------------------------------------------------------------------------

class TestDockerInspect:
    def test_inspect_returns_first_record(self):
        record = {"State": {"Running": True}, "Id": "abc123"}

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps([record]), stderr="")

        driver = DockerDriver(run_cmd=fake_run)
        result = driver.inspect("my-container")
        assert result == record

    def test_inspect_returns_none_on_failure(self):
        def fail_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Error")

        driver = DockerDriver(run_cmd=fail_run)
        assert driver.inspect("missing") is None

    def test_inspect_returns_none_on_empty_list(self):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

        driver = DockerDriver(run_cmd=fake_run)
        assert driver.inspect("empty") is None

    def test_inspect_returns_none_on_bad_json(self):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")

        driver = DockerDriver(run_cmd=fake_run)
        assert driver.inspect("bad") is None


# ---------------------------------------------------------------------------
# DockerDriver.ps
# ---------------------------------------------------------------------------

class TestDockerPs:
    def test_ps_parses_json_lines(self):
        output = '{"ID":"id1","Names":"name1"}\n{"ID":"id2","Names":"name2"}\n'

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")

        driver = DockerDriver(run_cmd=fake_run)
        result = driver.ps()
        assert len(result) == 2
        assert result[0] == {"ID": "id1", "Names": "name1"}
        assert result[1] == {"ID": "id2", "Names": "name2"}

    def test_ps_returns_empty_on_failure(self):
        def fail_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error")

        driver = DockerDriver(run_cmd=fail_run)
        assert driver.ps() == []

    def test_ps_skips_empty_lines(self):
        output = '{"ID":"id1","Names":"name1"}\n\n\n'

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")

        driver = DockerDriver(run_cmd=fake_run)
        result = driver.ps()
        assert len(result) == 1
