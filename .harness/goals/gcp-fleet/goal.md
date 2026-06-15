# Goal: GCP per-user container fleet (replace the live shared bridge worker)

## Objective

The multi-tenant system is fully built and LIVE today using a single **shared
bridge worker** (`WORKER_MODE=shared`, Convex mutation `claimNextAny`) that
serves every tenant from one process. The LOCKED architecture decision is **one
container per user** — a GCP fleet where each tenant gets a dedicated Hermes
worker container with its own persistent state (browser logins, SOUL.md,
history). The M6 code for this exists (`fleet/controller/`, `lab/docker/
Dockerfile.fleet`, `control-plane/convex/fleet.ts`, `scripts/fleet/
provision-host.sh`) but **no real container has ever run** and **the image is
unbuildable**. This goal makes the fleet real, live, and verified — then cuts
over from the shared worker to the fleet without losing or duplicating a single
message.

## Scope (the work)

1. **Make the image buildable & pushable** to Artifact Registry.
   - `Dockerfile.fleet:101` clones `github.com/your-org/hermes-agent.git`
     (placeholder). Real Hermes source is the PUBLIC repo
     `github.com/Ageree/hermes-agent.git` → fix the org.
   - `cloudbuild.fleet.yaml` pushes to `.../$PROJECT_ID/hermes/hermes-fleet` but
     the real AR repo is `saved-content` → fix the repo path.
   - Containers run as root (no `USER`) → add a non-root user (security).
2. **Build + push the image, stand up ONE real GCE VM + Docker container.**
3. **Cutover**: the shared worker (`claimNextAny`) must coexist with the fleet,
   then flip — with zero message loss and zero double-processing. This unblocks
   the deferred **M7 destructive tighten** (remove `claimNext` /
   `ALLOWED_USER_NUMBER`, tighten the schema).
4. **Close the deferred fleet items** that the first real live e2e needs
   (`docs/superpowers/plans/2026-06-15-review-findings-and-deferrals.md`):
   per-host `/metrics` for placement, periodic GCS state mirror, per-instance
   secrets (vs the shared `WORKER_SECRET`), non-root containers — closing the
   security-relevant ones; consciously deferring what the single-VM e2e doesn't
   need (marked with a `ponytail:` rationale).

## Hard constraints

- **Live/paid/irreversible GCP steps are OPERATOR-CHECKPOINTED.** Before running
  any of: enable Compute Engine API, `docker push` / `gcloud builds submit`,
  `gcloud compute instances create`, flipping `WORKER_MODE`, the M7 destructive
  tighten — present the exact command + rationale to the operator and WAIT for
  approval. These are never run inside parallel agents.
- **File edits happen in a git worktree** (this one: `worktree-gcp-fleet`), never
  the live cockpit checkout.
- **Verification is on REAL GCP, not mocks.** Live e2e runs against the live dev
  Convex deployment **zany-tapir-501**.
- The fleet must serve **both channels** (iMessage/Sendblue + Telegram) per
  tenant; reply routing is **per-message** (`replyTarget` on the claimed row),
  never a global `ALLOWED_USER_NUMBER`.
- Model config is **OpenRouter** today (`minimax/minimax-m3`, `sk-or-` key,
  `openrouter.ai/api/v1`) — the fleet container env MUST match this or every
  container fails model auth. (`controller.py:_build_env` defaults to native
  MiniMax and is overridable — provisioning must inject the OpenRouter values.)

## GCP facts (locked)

- Project: **hermes-saved-content-lab** (number 7700387935), account
  **solsav1703@gmail.com** (active; `nikto256@gmail.com` has NO access).
- Billing ON. Cloud Build + Artifact Registry + Secret Manager enabled.
  **Compute Engine API NOT yet enabled** (checkpoint step).
- AR repo: **saved-content** in **us-central1** (DOCKER). Hermes source repo
  `Ageree/hermes-agent` is PUBLIC (Cloud Build can clone, no creds).

## What "done" means

A real GCE VM runs the controller; a real per-tenant container cold-starts on an
inbound message, serves a full reply on BOTH channels, and is idle-reaped — for
a real tenant on the live dev Convex. Two tenants run concurrently with no
cross-leak. The shared→fleet cutover loses/dups zero messages. Independent
isolated audit agents re-verify isolation, runtime-readiness, and the
producer↔consumer contracts. (Concrete, testable rows in `acceptance.md`.)
