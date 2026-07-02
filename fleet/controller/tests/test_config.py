"""Tests for config.py — env var parsing and validation."""
# ruff: noqa: PLR2004

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import (
    ControllerConfig,
    _bool_env,
    _float_env,
    _int_env,
    _optional,
    _require,
)

# ---------------------------------------------------------------------------
# _require
# ---------------------------------------------------------------------------


class TestRequire:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "hello")
        assert _require("TEST_VAR") == "hello"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "  value  ")
        assert _require("TEST_VAR") == "value"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(ValueError, match="MISSING_VAR"):
            _require("MISSING_VAR")

    def test_raises_when_empty(self, monkeypatch):
        monkeypatch.setenv("EMPTY_VAR", "")
        with pytest.raises(ValueError, match="EMPTY_VAR"):
            _require("EMPTY_VAR")

    def test_raises_when_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("WS_VAR", "   ")
        with pytest.raises(ValueError, match="WS_VAR"):
            _require("WS_VAR")


# ---------------------------------------------------------------------------
# _optional
# ---------------------------------------------------------------------------


class TestOptional:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("OPT_VAR", "present")
        assert _optional("OPT_VAR", "fallback") == "present"

    def test_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("OPT_VAR", raising=False)
        assert _optional("OPT_VAR", "fallback") == "fallback"

    def test_returns_default_when_empty(self, monkeypatch):
        monkeypatch.setenv("OPT_VAR", "")
        assert _optional("OPT_VAR", "fallback") == "fallback"

    def test_default_defaults_to_empty_string(self, monkeypatch):
        monkeypatch.delenv("OPT_VAR", raising=False)
        assert _optional("OPT_VAR") == ""


# ---------------------------------------------------------------------------
# _float_env
# ---------------------------------------------------------------------------


class TestFloatEnv:
    def test_parses_float(self, monkeypatch):
        monkeypatch.setenv("F_VAR", "3.14")
        assert _float_env("F_VAR", 1.0) == 3.14

    def test_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("F_VAR", raising=False)
        assert _float_env("F_VAR", 2.5) == 2.5

    def test_returns_default_when_empty(self, monkeypatch):
        monkeypatch.setenv("F_VAR", "")
        assert _float_env("F_VAR", 2.5) == 2.5

    def test_raises_on_invalid(self, monkeypatch):
        monkeypatch.setenv("F_VAR", "not_a_float")
        with pytest.raises(ValueError, match="must be a float"):
            _float_env("F_VAR", 1.0)

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("F_VAR", "  7.5  ")
        assert _float_env("F_VAR", 1.0) == 7.5


# ---------------------------------------------------------------------------
# _int_env
# ---------------------------------------------------------------------------


class TestIntEnv:
    def test_parses_int(self, monkeypatch):
        monkeypatch.setenv("I_VAR", "42")
        assert _int_env("I_VAR", 0) == 42

    def test_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("I_VAR", raising=False)
        assert _int_env("I_VAR", 99) == 99

    def test_returns_default_when_empty(self, monkeypatch):
        monkeypatch.setenv("I_VAR", "")
        assert _int_env("I_VAR", 99) == 99

    def test_raises_on_invalid(self, monkeypatch):
        monkeypatch.setenv("I_VAR", "3.14")
        with pytest.raises(ValueError, match="must be an int"):
            _int_env("I_VAR", 0)

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("I_VAR", "  10  ")
        assert _int_env("I_VAR", 0) == 10


# ---------------------------------------------------------------------------
# _bool_env
# ---------------------------------------------------------------------------


class TestBoolEnv:
    @pytest.mark.parametrize(
        "val", ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON"]
    )
    def test_truthy_values(self, monkeypatch, val):
        monkeypatch.setenv("B_VAR", val)
        assert _bool_env("B_VAR", False) is True

    @pytest.mark.parametrize("val", ["0", "false", "False", "no", "off", "anything"])
    def test_falsy_values(self, monkeypatch, val):
        monkeypatch.setenv("B_VAR", val)
        assert _bool_env("B_VAR", False) is False

    def test_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("B_VAR", raising=False)
        assert _bool_env("B_VAR", True) is True

    def test_returns_default_when_empty(self, monkeypatch):
        monkeypatch.setenv("B_VAR", "")
        assert _bool_env("B_VAR", True) is True


# ---------------------------------------------------------------------------
# ControllerConfig.from_env
# ---------------------------------------------------------------------------


class TestControllerConfigFromEnv:
    def _set_required_env(self, monkeypatch):
        monkeypatch.setenv("CONVEX_URL", "https://test.convex.cloud")
        monkeypatch.setenv("WORKER_SECRET", "test-secret")
        monkeypatch.setenv("IMAGE", "hermes:test")
        monkeypatch.setenv("HOSTS", "host-a,host-b")
        monkeypatch.setenv("GCP_PROJECT", "test-project")
        monkeypatch.setenv("GCS_BUCKET", "test-bucket")

    def test_parses_all_required_fields(self, monkeypatch):
        self._set_required_env(monkeypatch)
        cfg = ControllerConfig.from_env()
        assert cfg.convex_url == "https://test.convex.cloud"
        assert cfg.image == "hermes:test"
        assert cfg.hosts == ("host-a", "host-b")

    def test_hosts_are_parsed_as_tuple(self, monkeypatch):
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("HOSTS", "a, b, c")
        cfg = ControllerConfig.from_env()
        assert cfg.hosts == ("a", "b", "c")

    def test_raises_when_convex_url_missing(self, monkeypatch):
        monkeypatch.delenv("CONVEX_URL", raising=False)
        monkeypatch.setenv("WORKER_SECRET", "x")
        monkeypatch.setenv("IMAGE", "x")
        with pytest.raises(ValueError, match="CONVEX_URL"):
            ControllerConfig.from_env()

    def test_raises_when_worker_secret_missing(self, monkeypatch):
        monkeypatch.setenv("CONVEX_URL", "https://x")
        monkeypatch.delenv("WORKER_SECRET", raising=False)
        monkeypatch.setenv("IMAGE", "x")
        with pytest.raises(ValueError, match="WORKER_SECRET"):
            ControllerConfig.from_env()

    def test_raises_when_image_missing(self, monkeypatch):
        monkeypatch.setenv("CONVEX_URL", "https://x")
        monkeypatch.setenv("WORKER_SECRET", "x")
        monkeypatch.delenv("IMAGE", raising=False)
        with pytest.raises(ValueError, match="IMAGE"):
            ControllerConfig.from_env()

    def test_falls_back_to_localhost_when_hosts_empty(self, monkeypatch):
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("HOSTS", "")
        cfg = ControllerConfig.from_env()
        # _optional("HOSTS", "localhost") returns "localhost" for empty
        assert cfg.hosts == ("localhost",)

    def test_default_poll_interval(self, monkeypatch):
        self._set_required_env(monkeypatch)
        cfg = ControllerConfig.from_env()
        assert cfg.poll_interval_s == 3.0

    def test_custom_poll_interval(self, monkeypatch):
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("POLL_INTERVAL_S", "5.0")
        cfg = ControllerConfig.from_env()
        assert cfg.poll_interval_s == 5.0

    def test_default_stale_ttl(self, monkeypatch):
        self._set_required_env(monkeypatch)
        cfg = ControllerConfig.from_env()
        assert cfg.stale_ttl_s == 240.0

    def test_redacted_hides_worker_secret(self, monkeypatch):
        self._set_required_env(monkeypatch)
        cfg = ControllerConfig.from_env()
        r = cfg.redacted()
        assert r["worker_secret"] == "***"
        assert "test-secret" not in str(r)

    def test_runtime_backend_defaults_to_docker(self, monkeypatch):
        self._set_required_env(monkeypatch)
        cfg = ControllerConfig.from_env()
        assert cfg.runtime_backend == "docker"

    def test_runtime_backend_gce_vm_fields(self, monkeypatch):
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("RUNTIME_BACKEND", "gce_vm")
        monkeypatch.setenv("GCE_ZONE", "europe-west4-a")
        monkeypatch.setenv("GCE_MACHINE_TYPE", "e2-standard-4")
        monkeypatch.setenv("GCE_TAGS", "hermes-tenant,ru-browser")
        cfg = ControllerConfig.from_env()
        assert cfg.runtime_backend == "gce_vm"
        assert cfg.gce_zone == "europe-west4-a"
        assert cfg.gce_machine_type == "e2-standard-4"
        assert cfg.gce_tags == ("hermes-tenant", "ru-browser")

    def test_invalid_runtime_backend_raises(self, monkeypatch):
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("RUNTIME_BACKEND", "bad")
        with pytest.raises(ValueError, match="RUNTIME_BACKEND"):
            ControllerConfig.from_env()

    def test_single_host(self, monkeypatch):
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("HOSTS", "single-host")
        cfg = ControllerConfig.from_env()
        assert cfg.hosts == ("single-host",)

    def test_hosts_with_trailing_commas_and_spaces(self, monkeypatch):
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("HOSTS", " host-a , host-b , ")
        cfg = ControllerConfig.from_env()
        assert cfg.hosts == ("host-a", "host-b")
