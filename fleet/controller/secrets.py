"""Secret Manager integration for per-instance worker secrets.

ensure_worker_secret(userId) returns the Secret Manager SECRET NAME
(e.g. "hermes-worker-<userId>") — never the secret value.

The actual secret value is injected into docker run env by reading
`gcloud secrets versions access latest --secret=<name>` at launch time.
This module only handles CREATE-IF-ABSENT idempotency.

`run_cmd` is injectable for test mocking.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Callable, Optional

logger = logging.getLogger(__name__)

RunCmd = Callable[..., subprocess.CompletedProcess]

_SECRET_PREFIX = "hermes-worker"


def _secret_name(user_id: str) -> str:
    # Only alphanumeric + hyphens allowed in Secret Manager names.
    safe = "".join(c if c.isalnum() else "-" for c in user_id)
    return f"{_SECRET_PREFIX}-{safe}"


class SecretManager:
    """Idempotent Secret Manager helper.

    Parameters
    ----------
    gcp_project:  GCP project ID.
    run_cmd:      Injectable subprocess runner.
    """

    def __init__(
        self,
        gcp_project: str,
        run_cmd: Optional[RunCmd] = None,
    ) -> None:
        if not gcp_project:
            raise ValueError("gcp_project must not be empty")
        self._project = gcp_project
        self._run = run_cmd or (lambda *a, **kw: subprocess.run(*a, **kw))

    def ensure_worker_secret(self, user_id: str) -> str:
        """Ensure a per-instance secret exists; return the secret NAME.

        Idempotent: if the secret already exists, returns the name without
        error.  The secret VALUE is never read or logged by this function.

        Parameters
        ----------
        user_id: The Convex user ID for this instance.

        Returns
        -------
        str: The Secret Manager secret name (e.g. "hermes-worker-abc123").
        """
        name = _secret_name(user_id)
        if self._secret_exists(name):
            logger.debug("secrets ensure user=%s name=%s (already exists)", user_id, name)
            return name

        logger.info("secrets create user=%s name=%s", user_id, name)
        self._create_secret(name)
        return name

    def secret_ref(self, user_id: str) -> str:
        """Return the full Secret Manager resource name for a user.

        projects/<project>/secrets/<name>
        """
        return f"projects/{self._project}/secrets/{_secret_name(user_id)}"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _secret_exists(self, name: str) -> bool:
        cmd = [
            "gcloud",
            "secrets",
            "describe",
            name,
            f"--project={self._project}",
            "--format=value(name)",
        ]
        try:
            result = self._run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as exc:
            logger.warning("secrets describe %s error: %s", name, exc)
            return False

    def _create_secret(self, name: str) -> None:
        # Create without any initial value; the value is set separately
        # (e.g. by a provisioning step or operator tool).
        cmd = [
            "gcloud",
            "secrets",
            "create",
            name,
            f"--project={self._project}",
            "--replication-policy=automatic",
        ]
        try:
            result = self._run(cmd, capture_output=True, text=True)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to create secret {name!r}: {exc}"
            ) from exc
        if result.returncode != 0:
            raise RuntimeError(
                f"gcloud secrets create {name!r} failed: {result.stderr.strip()}"
            )
