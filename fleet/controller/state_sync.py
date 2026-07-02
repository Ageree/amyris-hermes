"""GCS state sync for per-user Hermes state.

rehydrate(userId): pull state from GCS into the local bind-mount before launch.
mirror(userId):    push local bind-mount state to GCS after quiesce.

Both use `gcloud storage rsync` via subprocess.

Key rules:
- Caller MUST stop the container BEFORE calling mirror() — this module does
  not enforce quiesce; it trusts the caller.
- Lockfiles and SQLite WAL/journal files are excluded to avoid corrupting
  state on restore.
- FAIL-SOFT + logged: a sync error is never fatal to the reconcile loop.
- `run_cmd` is injectable (defaults to subprocess.run) for test mocking.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Callable, Optional

logger = logging.getLogger(__name__)

RunCmd = Callable[..., subprocess.CompletedProcess]

# `gcloud storage rsync --exclude` takes a PYTHON REGEX, not a glob — a glob like
# "*.lock" is an invalid regex ("nothing to repeat at position 0") and crashes the
# whole rsync (caught live: every mirror/rehydrate failed). One combined regex,
# matched on the path tail, drops live lock / SQLite WAL+journal / Chrome singleton
# files so a restored snapshot can't carry a stale lock that corrupts state.
_EXCLUDE_REGEX = r".*\.lock$|.*SingletonLock$|.*SingletonSocket$|.*SingletonCookie$|.*-journal$|.*-wal$"


def _build_exclude_args() -> list[str]:
    return ["--exclude", _EXCLUDE_REGEX]


class StateSync:
    """Rehydrate and mirror per-user Hermes state via GCS.

    Parameters
    ----------
    gcs_bucket:    Name of the GCS bucket (without gs:// prefix).
    local_root:    Local root directory for per-user state
                   (typically /data/tenants on the host VM).
    run_cmd:       Injectable runner (defaults to subprocess.run).
    """

    def __init__(
        self,
        gcs_bucket: str,
        local_root: str = "/data/tenants",
        run_cmd: Optional[RunCmd] = None,
    ) -> None:
        if not gcs_bucket:
            raise ValueError("gcs_bucket must not be empty")
        self._bucket = gcs_bucket.strip().rstrip("/")
        self._local_root = local_root.rstrip("/")
        self._run = run_cmd or (lambda *a, **kw: subprocess.run(*a, **kw))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rehydrate(self, user_id: str) -> bool:
        """Pull state from GCS to local bind-mount.

        Returns True on success, False on failure (FAIL-SOFT).
        Call this BEFORE starting the container.
        """
        gcs_path = self._gcs_path(user_id)
        local_path = self._local_path(user_id)
        # Ensure the bind-mount SOURCE dir exists BEFORE docker run (Bug C5). The
        # controller runs as the same uid (10001) as the container's non-root user,
        # so a dir it creates is container-writable. Without this, docker would
        # create the mount source as root → the container's uid 10001 gets EACCES on
        # HERMES_HOME. We create it as ourselves (no chown — NoNewPrivileges-safe).
        try:
            os.makedirs(local_path, exist_ok=True)
        except OSError as exc:
            logger.error("state_sync rehydrate user=%s mkdir %s failed: %s",
                         user_id, local_path, exc)
            return False
        return self._rsync(
            src=gcs_path,
            dst=local_path,
            user_id=user_id,
            direction="rehydrate",
        )

    def mirror(self, user_id: str) -> bool:
        """Push local bind-mount state to GCS.

        Returns True on success, False on failure (FAIL-SOFT).
        CALLER MUST STOP THE CONTAINER before calling this.
        """
        gcs_path = self._gcs_path(user_id)
        local_path = self._local_path(user_id)
        return self._rsync(
            src=local_path,
            dst=gcs_path,
            user_id=user_id,
            direction="mirror",
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _gcs_path(self, user_id: str) -> str:
        return f"gs://{self._bucket}/tenants/{user_id}/"

    def _local_path(self, user_id: str) -> str:
        return f"{self._local_root}/{user_id}/"

    def _rsync(
        self,
        src: str,
        dst: str,
        user_id: str,
        direction: str,
    ) -> bool:
        cmd = [
            "gcloud",
            "storage",
            "rsync",
            "--recursive",
            "--delete-unmatched-destination-objects",
        ] + _build_exclude_args() + [src, dst]

        logger.info("state_sync %s user=%s src=%s dst=%s", direction, user_id, src, dst)
        try:
            result = self._run(
                cmd,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            logger.error(
                "state_sync %s user=%s subprocess error: %s", direction, user_id, exc
            )
            return False

        if result.returncode != 0:
            logger.error(
                "state_sync %s user=%s failed (exit %d): %s",
                direction,
                user_id,
                result.returncode,
                result.stderr.strip(),
            )
            return False

        logger.info("state_sync %s user=%s ok", direction, user_id)
        return True
