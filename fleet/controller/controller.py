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
import re
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
    # simple in-memory failure counter per userId (failed docker RUN)
    failure_counts: dict[str, int] = field(default_factory=dict)
    # Crash-loop guard (Bug H1): a container that docker-runs fine but DIES before
    # its first heartbeat would otherwise be relaunched forever (failure_counts
    # never increments). We count consecutive relaunches that did NOT produce a
    # heartbeat advance, and after max_launch_failures we markError + STOP
    # relaunching until desired/wantsAt is re-asserted.
    crash_counts: dict[str, int] = field(default_factory=dict)
    # last heartbeatAt observed per user (to detect a healthy advance between ticks)
    last_heartbeat_seen: dict[str, Optional[float]] = field(default_factory=dict)
    # users whose crash-loop tripped the guard, mapped to the wantsAt/desired
    # marker that was current when we blocked them. A change to that marker means
    # desired was re-asserted -> clear the block and allow a fresh launch.
    crash_blocked: dict[str, Any] = field(default_factory=dict)


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


def _desired_marker(instance: dict):
    """A value that CHANGES whenever 'desired' is (re-)asserted for an instance.

    Prefer `wantsAt` (a Convex timestamp bumped on every requestInstance /
    setDesired) and fall back to `desired` so the guard still works if wantsAt is
    absent. Used by the crash-loop guard to know when an operator/user has asked
    for the instance again, which should clear a previous error block.
    """
    if instance.get("wantsAt") is not None:
        return instance.get("wantsAt")
    return instance.get("desired")


def _crash_block_active(instance: dict, deps: ControllerDeps) -> bool:
    """True if this user is crash-loop-blocked AND desired hasn't been re-asserted.

    Clears (and returns False) the moment the desired marker changes — that's the
    signal an operator/user re-requested the instance, so we should try again.
    """
    user_id = instance.get("userId")
    if user_id not in deps.crash_blocked:
        return False
    if deps.crash_blocked[user_id] != _desired_marker(instance):
        # Desired re-asserted -> clear the block and the crash counter.
        deps.crash_blocked.pop(user_id, None)
        deps.crash_counts.pop(user_id, None)
        deps.last_heartbeat_seen.pop(user_id, None)
        return False
    return True


def _record_crash_relaunch(instance: dict, deps: ControllerDeps) -> bool:
    """Update the crash-relaunch counter for a relaunch about to happen.

    Returns True if the crash-loop threshold is now exceeded and the relaunch must
    be SUPPRESSED (instance marked error instead). A relaunch is a "crash relaunch"
    when the heartbeat has NOT advanced since the last time we relaunched this user;
    a heartbeat advance means the container became healthy, so the counter resets.
    """
    user_id = instance["userId"]
    hb = instance.get("heartbeatAt")
    prev_hb = deps.last_heartbeat_seen.get(user_id, "__unset__")

    healthy_advance = (
        hb is not None and prev_hb != "__unset__" and prev_hb is not None and hb > prev_hb
    )
    if healthy_advance:
        deps.crash_counts[user_id] = 0
    else:
        deps.crash_counts[user_id] = deps.crash_counts.get(user_id, 0) + 1
    deps.last_heartbeat_seen[user_id] = hb

    if deps.crash_counts[user_id] >= deps.cfg.max_launch_failures:
        logger.error(
            "ALERT: user=%s crash-looped %d relaunches with no healthy heartbeat — "
            "marking error and suspending relaunch until desired is re-asserted",
            user_id, deps.crash_counts[user_id],
        )
        try:
            deps.convex.mark_error(user_id, "crash-loop: container died before first heartbeat")
        except Exception as exc:
            logger.error("markError failed user=%s: %s", user_id, exc)
        deps.crash_blocked[user_id] = _desired_marker(instance)
        return True
    return False


def _sanitize_bu_name(user_id: str) -> str:
    """browser-harness daemon name for a tenant. BU_NAME must match
    ``[A-Za-z0-9_-]{1,64}``; Convex userIds already do, but sanitize defensively
    so a malformed id can never break the harness invocation."""
    name = re.sub(r"[^A-Za-z0-9_-]", "-", user_id or "")[:64]
    return name or "tenant"


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

    # Model endpoint MUST match the funded key or EVERY model call 401s (Bug C3).
    # The live key is an OpenRouter key (sk-or-*) → openrouter.ai/api/v1, model
    # minimax/minimax-m3; a native MiniMax key → api.minimax.io/v1, MiniMax-M3.
    # Derive base_url + model from the key prefix when the controller does not set
    # them explicitly, so a forgotten MINIMAX_BASE_URL can't silently break every
    # container. An explicit env value always wins (overridable).
    minimax_key = _get("MINIMAX_API_KEY")
    is_openrouter = minimax_key.startswith("sk-or-")
    minimax_base_url = os.environ.get("MINIMAX_BASE_URL", "").strip() or (
        "https://openrouter.ai/api/v1" if is_openrouter else "https://api.minimax.io/v1"
    )
    minimax_model = os.environ.get("MINIMAX_MODEL", "").strip() or (
        "minimax/minimax-m3" if is_openrouter else "MiniMax-M3"
    )

    # The names below MUST match EXACTLY what the worker's WorkerConfig.from_env()
    # bracket-reads, or the container crashes on boot (Bug C1). The worker reads:
    #   CONVEX_URL, WORKER_SECRET, SENDBLUE_API_KEY_ID, SENDBLUE_API_SECRET_KEY,
    #   SENDBLUE_FROM_NUMBER  (all required).
    # NOTE: ALLOWED_USER_NUMBER is INTENTIONALLY omitted — a scoped per-tenant
    #   worker routes each reply to the claimed message's own address (multi-tenant
    #   keystone); it must never be pinned to the operator's number.
    env = {
        "WORKER_MODE": "scoped",
        "USER_ID": user_id,
        "INSTANCE_ID": instance_id,
        "CONVEX_URL": cfg.convex_url,
        "WORKER_SECRET": _get("WORKER_SECRET"),
        "HERMES_HOME": f"/data/tenants/{user_id}",
        "MINIMAX_API_KEY": minimax_key,
        "MINIMAX_MODEL": minimax_model,
        "MINIMAX_BASE_URL": minimax_base_url,
        "SENDBLUE_API_KEY_ID": _get("SENDBLUE_API_KEY_ID"),
        "SENDBLUE_API_SECRET_KEY": _get("SENDBLUE_API_SECRET_KEY"),
        "SENDBLUE_FROM_NUMBER": _get("SENDBLUE_FROM_NUMBER"),
        "TELEGRAM_BOT_TOKEN": _get("TELEGRAM_BOT_TOKEN"),
        "EXA_API_KEY": _get("EXA_API_KEY"),
        # browser-harness (Lane B): per-user CDP browser, driven by Hermes via
        # the terminal tool. BU_NAME isolates the harness daemon per user;
        # BU_CDP_URL is the container-local headless Chrome the entrypoint
        # launches. Kill-switch BROWSER_HARNESS_ENABLED=0 keeps the built-in
        # browser. ponytail: local Chrome only; remote/cloud would set BU_CDP_WS.
        "BU_NAME": _sanitize_bu_name(user_id),
        "BU_CDP_URL": "http://127.0.0.1:9222",
        "BROWSER_HARNESS_ENABLED": os.environ.get("BROWSER_HARNESS_ENABLED", "1"),
    }
    # Per-instance Secret Manager ref — injected ONLY when the (not-yet-wired)
    # per-instance-secrets feature is on. The worker reads WORKER_SECRET directly and
    # NEVER WORKER_SECRET_REF, so injecting it by default would be a dead, misleading
    # env var (and would pair with empty Secret Manager secrets). See cfg docstring.
    if cfg.per_instance_secrets and secret_ref:
        env["WORKER_SECRET_REF"] = secret_ref
    return env


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

    # Crash-loop guard (Bug H1): after we markError a crash-looping instance its
    # status becomes "error", which _decide turns back into "launch". Suppress that
    # launch until desired/wantsAt is re-asserted, so we don't keep starting doomed
    # containers every ~3s.
    if _crash_block_active(instance, deps):
        logger.warning(
            "launch suppressed for user=%s — crash-loop blocked (awaiting desired re-assert)",
            user_id,
        )
        return {"action": "launch_suppressed_crashloop", "userId": user_id}

    # Placement: we need a real hosts_state; for now build a minimal one
    # from the running container counts on each host (best-effort).
    hosts_state = _build_hosts_state(cfg, deps.docker)
    host = choose_host(hosts_state, cfg.ram_headroom_pct)
    if host is None:
        logger.error("All hosts full — cannot launch user=%s", user_id)
        return {"action": "launch_refused", "userId": user_id, "reason": "hosts_full"}

    # Per-instance secret is OFF by default (v1 uses the shared WORKER_SECRET; the
    # per-instance read isn't wired in the worker). Only mint one when the feature
    # flag is on, so we don't create empty, enumerable Secret Manager secrets.
    secret_ref = deps.secrets.ensure_worker_secret(user_id) if cfg.per_instance_secrets else ""
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
    """Handle a stale or dead container — stop then re-launch.

    CRITICAL (relaunch self-kill): the Convex row is still status="running" here,
    and `claimInstanceForLaunch` returns claimed=false for a "running" row. So we
    MUST transition the row OFF "running" via `markStopped` BEFORE calling
    `_do_launch`; otherwise the freshly-started container loses the claim and
    `_do_launch` immediately `docker stop`s it as a "duplicate" — leaving the
    instance down and relaunched-then-killed every tick. `markStopped` sets
    status="stopped" but LEAVES desired="running" intact, so reconcile still wants
    it and the new claim now succeeds.
    """
    user_id = instance["userId"]
    name = _container_name(user_id)

    # Crash-loop guard (Bug H1): if this user is already error-blocked (and desired
    # hasn't been re-asserted), do NOT hammer docker again.
    if _crash_block_active(instance, deps):
        logger.warning(
            "relaunch suppressed for user=%s — crash-loop blocked (awaiting desired re-assert)",
            user_id,
        )
        return {"action": "relaunch_suppressed_crashloop", "userId": user_id}

    # Count this relaunch; if it trips the crash-loop threshold, mark error and
    # suppress the relaunch instead of starting yet another doomed container.
    if _record_crash_relaunch(instance, deps):
        deps.docker.stop(name)  # ensure the dead container is gone; do NOT relaunch
        return {"action": "relaunch_suppressed_crashloop", "userId": user_id}

    logger.info("relaunch user=%s (stale heartbeat or dead container)", user_id)
    deps.docker.stop(name)

    # Release the "running" claim so the relaunch can re-claim the slot. Best-effort:
    # a markStopped hiccup must not abort the relaunch (the claim may still succeed
    # if the row was already off "running"); log and continue.
    try:
        deps.convex.mark_stopped(user_id)
    except Exception as exc:
        logger.error("markStopped before relaunch failed user=%s: %s", user_id, exc)

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
        logger.warning("docker.ps() failed; placement will use zero counts", exc_info=True)
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
            "capacity": cfg.capacity_per_host,  # CAPACITY_PER_HOST; keep conservative
            # ponytail: ram_used_pct is a fabricated constant — placement refuses
            # only on the container COUNT (capacity_per_host) until a real per-host
            # /metrics agent feeds true RAM. Upgrade path: host-agent /metrics.
            "ram_used_pct": 40,
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
# Periodic crash-recovery mirror (deferred item #2)
# ---------------------------------------------------------------------------


def _mirror_running_tenants(deps: ControllerDeps) -> int:
    """Best-effort GCS mirror of every running tenant's state. Returns count mirrored.

    Closes deferred item #2: without this, state is mirrored only on a clean
    `docker stop` (_do_stop), so a host/controller crash loses everything written
    since the last stop. rehydrate-on-launch then restores the last mirror.

    ponytail: this mirrors a LIVE bind-mount, so a snapshot can catch a mid-write
    file; state_sync's WAL/journal/lock excludes skip the corruption-prone ones, and
    a slightly-stale crash snapshot beats total loss. The only strictly-consistent
    point remains the quiesce-then-mirror in _do_stop. Driven by MIRROR_INTERVAL_S.
    """
    try:
        instances = deps.convex.list_reconcile()
    except Exception as exc:  # fail-soft: a mirror miss must never kill the loop
        logger.error("periodic mirror: list_reconcile failed: %s", exc)
        return 0
    n = 0
    for inst in instances:
        if inst.get("status") == "running":
            uid = inst.get("userId")
            if uid:
                deps.state_sync.mirror(uid)  # fail-soft inside StateSync
                n += 1
    if n:
        logger.info("periodic mirror: mirrored %d running tenant(s)", n)
    return n


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
    last_mirror = deps.now_fn()

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

        # Periodic crash-recovery mirror (deferred #2); MIRROR_INTERVAL_S=0 disables.
        if cfg.mirror_interval_s > 0 and deps.now_fn() - last_mirror >= cfg.mirror_interval_s:
            _mirror_running_tenants(deps)
            last_mirror = deps.now_fn()

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
