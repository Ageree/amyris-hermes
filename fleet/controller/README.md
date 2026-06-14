# Hermes Fleet Controller (M6)

A long-running reconcile loop on a GCE controller VM. Every ~3 s it polls
Convex `fleet:listReconcile`, diffs DESIRED vs ACTUAL state of each per-user
container, and drives Docker on host VM(s) toward desired state.

## Quick start

```bash
# Copy and fill in the env file
cp .env.example .env   # or set vars directly

# Single reconcile pass (smoke test)
./run.sh --once

# Production: use systemd (see hermes-controller.service)
sudo systemctl enable --now hermes-controller
```

## Environment contract

| Variable | Required | Default | Description |
|---|---|---|---|
| `CONVEX_URL` | yes | — | Convex deployment HTTP URL |
| `WORKER_SECRET` | yes | — | Shared secret for fleet:* Convex functions |
| `IMAGE` | yes | — | Docker image ref for per-user containers |
| `HOSTS` | yes | `localhost` | Comma-separated list of host VMs |
| `GCP_PROJECT` | no | `hermes-saved-content-lab` | GCP project ID |
| `GCP_REGION` | no | `us-central1` | GCP region |
| `GCS_BUCKET` | no | `hermes-fleet-state` | GCS bucket for per-user state |
| `POLL_INTERVAL_S` | no | `3.0` | Seconds between reconcile passes |
| `STALE_TTL_S` | no | `90.0` | Heartbeat age that triggers relaunch |
| `MAX_LAUNCH_FAILURES` | no | `3` | Consecutive failures before markError |
| `RAM_HEADROOM_PCT` | no | `30` | Minimum free RAM % required on a host |
| `MINIMAX_API_KEY` | yes | — | Passed to per-user containers |
| `SENDBLUE_API_KEY_ID` | yes | — | Passed to per-user containers |
| `SENDBLUE_API_SECRET` | yes | — | Passed to per-user containers |
| `TELEGRAM_BOT_TOKEN` | yes | — | Passed to per-user containers |
| `EXA_API_KEY` | yes | — | Passed to per-user containers |

Secret values are never logged. `WORKER_SECRET` is read from the environment
at each call and never stored on the config object.

## Reconcile state machine

```
Instance state               →  Action
─────────────────────────────────────────────────────────────────────────────
desired=running
  status ∈ {provisioning,stopped,error}, no containerId
                             →  LAUNCH
                                  1. placement: choose least-loaded host
                                  2. state_sync.rehydrate(userId)
                                  3. secrets.ensure_worker_secret(userId)
                                  4. docker run  →  containerId
                                  5. convex.claim_for_launch(userId, host, cid)
                                     • claimed=True  → done
                                     • claimed=False → docker stop (dup)

  status=running, no heartbeatAt
  OR heartbeatAt > STALE_TTL ago
                             →  RELAUNCH
                                  1. docker stop (old name)
                                  2. same as LAUNCH (rehydrate skipped)

  status=running, fresh heartbeatAt
                             →  NOOP  (healthy)

desired=stopped
  containerId present        →  STOP
                                  1. docker stop
                                  2. state_sync.mirror(userId)   ← after stop!
                                  3. convex.mark_stopped(userId)

  no containerId             →  NOOP

After MAX_LAUNCH_FAILURES consecutive docker-run failures
                             →  convex.mark_error + log ALERT
```

## Which legs are GCP-gated

| Capability | Requires GCP |
|---|---|
| `gcloud storage rsync` (state_sync) | yes — needs GCS bucket + ADC |
| `gcloud secrets` (secrets.py) | yes — needs Secret Manager + ADC |
| Per-user container Docker bind-mounts (`/data/tenants/<userId>`) | yes — host path must exist |
| Convex `fleet:*` mutations | yes — needs live Convex deployment |
| Docker `docker run / stop / ps / inspect` | no — runs locally on controller VM |

In local dev, all of the above are mocked via injectable fakes (see tests/).

## Running tests

```bash
cd fleet/controller
python3 -m pytest tests/ -q
```

All tests are network-free. Docker, gcloud, and Convex are injected as fakes.
