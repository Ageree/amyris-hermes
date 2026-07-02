"""GCE VM runtime driver for one-VM-per-user agents.

The controller can use this instead of DockerDriver by setting
RUNTIME_BACKEND=gce_vm. Each tenant gets one stopped/running Compute Engine VM
that runs the existing fleet container with the tenant's Chrome profile on that
VM's persistent boot disk.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

RunCmd = Callable[..., subprocess.CompletedProcess[Any]]
MOUNT_BASIC_PARTS = 2
MOUNT_WITH_MODE_PARTS = 3


def _default_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(*args, check=False, **kwargs)


@dataclass(frozen=True)
class GceVmConfig:
    project: str
    zone: str
    machine_type: str
    boot_disk_size: str
    service_account: str
    network: str
    subnetwork: str
    scopes: str
    tags: tuple[str, ...]
    labels: tuple[str, ...]


class GceVmDriver:
    """Thin `gcloud compute instances` wrapper with DockerDriver-like methods."""

    def __init__(self, cfg: GceVmConfig, run_cmd: RunCmd | None = None) -> None:
        self._cfg = cfg
        self._run = run_cmd or _default_run

    def run(
        self,
        image: str,
        name: str,
        env: dict[str, str],
        mounts: list[str] | None = None,
    ) -> str:
        existing = self.inspect(name)
        if existing is not None:
            status = str(existing.get("status", ""))
            if status != "RUNNING":
                self._gcloud(["compute", "instances", "start", name])
            logger.info("gce start ok name=%s status=%s", name, status)
            return name

        cmd = [
            "compute",
            "instances",
            "create-with-container",
            name,
            "--machine-type",
            self._cfg.machine_type,
            "--boot-disk-size",
            self._cfg.boot_disk_size,
            "--container-image",
            image,
            "--container-restart-policy",
            "always",
            "--metadata",
            f"google-logging-enabled=true,startup-script={_startup_script(mounts)}",
        ]
        if self._cfg.service_account:
            cmd.extend(["--service-account", self._cfg.service_account])
        if self._cfg.scopes:
            cmd.extend(["--scopes", self._cfg.scopes])
        if self._cfg.network:
            cmd.extend(["--network", self._cfg.network])
        if self._cfg.subnetwork:
            cmd.extend(["--subnet", self._cfg.subnetwork])
        if self._cfg.tags:
            cmd.extend(["--tags", ",".join(self._cfg.tags)])
        labels = dict(_split_kv(v) for v in self._cfg.labels)
        labels.setdefault("hermes-tenant", "true")
        cmd.extend(["--labels", ",".join(f"{k}={v}" for k, v in labels.items())])
        for key, value in env.items():
            cmd.extend(["--container-env", f"{key}={value}"])
        for mount in mounts or []:
            host_path, mount_path, mode = _mount_parts(mount)
            cmd.extend(
                [
                    "--container-mount-host-path",
                    f"host-path={host_path},mount-path={mount_path},mode={mode}",
                ]
            )

        logger.info("gce create-with-container name=%s image=%s", name, image)
        self._gcloud(cmd)
        return name

    def stop(self, name_or_id: str) -> None:
        logger.info("gce stop %s", name_or_id)
        result = self._gcloud(
            ["compute", "instances", "stop", name_or_id],
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "gce stop %s exited %d: %s",
                name_or_id,
                result.returncode,
                result.stderr.strip(),
            )

    def inspect(self, name_or_id: str) -> dict[str, Any] | None:
        result = self._gcloud(
            ["compute", "instances", "describe", name_or_id, "--format=json"],
            check=False,
        )
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.error("gce describe parse error for %s: %s", name_or_id, exc)
            return None

    def ps(self) -> list[dict[str, str]]:
        result = self._gcloud(
            [
                "compute",
                "instances",
                "list",
                "--filter=labels.hermes-tenant=true AND status=RUNNING",
                "--format=json",
            ],
            check=False,
        )
        if result.returncode != 0:
            logger.error("gce list failed: %s", result.stderr.strip())
            return []
        try:
            rows = json.loads(result.stdout)
        except Exception:
            return []
        if not isinstance(rows, list):
            return []
        return [
            {"ID": str(r.get("id", "")), "Names": str(r.get("name", ""))}
            for r in rows
            if isinstance(r, dict)
        ]

    def is_running(self, name_or_id: str) -> bool:
        record = self.inspect(name_or_id)
        return bool(record and record.get("status") == "RUNNING")

    def _gcloud(
        self,
        args: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[Any]:
        cmd = [
            "gcloud",
            *args,
            "--project",
            self._cfg.project,
            "--quiet",
        ]
        if args[:3] != ["compute", "instances", "list"]:
            cmd.extend(["--zone", self._cfg.zone])
        result = self._run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(
                f"gcloud {' '.join(args[:3])} failed: {result.stderr.strip()}"
            )
        return result


def _split_kv(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"label must be k=v, got {raw!r}")
    k, v = raw.split("=", 1)
    return k.strip(), v.strip()


def _mount_parts(mount: str) -> tuple[str, str, str]:
    parts = mount.split(":")
    if len(parts) == MOUNT_BASIC_PARTS:
        return parts[0], parts[1], "rw"
    if len(parts) == MOUNT_WITH_MODE_PARTS:
        return parts[0], parts[1], parts[2]
    raise ValueError(f"mount must be host:container[:mode], got {mount!r}")


def _startup_script(mounts: list[str] | None) -> str:
    dirs: list[str] = []
    for mount in mounts or []:
        host_path, _, _ = _mount_parts(mount)
        dirs.append(host_path)
    if not dirs:
        return "#!/bin/sh\nexit 0"
    lines = ["#!/bin/sh", "set -eu"]
    for path in dirs:
        lines.append(f"mkdir -p {path!r}")
        lines.append(f"chown 10001:10001 {path!r} || true")
    return "\n".join(lines)
