"""Fleet controller configuration loaded from environment variables.

All secrets are referenced by name only — values never appear in logs.
Use `cfg.redacted()` for safe repr in log output.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _require(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise ValueError(f"Required env var {name!r} is not set")
    return v


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Env var {name!r} must be a float, got {raw!r}") from exc


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Env var {name!r} must be an int, got {raw!r}") from exc


@dataclass(frozen=True)
class ControllerConfig:
    """Immutable configuration for the fleet controller.

    Secret values (WORKER_SECRET, MINIMAX_API_KEY, etc.) are never stored
    on this object — the controller reads them directly from the environment
    at the point of use (docker run env injection) to keep them out of
    repr / logs.
    """

    # Convex
    convex_url: str
    # WORKER_SECRET value is intentionally NOT stored here; read from env at use-time.

    # GCP
    gcp_project: str
    gcp_region: str
    gcs_bucket: str

    # Fleet image
    image: str

    # Host VMs (comma-separated, parsed to a tuple)
    hosts: tuple[str, ...]

    # Timing
    poll_interval_s: float
    stale_ttl_s: float

    # Placement
    ram_headroom_pct: int

    # Failure thresholds
    max_launch_failures: int

    def redacted(self) -> dict:
        """Return a log-safe view of config — no secret values."""
        return {
            "convex_url": self.convex_url,
            "gcp_project": self.gcp_project,
            "gcp_region": self.gcp_region,
            "gcs_bucket": self.gcs_bucket,
            "image": self.image,
            "hosts": list(self.hosts),
            "poll_interval_s": self.poll_interval_s,
            "stale_ttl_s": self.stale_ttl_s,
            "ram_headroom_pct": self.ram_headroom_pct,
            "max_launch_failures": self.max_launch_failures,
            "worker_secret": "***",
        }

    @classmethod
    def from_env(cls) -> "ControllerConfig":
        """Construct config from environment variables.

        Raises ValueError for any missing required variable.
        """
        convex_url = _require("CONVEX_URL")
        # Validate WORKER_SECRET is present but do NOT store it on the config.
        _require("WORKER_SECRET")

        image = _require("IMAGE")

        raw_hosts = _optional("HOSTS", "localhost")
        hosts = tuple(h.strip() for h in raw_hosts.split(",") if h.strip())
        if not hosts:
            raise ValueError("HOSTS must contain at least one host")

        return cls(
            convex_url=convex_url,
            gcp_project=_optional("GCP_PROJECT", "hermes-saved-content-lab"),
            gcp_region=_optional("GCP_REGION", "us-central1"),
            gcs_bucket=_optional("GCS_BUCKET", "hermes-fleet-state"),
            image=image,
            hosts=hosts,
            poll_interval_s=_float_env("POLL_INTERVAL_S", 3.0),
            stale_ttl_s=_float_env("STALE_TTL_S", 90.0),
            ram_headroom_pct=_int_env("RAM_HEADROOM_PCT", 30),
            max_launch_failures=_int_env("MAX_LAUNCH_FAILURES", 3),
        )
