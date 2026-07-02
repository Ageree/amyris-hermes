"""Fleet controller configuration loaded from environment variables.

All secrets are referenced by name only — values never appear in logs.
Use `cfg.redacted()` for safe repr in log output.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


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


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _csv_env(name: str, default: str = "") -> tuple[str, ...]:
    raw = _optional(name, default)
    return tuple(v.strip() for v in raw.split(",") if v.strip())


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

    # Runtime backend. docker = historical per-user containers on a controller VM;
    # gce_vm = one Compute Engine VM per user running the same container image.
    runtime_backend: str

    # Eve in-container server port. The entrypoint binds the Eve Nitro server
    # here (127.0.0.1); the controller derives EVE_URL=http://127.0.0.1:<eve_port>
    # for the in-container scoped poller. EVE_INGRESS_SECRET is a secret and is
    # read from env at use-time (never stored on this object).
    eve_port: int

    # Host VMs (comma-separated, parsed to a tuple)
    hosts: tuple[str, ...]

    # Timing
    poll_interval_s: float
    stale_ttl_s: float
    # Periodic crash-recovery GCS mirror (deferred item #2). State is otherwise
    # mirrored only on a clean docker stop, so a crash loses everything written
    # since the last stop. 0 disables the timer.
    mirror_interval_s: float

    # Placement
    ram_headroom_pct: int
    # Per-host container cap. The real fix for placement is a /metrics host agent
    # (deferred); until then this lets the operator keep capacity CONSERVATIVE on a
    # single VM (the deferral's interim guidance), e.g. CAPACITY_PER_HOST=5.
    capacity_per_host: int

    # Failure thresholds
    max_launch_failures: int

    # Per-instance Secret Manager secrets. OFF for v1: the worker reads the shared
    # WORKER_SECRET, and claimNextForUser's server-side userId-scope IS the
    # isolation boundary. The per-instance machinery (secrets.py + WORKER_SECRET_REF)
    # is NOT wired (worker.py never reads the ref), so creating per-instance secrets
    # would only mint empty, enumerable secrets. Flip ON only after wiring the read.
    per_instance_secrets: bool

    # GCE one-VM-per-user backend.
    gce_zone: str
    gce_machine_type: str
    gce_boot_disk_size: str
    gce_service_account: str
    gce_network: str
    gce_subnetwork: str
    gce_scopes: str
    gce_tags: tuple[str, ...]
    gce_labels: tuple[str, ...]

    def redacted(self) -> dict:
        """Return a log-safe view of config — no secret values."""
        return {
            "convex_url": self.convex_url,
            "gcp_project": self.gcp_project,
            "gcp_region": self.gcp_region,
            "gcs_bucket": self.gcs_bucket,
            "image": self.image,
            "runtime_backend": self.runtime_backend,
            "eve_port": self.eve_port,
            "hosts": list(self.hosts),
            "poll_interval_s": self.poll_interval_s,
            "stale_ttl_s": self.stale_ttl_s,
            "mirror_interval_s": self.mirror_interval_s,
            "ram_headroom_pct": self.ram_headroom_pct,
            "capacity_per_host": self.capacity_per_host,
            "max_launch_failures": self.max_launch_failures,
            "per_instance_secrets": self.per_instance_secrets,
            "gce_zone": self.gce_zone,
            "gce_machine_type": self.gce_machine_type,
            "gce_boot_disk_size": self.gce_boot_disk_size,
            "gce_service_account": self.gce_service_account,
            "gce_network": self.gce_network,
            "gce_subnetwork": self.gce_subnetwork,
            "gce_scopes": self.gce_scopes,
            "gce_tags": list(self.gce_tags),
            "gce_labels": list(self.gce_labels),
            "worker_secret": "***",
        }

    @classmethod
    def from_env(cls) -> ControllerConfig:
        """Construct config from environment variables.

        Raises ValueError for any missing required variable.
        """
        convex_url = _require("CONVEX_URL")
        # Validate WORKER_SECRET is present but do NOT store it on the config.
        _require("WORKER_SECRET")

        image = _require("IMAGE")
        runtime_backend = _optional("RUNTIME_BACKEND", "docker")
        if runtime_backend not in ("docker", "gce_vm"):
            raise ValueError("RUNTIME_BACKEND must be 'docker' or 'gce_vm'")

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
            runtime_backend=runtime_backend,
            eve_port=_int_env("EVE_PORT", 4123),
            hosts=hosts,
            poll_interval_s=_float_env("POLL_INTERVAL_S", 3.0),
            stale_ttl_s=_float_env("STALE_TTL_S", 240.0),
            mirror_interval_s=_float_env("MIRROR_INTERVAL_S", 300.0),
            ram_headroom_pct=_int_env("RAM_HEADROOM_PCT", 30),
            capacity_per_host=_int_env("CAPACITY_PER_HOST", 50),
            max_launch_failures=_int_env("MAX_LAUNCH_FAILURES", 3),
            per_instance_secrets=_bool_env("PER_INSTANCE_SECRETS", False),
            gce_zone=_optional("GCE_ZONE", _optional("GCP_ZONE", "us-central1-a")),
            gce_machine_type=_optional("GCE_MACHINE_TYPE", "e2-standard-2"),
            gce_boot_disk_size=_optional("GCE_BOOT_DISK_SIZE", "40GB"),
            gce_service_account=_optional("GCE_SERVICE_ACCOUNT", ""),
            gce_network=_optional("GCE_NETWORK", ""),
            gce_subnetwork=_optional("GCE_SUBNETWORK", ""),
            gce_scopes=_optional("GCE_SCOPES", "cloud-platform"),
            gce_tags=_csv_env("GCE_TAGS", "hermes-tenant"),
            gce_labels=_csv_env("GCE_LABELS", "app=hermes,component=tenant-agent"),
        )
