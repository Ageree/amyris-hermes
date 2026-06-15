"""Docker driver for the fleet controller.

Wraps the `docker` CLI via subprocess.  The `run_cmd` callable is injectable
so unit tests can pass a fake without ever touching real Docker.

Security notes:
- Secret VALUES (WORKER_SECRET, API keys) are passed via `env` at runtime but
  NEVER written to container names, log lines, or intermediate files.
- Container names use only userId (safe, non-secret identifier).
- ponytail: `docker run --env K=V` puts values on the argv, so they are visible
  to same-host users via `ps`/`/proc/<pid>/cmdline` and in `docker inspect`. On
  the v1 single co-located VM the controller and containers share ONE trust
  domain (the `hermes-fleet` user already reads controller.env), so no trust
  boundary is crossed. Upgrade path if hosts ever become multi-tenant across
  trust domains: write a mode-0600 temp env-file and pass `--env-file` instead.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Type alias for the injectable runner
RunCmd = Callable[..., subprocess.CompletedProcess]


def _default_run(*args, **kwargs) -> subprocess.CompletedProcess:
    """Default subprocess runner."""
    return subprocess.run(*args, **kwargs)


class DockerDriver:
    """Thin wrapper around the docker CLI.

    Parameters
    ----------
    run_cmd:
        Injectable callable with the same signature as `subprocess.run`.
        Pass a fake in tests.
    """

    def __init__(self, run_cmd: Optional[RunCmd] = None) -> None:
        self._run = run_cmd or _default_run

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        image: str,
        name: str,
        env: dict[str, str],
        mounts: Optional[list[str]] = None,
    ) -> str:
        """Start a container and return its container ID.

        Parameters
        ----------
        image:  Docker image ref.
        name:   Container name (must be unique on the host).
        env:    Environment variables to pass.  Values are never logged.
        mounts: Optional list of host-path:container-path[:mode] strings.

        Returns the trimmed container ID on success.
        Raises RuntimeError on failure.
        """
        cmd = ["docker", "run", "--detach", "--name", name]
        for key, value in env.items():
            cmd += ["--env", f"{key}={value}"]
        if mounts:
            for mount in mounts:
                cmd += ["--volume", mount]
        cmd.append(image)

        logger.info("docker run name=%s image=%s", name, image)
        result = self._run(
            cmd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"docker run failed (name={name}): {result.stderr.strip()}"
            )
        container_id = result.stdout.strip()
        logger.info("docker run ok name=%s container_id=%.12s", name, container_id)
        return container_id

    def stop(self, name_or_id: str) -> None:
        """Stop a running container.  Logs a warning if it is not found."""
        cmd = ["docker", "stop", name_or_id]
        logger.info("docker stop %s", name_or_id)
        result = self._run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # Non-zero can mean the container is already gone — warn, don't raise.
            logger.warning(
                "docker stop %s exited %d: %s",
                name_or_id,
                result.returncode,
                result.stderr.strip(),
            )

    def inspect(self, name_or_id: str) -> Optional[dict]:
        """Return the first inspect record dict, or None if not found/running."""
        import json as _json

        cmd = ["docker", "inspect", name_or_id]
        result = self._run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        try:
            records = _json.loads(result.stdout)
            if not records:
                return None
            return records[0]
        except Exception as exc:
            logger.error("docker inspect parse error for %s: %s", name_or_id, exc)
            return None

    def ps(self) -> list[dict]:
        """List running containers as a list of dicts with 'ID' and 'Names'."""
        import json as _json

        cmd = [
            "docker",
            "ps",
            "--format",
            '{"ID":"{{.ID}}","Names":"{{.Names}}"}',
        ]
        result = self._run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("docker ps failed: %s", result.stderr.strip())
            return []
        containers = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                containers.append(_json.loads(line))
            except Exception as exc:
                logger.warning("docker ps parse line error: %s | %s", exc, line)
        return containers

    def is_running(self, name_or_id: str) -> bool:
        """Return True if the container exists and is in 'running' state."""
        record = self.inspect(name_or_id)
        if record is None:
            return False
        state = record.get("State", {})
        return state.get("Running", False) is True
