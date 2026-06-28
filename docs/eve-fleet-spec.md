# Eve Fleet — per-user GCP VM/container running Eve + browser-use

**Date:** 2026-06-28 · **Decided by operator:** full per-VM (each user = own container
running the FULL Eve brain + local browser-use + their persistent Chrome profile), on GCP
for now (`hermes-saved-content-lab`, host `hermes-fleet-host`, us-central1-a).

## Why this shape
RF has no consumer ordering API → the agent orders via browser automation. To keep a
per-user logged-in Yandex session (with the user's card) AND get a usable egress IP, each
user gets their OWN container: the user's Chrome profile (login + card in cookies) lives on
the container disk, and order.py drives that Chrome from the container's own IP. This is the
OLD Hermes fleet shape with the brain swapped Hermes→Eve.

> RU-egress caveat: GCP has no RU region → the container IP is non-RU (us-central1). Taxi/eda
> proven to work from a datacenter IP; Lavka's behavioral anti-bot may need a RU proxy later.
> Keep egress swappable (env `ORDER_PROXY`/RU-cloud migration) — NOT in this phase.

## Reuse (old Hermes fleet, proven in prod — do NOT rebuild)
- `fleet/controller/controller.py` — reconcile loop, per-user container provisioning,
  `_build_env`, heartbeat, crash-guard, GCS state sync.
- `control-plane/convex/{fleet.ts,messages.ts}` — `agentInstances` table, `requestInstance`,
  `claimInstanceForLaunch`, `heartbeat`, idle-reap, AND **`claimNextForUser(userId)`** (scoped
  claim) + **`claimNextAny`** (shared worker, skips fleeted users). Routing already done.
- `lab/docker/{Dockerfile.fleet,fleet-entrypoint.sh,cloudbuild.fleet.yaml}` — python3.12 +
  browser-harness + chromium + per-tenant Chrome profile + GCS, Cloud Build pipeline.
- `scripts/fleet/deploy-controller.sh` — gcloud scp/ssh + systemd install pattern.
- `features/browser_tasks/order.py` — the order engine (attaches via `ORDER_CDP_URL`).

## Build (new) — verified facts
- **Eve runs standalone** (KEYSTONE confirmed 2026-06-28): `node agent/.output/server/index.mjs`
  boots a Nitro server, serves `GET /eve/v1/health` → `200 {"ok":true,"status":"ready"}`. Reads
  `PORT`/`NITRO_PORT`/`NITRO_HOST`. `.output` is self-contained (5.5M, no node_modules needed).
- **Model without Vercel:** `agent/agent/agent.ts` already branches — set `MINIMAX_API_KEY`
  (+`MINIMAX_BASE_URL`,`MINIMAX_MODEL`) → direct OpenRouter, NO AI-Gateway/OIDC. (gateway string
  only when key unset.)
- **Ingress:** the Eve channel uses httpBasic `convex:<EVE_INGRESS_SECRET>`. The in-container
  poller calls `http://127.0.0.1:$EVE_PORT` with that secret.

### Container interface contract (all components MUST agree on these)
| Thing | Value |
|---|---|
| Eve server port | `EVE_PORT` (default `4123`), bound `127.0.0.1` |
| Eve health | `GET /eve/v1/health` |
| Chrome CDP | `http://127.0.0.1:9222` (headless, `--user-data-dir=$HERMES_HOME/chrome-profile`) |
| order.py attach | `ORDER_CDP_URL=http://127.0.0.1:9222` |
| Profile/state dir | `HERMES_HOME=/data/tenants/{userId}` (host bind mount, GCS-mirrored) |
| Scoped claim | `claimNextForUser({workerSecret, userId})` |
| Model | `MINIMAX_API_KEY`/`MINIMAX_BASE_URL`/`MINIMAX_MODEL` (direct OpenRouter) |
| Ingress secret | `EVE_INGRESS_SECRET` |
| Eve URL (poller) | `EVE_URL=http://127.0.0.1:$EVE_PORT` |

### Components to build
1. **`control-plane/drainer/drainer.mjs` scoped mode** — when `USER_ID` set: claim via
   `claimNextForUser(userId)` (not `claimNextAny`), loop only that user. Everything else
   (Eve call, order routing, rich, facts) UNCHANGED. EVE_URL/ORDER_CDP_URL point at localhost
   via env (already supported). Single new branch + a self-check.
2. **`lab/docker/eve-fleet-entrypoint.sh`** — tini child: launch headless Chrome (:9222,
   profile dir), launch `node /app/eve/.output/server/index.mjs` (EVE_PORT), wait for
   `/eve/v1/health`, then exec the scoped poller. All three in one container, ordered.
3. **`lab/docker/Dockerfile.eve-fleet`** — adapt `Dockerfile.fleet`: keep python/browser-harness/
   chromium layers; ADD node 24; COPY `agent/.output` → `/app/eve`; COPY drainer + order.py;
   pip install order.py deps (browser-use, playwright). CMD = eve-fleet-entrypoint.sh.
4. **`fleet/controller/controller.py` `_build_env`** — add `MINIMAX_*`, `EVE_INGRESS_SECRET`,
   `EVE_PORT`, `EVE_URL`, `ORDER_CDP_URL`; point `IMAGE` at the eve-fleet image. Minimal diff.
5. **`lab/docker/cloudbuild.eve-fleet.yaml`** — build+push `hermes-eve-fleet:$SHORT_SHA`.
6. **Onboarding/handoff** — first order → Chrome not logged into Yandex → order.py returns
   `NEED_LOGIN` → poller surfaces a live-view URL so the user logs into THEIR Yandex + adds
   THEIR card once (the per-user equivalent of browser-use cloud's live_url). v1 = a CDP
   screencast page or noVNC over the container's Chrome; pick the lightest. (HUMAN-gated step.)

## Verification ladder (each a real check)
1. Scoped poller self-check (claimNextForUser path) + `node --check`.
2. Local trio: Eve standalone + scoped poller (EVE_URL=localhost) + order.py local → a Convex
   test message for the operator's userId → claimed → answered → replied. (No Docker.)
3. Image builds (Cloud Build) green.
4. Operator's container provisioned on `hermes-fleet-host`; boots; heartbeats; `/eve/v1/health` ok.
5. A real inbound (operator) → his container orders (taxi/eda) a cart FROM the container IP →
   reply delivered. (Cart only — pay/login is the human handoff.)

## Out of scope (later)
- RU-egress (proxy / RU-cloud migration) — GCP non-RU IP for now.
- Real payment (human: Yandex login via handoff + per-order charge confirm).
- Autoscale tuning, multi-host, billing tiers (the controller already has the hooks).
