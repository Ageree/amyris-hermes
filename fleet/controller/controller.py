"""Fleet controller — reconcile loop.

The controller polls Convex for the desired vs actual state of all per-user
containers and drives Docker on the host VMs toward desired state.

Architecture
------------
- reconcile_once(deps) — one full reconcile pass; injectable deps for testing.
- run(cfg)             — infinite loop that calls reconcile_once, backs off on
                         errors, and NEVER exits.

Reconcile state machine (per instance):
  1. desired=running, status in {provisioning,stopped,error}, no live container
       -> rehydrate GCS state
       -> ensure_worker_secret
       -> docker run
       -> claimInstanceForLaunch
       -> if claimed=False: docker stop (duplicate — another controller won)
  2. desired=running, status=running, heartbeatAt older than STALE_TTL
       -> docker inspect
       -> if dead: docker run (relaunch)
       -> after MAX_LAUNCH_FAILURES consecutive: markError + log alert
  3. desired=stopped, container is still running
       -> docker stop (quiesce)
       -> mirror state to GCS
       -> markStopped
  4. desired=running, status=running, container live + heartbeat fresh
       -> no action (healthy)
  5. all other combinations
       -> no action (skip)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from config import ControllerConfig
from convex_admin import ConvexAdminClient
from docker_driver import DockerDriver
from placement import choose_host
from secrets import SecretManager
from state_sync import StateSync

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dependency bundle (injectable for tests)
# ---------------------------------------------------------------------------


@dataclass
class ControllerDeps:
    """All collaborators needed by reconcile_once."""

    cfg: ControllerConfig
    convex: ConvexAdminClient
    docker: DockerDriver
    state_sync: StateSync
    secrets: SecretManager
    # clock: injectable for tests
    now_fn: Callable[[], float] = field(default_factory=lambda: time.time)
    # simple in-memory failure counter per userId
    failure_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Decision helpers (pure / testable)
# ---------------------------------------------------------------------------

_LAUNCH_STATUSES = {"provisioning", "stopped", "error"}


def _decide(instance: dict, deps: ControllerDeps) -> str:
    """Return an action keyword for this instance.

    Actions:
        "launch"     — cold-start a new container
        "relaunch"   — stale heartbeat, restart
        "stop"       — desired=stopped but container running
        "noop"       — nothing to do
        "skip"       — unrecognised / terminal state
    """
    desired = instance.get("desired")
    status = instance.get("status")
    container_id = instance.get("containerId")
    heartbeat_at = instance.get("heartbeatAt")  # epoch ms or None
    now_ms = deps.now_fn() * 1000
    stale_ttl_ms = deps.cfg.stale_ttl_s * 1000

    if desired == "running":
        if status in _LAUNCH_STATUSES and not container_id:
            return "launch"
        if status == "running":
            if heartbeat_at is None:
                return "relaunch"
            age_ms = now_ms - heartbeat_at
            if age_ms > stale_ttl_ms:
                return "relaunch"
            # Healthy
            return "noop"
        return "skip"

    if desired == "stopped":
        if container_id:
            return "stop"
        return "noop"

    logger.warning("Unknown desired state %r for user %s", desired, instance.get("userId"))
    return "skip"


def _container_name(user_id: str) -> str:
    """Stable, non-secret container name for a user."""
    safe = "".join(c if c.isalnum() else "-" for c in user_id)
    return f"hermes-{safe}"


def _build_env(user_id: str, instance_id: str, cfg: ControllerConfig, secret_ref: str) -> dict[str, str]:
    """Build the env dict for docker run.

    Secret VALUES come from the OS environment; they are passed through
    to the container but never logged by this function.
    """
    def _get(name: str) -> str:
        v = os.environ.get(name, "")
        if not v:
            logger.warning("env var %s is not set — container may misbehave", name)
        return v

    return {
        "WORKER_MODE": "scoped",
        "USER_ID": user_id,
        "INSTANCE_ID": instance_id,
        "CONVEX_URL": cfg.convex_url,
        "WORKER_SECRET": _get("WORKER_SECRET"),
        "HERMES_HOME": f"/data/tenants/{user_id}",
        "MINIMAX_API_KEY": _get("MINIMAX_API_KEY"),
        "MINIMAX_MODEL": os.environ.get("MINIMAX_MODEL", "MiniMax-M3"),
        "SENDBLUE_API_KEY_ID": _get("SENDBLUE_API_KEY_ID"),
        "SENDBLUE_API_SECRET": _get("SENDBLUE_API_SECRET"),
        "TELEGRAM_BOT_TOKEN": _get("TELEGRAM_BOT_TOKEN"),
        "EXA_API_KEY": _get("EXA_API_KEY"),
        # Secret Manager ref (not the value)
        "WORKER_SECRET_REF": secret_ref,
    }


def _build_mounts(user_id: str) -> list[str]:
    local_dir = f"/data/tenants/{user_id}"
    container_dir = f"/data/tenants/{user_id}"
    return [f"{local_dir}:{container_dir}"]


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


def _do_launch(instance: dict, deps: ControllerDeps) -> dict:
    """Execute a cold-start launch. Returns action summary dict."""
    user_id = instance["userId"]
    instance_id = instance.get("instanceId", user_id)
    cfg = deps.cfg

    # Placement: we need a real hosts_state; for now build a minimal one
    # from the running container counts on each host (best-effort).
    hosts_state = _build_hosts_state(cfg, deps.docker)
    host = choose_host(hosts_state, cfg.ram_headroom_pct)
    if host is None:
        logger.error("All hosts full — cannot launch user=%s", user_id)
        return {"action": "launch_refused", "userId": user_id, "reason": "hosts_full"}

    secret_ref = deps.secrets.ensure_worker_secret(user_id)
    deps.state_sync.rehydrate(user_id)

    env = _build_env(user_id, instance_id, cfg, secret_ref)
    mounts = _build_mounts(user_id)
    name = _container_name(user_id)

    try:
        container_id = deps.docker.run(cfg.image, name, env, mounts)
    except Exception as exc:
        logger.error("docker run failed user=%s: %s", user_id, exc)
        count = deps.failure_counts.get(user_id, 0) + 1
        deps.failure_counts[user_id] = count
        if count >= cfg.max_launch_failures:
            logger.error(
                "ALERT: user=%s exceeded MAX_LAUNCH_FAILURES (%d)", user_id, cfg.max_launch_failures
            )
            try:
                deps.convex.mark_error(user_id, str(exc))
            except Exception as merr:
                logger.error("markError failed user=%s: %s", user_id, merr)
        return {"action": "launch_failed", "userId": user_id, "error": str(exc)}

    # Claim the slot — another controller may have won the race.
    try:
        claim_result = deps.convex.claim_for_launch(
            user_id=user_id,
            host_vm=host,
            container_id=container_id,
            worker_secret_ref=secret_ref,
        )
    except Exception as exc:
        logger.error("claim_for_launch failed user=%s: %s", user_id, exc)
        deps.docker.stop(name)
        return {"action": "launch_claim_error", "userId": user_id, "error": str(exc)}

    if not claim_result.get("claimed", False):
        logger.info(
            "claim_for_launch: not claimed (race lost) user=%s — stopping duplicate", user_id
        )
        deps.docker.stop(name)
        return {"action": "launch_duplicate_stopped", "userId": user_id}

    deps.failure_counts[user_id] = 0
    logger.info("launch ok user=%s container=%.12s host=%s", user_id, container_id, host)
    return {"action": "launched", "userId": user_id, "containerId": container_id, "host": host}


def _do_relaunch(instance: dict, deps: ControllerDeps) -> dict:
    """Handle a stale or dead container — stop then re-launch."""
    user_id = instance["userId"]
    name = _container_name(user_id)

    logger.info("relaunch user=%s (stale heartbeat or dead container)", user_id)
    deps.docker.stop(name)
    # Reuse launch path (no GCS mirror on relaunch — state is live on disk)
    return _do_launch(instance, deps)


def _do_stop(instance: dict, deps: ControllerDeps) -> dict:
    """Quiesce, mirror to GCS, stop container, markStopped."""
    user_id = instance["userId"]
    name = _container_name(user_id)
    container_id = instance.get("containerId") or name

    logger.info("stop user=%s container=%s", user_id, container_id)

    # Stop first (quiesce), then mirror (safe to read filesystem)
    deps.docker.stop(name)
    deps.state_sync.mirror(user_id)

    try:
        deps.convex.mark_stopped(user_id)
    except Exception as exc:
        logger.error("markStopped failed user=%s: %s", user_id, exc)

    return {"action": "stopped", "userId": user_id}


# ---------------------------------------------------------------------------
# Placement helper (best-effort; real impl needs host metrics API)
# ---------------------------------------------------------------------------


def _build_hosts_state(cfg: ControllerConfig, docker: DockerDriver) -> list[dict]:
    """Build a minimal hosts_state list.

    In a real deployment this would query host metrics (RAM %).
    Here we use the docker ps count as a proxy; RAM is set to a safe
    default so placement still works in tests.
    """
    try:
        running_containers = docker.ps()
    except Exception:
        running_containers = []

    # Count by host name prefix (best-effort heuristic)
    # In production: query /metrics on each host agent.
    counts: dict[str, int] = {h: 0 for h in cfg.hosts}
    for c in running_containers:
        cname = c.get("Names", "")
        for host in cfg.hosts:
            if host in cname:
                counts[host] = counts.get(host, 0) + 1

    return [
        {
            "host": host,
            "running": counts.get(host, 0),
            "capacity": 50,          # reasonable per-VM default
            "ram_used_pct": 40,       # assume moderate load; real impl: query host
        }
        for host in cfg.hosts
    ]


# ---------------------------------------------------------------------------
# reconcile_once — one full pass
# ---------------------------------------------------------------------------


def reconcile_once(deps: ControllerDeps) -> list[dict]:
    """Execute a single reconcile pass.

    Returns a list of action summary dicts (one per acted-on instance).
    """
    instances = deps.convex.list_reconcile()
    logger.debug("reconcile_once: %d instances", len(instances))

    actions = []
    for instance in instances:
        user_id = instance.get("userId", "<unknown>")
        try:
            action = _decide(instance, deps)
            if action == "launch":
                result = _do_launch(instance, deps)
                actions.append(result)
            elif action == "relaunch":
                result = _do_relaunch(instance, deps)
                actions.append(result)
            elif action == "stop":
                result = _do_stop(instance, deps)
                actions.append(result)
            elif action == "noop":
                pass
            else:
                logger.debug("skip user=%s status=%s desired=%s", user_id,
                             instance.get("status"), instance.get("desired"))
        except Exception as exc:
            logger.error("reconcile_once error for user=%s: %s", user_id, exc)
            actions.append({"action": "error", "userId": user_id, "error": str(exc)})

    return actions


# ---------------------------------------------------------------------------
# run — the immortal loop
# ---------------------------------------------------------------------------


def run(cfg: Optional[ControllerConfig] = None, *, once: bool = False) -> None:
    """Start the reconcile loop.  Never exits unless `once=True`.

    Parameters
    ----------
    cfg:    ControllerConfig (loaded from env if None).
    once:   If True, run exactly one reconcile pass and return (--once flag).
    """
    if cfg is None:
        cfg = ControllerConfig.from_env()

    logger.info("fleet-controller starting config=%s", cfg.redacted())

    deps = ControllerDeps(
        cfg=cfg,
        convex=ConvexAdminClient(cfg.convex_url),
        docker=DockerDriver(),
        state_sync=StateSync(cfg.gcs_bucket),
        secrets=SecretManager(cfg.gcp_project),
    )

    backoff = 1.0

    while True:
        try:
            actions = reconcile_once(deps)
            if actions:
                logger.info("reconcile actions=%d", len(actions))
            backoff = 1.0  # reset on success
        except Exception as exc:
            logger.error("reconcile_once unhandled exception: %s", exc, exc_info=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

        if once:
            return

        time.sleep(cfg.poll_interval_s)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Fleet controller")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single reconcile pass and exit (for local harness / health check)",
    )
    args = parser.parse_args()

    run(once=args.once)
