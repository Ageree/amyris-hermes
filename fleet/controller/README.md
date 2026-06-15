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
| `CONVEX_URL` | yes | — | Convex **admin** URL `https://<deployment>.convex.cloud` (NOT the `.convex.site` webhook host — the controller POSTs `/api/query` + `/api/mutation`) |
| `WORKER_SECRET` | yes | — | Shared secret for fleet:* Convex functions |
| `IMAGE` | yes | — | Docker image ref for per-user containers (e.g. `us-central1-docker.pkg.dev/<proj>/saved-content/hermes-fleet:<sha>`) |
| `HOSTS` | yes | `localhost` | Comma-separated host VMs. v1 = a single co-located VM → `localhost` |
| `GCP_PROJECT` | no | `hermes-saved-content-lab` | GCP project ID |
| `GCP_REGION` | no | `us-central1` | GCP region |
| `GCS_BUCKET` | no | `hermes-fleet-state` | GCS bucket for per-user state |
| `POLL_INTERVAL_S` | no | `3.0` | Seconds between reconcile passes |
| `STALE_TTL_S` | no | `90.0` | Heartbeat age that triggers relaunch (set `240` ≥ worst-case Hermes turn so the reaper never fires mid-turn) |
| `MAX_LAUNCH_FAILURES` | no | `3` | Consecutive failures before markError |
| `RAM_HEADROOM_PCT` | no | `30` | Minimum free RAM % required on a host |
| `CAPACITY_PER_HOST` | no | `50` | Max containers per host. Keep CONSERVATIVE (e.g. `5`) on a single VM until a real /metrics agent exists |
| `PER_INSTANCE_SECRETS` | no | `0` | OFF for v1 (shared WORKER_SECRET). The per-instance read is NOT wired — flipping on only mints empty secrets. |
| `MINIMAX_API_KEY` | yes | — | Injected into containers. The live key is an **OpenRouter** key (`sk-or-*`) |
| `MINIMAX_BASE_URL` | no | derived | Auto-derived from the key prefix: `sk-or-*` → `https://openrouter.ai/api/v1`, else `https://api.minimax.io/v1`. **An explicit value wins** — set it to be safe. |
| `MINIMAX_MODEL` | no | derived | `sk-or-*` → `minimax/minimax-m3`, else `MiniMax-M3` |
| `SENDBLUE_API_KEY_ID` | yes | — | Injected into containers |
| `SENDBLUE_API_SECRET_KEY` | yes | — | Injected into containers (**exact name** — the worker reads `SENDBLUE_API_SECRET_KEY`, NOT `SENDBLUE_API_SECRET`) |
| `SENDBLUE_FROM_NUMBER` | yes | — | Injected into containers (the iMessage sender number) |
| `TELEGRAM_BOT_TOKEN` | no | — | Injected into containers (Telegram channel) |
| `EXA_API_KEY` | no | — | Injected into containers (web search) |

Secret values are never logged. `WORKER_SECRET` is read from the environment
at each call and never stored on the config object. `MINIMAX_BASE_URL`/
`MINIMAX_MODEL` are derived from the key prefix at launch (Bug C3) so a forgotten
`MINIMAX_BASE_URL` can't silently 401 every container; set them explicitly to be
unambiguous.

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
                                     • ONLY when PER_INSTANCE_SECRETS=1 (off by
                                       default → shared WORKER_SECRET, no secret minted)
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
