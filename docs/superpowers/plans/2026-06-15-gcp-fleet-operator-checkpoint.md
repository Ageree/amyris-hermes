# GCP Fleet — Operator Checkpoint

Branch `worktree-gcp-fleet` @ `845080a` (local, **NOT pushed**). Updated 2026-06-16
after the full live verification run. Everything below the line is DONE & proven;
the **Remaining gates** section is what still needs your call (live/paid/irreversible).

Account: `solsav1703@gmail.com` (has access to `hermes-saved-content-lab`). Billing ON.
Live dev Convex: `zany-tapir-501`. Real GCE host: `hermes-fleet-host` (e2-standard-2,
us-central1-a, 35.255.156.171). Image: `…/saved-content/hermes-fleet:3bebfe3`.

---

## DONE & verified live (real GCP, not mocks)

- **L1 provision** — VM + GCS bucket `hermes-fleet-state` + SA `hermes-fleet`
  (least-priv IAM) + vm-startup (docker, uid 10001, /data/tenants, AR auth). Live.
- **L2 image** — Cloud Build `_INSTALL_HERMES=1`, in-image pytest gate + chromium ran.
  `hermes-fleet:3bebfe3` (+`:latest`) in AR.
- **L3 controller** — systemd `hermes-controller` active on the VM (stdlib-only,
  `/usr/bin/python3`), config via EnvironmentFile.
- **V1 cold-start→serve→reap** — `requestInstance`→real container ~5s, heartbeat
  advancing; iMessage served (fast lane 2.14s) + **real reply delivered to your iPhone**;
  Telegram channel routing proven (hit Telegram API; real chat delivery needs your
  `/start @e1isabot`); idle-reap → graceful SIGTERM drain → `Exited(0)` → GCS mirror.
- **V2 isolation** — two tenants concurrent; cross-leak check 0/6 (each container only
  its own msg/replyTarget; full Hermes lane also works in-container).
- **V3 cutover** — 9 msgs straddling a flip; container took all 9, shared worker only the
  pre-flip rows; intersection ∅ (no dup), all done (no loss), clean handoff.
- **3 independent audits** (isolation / runtime-readiness / producer↔consumer) — 0
  critical/high. Keystone (`claimNextAny` skips fleeted users) sound; cold-start wired;
  no zombie-running gap.
- **Fixes committed `845080a`**: GCS-mirror exclude regex (was crashing every mirror),
  SOUL.md baked into image (was voiceless), deploy-controller restart (was no-op redeploy).
- **State clean**: `listReconcile`=0, test tenants purged, `ALLOW_TEST_SEED` UNSET on dev,
  VM has 0 containers. Shared worker still serves all real users (fleet not yet cut over).

---

## Remaining gates (your call — live/paid/irreversible)

### G1 — Rebuild+push image so the SOUL.md fix lands (Cloud Build = docker-push gate)
The live image `:3bebfe3` predates the SOUL fix, so fleet replies are currently
voiceless. Rebuild from `845080a`:
```bash
cd /Users/saveliy/Documents/Amyris/.claude/worktrees/gcp-fleet
gcloud builds submit --config lab/docker/cloudbuild.fleet.yaml \
    --substitutions SHORT_SHA=$(git rev-parse --short HEAD) \
    --project hermes-saved-content-lab .          # ~3 min
# then point the controller at the new tag + restart:
bash scripts/fleet/deploy-controller.sh \
    --env-file <controller.env with IMAGE=…:845080a> --apply
```

### G2 — Real-user cutover (flip your own user to the fleet)
The `claimNextAny` skip already makes shared+fleet coexist safely (proven in V3). To cut
your real user over: `fleet:requestInstance {workerSecret, userId=<your user>}` (or send
an inbound — the webhooks call `requestInstanceInternal` automatically). The shared
worker then yields you; your container serves you. Roll back by `setDesired stopped`.
Retire/repurpose the shared `com.savedcontent.worker` (launchd) once all users are fleeted.

### G3 — M7 destructive tighten (depends on cutover; separately gated).

### G4 — Push/merge `worktree-gcp-fleet` → main (your decision; nothing pushed yet).

### Low-priority hardening (optional, deferred)
- Controller `_require()` the 5 worker secrets at startup (fail-fast vs the current
  empty-string injection).
- Fold webhook `enqueue`+`requestInstanceInternal` into one txn (cold-start cutover purity).
- Per-instance secrets (machinery exists, gated OFF) + per-host RAM `/metrics` — only
  needed beyond a single VM.
