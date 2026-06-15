# Acceptance criteria — GCP per-user container fleet

Verified by an isolated auditor re-running each command from scratch. Substitute
`PROJECT_ID=hermes-saved-content-lab`, account `solsav1703@gmail.com`, dev Convex
`zany-tapir-501`. Full design: `design-workflow-raw.txt` + the design doc.

## A. Image / code (NON-LIVE — autonomous, local & free)

| ID | Criterion | Verification |
|----|-----------|-------------|
| AC-1 | Image builds WITH Hermes from the Ageree fork | `docker build -f lab/docker/Dockerfile.fleet --build-arg INSTALL_HERMES=1 --build-arg HERMES_GIT_URL=https://github.com/Ageree/hermes-agent.git -t hermes-fleet:localtest .` → exit 0 |
| AC-2 | Worker runs non-root | `docker run --rm --entrypoint id hermes-fleet:localtest` → `uid=10001(hermes)` |
| AC-3 | Chromium usable non-root (INSTALL_HERMES=1) | `docker run --rm --entrypoint /opt/hermes-agent/venv/bin/python hermes-fleet:localtest -c "import shutil,sys;sys.exit(0 if shutil.which('chromium') else 1)"` → exit 0 |
| AC-4 | No dangling `/hermes-home`; default `HERMES_HOME=/data/tenants/default` | `docker inspect hermes-fleet:localtest --format '{{json .Config.Volumes}} {{json .Config.Env}}'` — no `/hermes-home` VOLUME; env shows the new default |
| AC-5 | No empty Secret Manager secrets created (v1 flag off) | after controller `--once`: `gcloud secrets list --project=$PROJECT_ID --filter='name:hermes-worker'` → empty |
| AC-6 | C1 env contract holds (seam test) | `cd fleet/controller && python3 -m pytest tests -q -k BuildEnvBootsWorker` → pass |
| AC-6b | C3 model-endpoint contract (seam test) | new test: `_build_env` resolves `MINIMAX_BASE_URL` to the OpenRouter host when key is `sk-or-*` → pass |
| AC-7 | Full suite green (no regression vs baseline 69+313) | `python3 -m pytest -q fleet/controller/tests` (69) AND `cd lab && PYTHONPATH=skeleton python3 -m pytest -q tests -m "not convex_e2e and not live_channel"` (≥313) → 0 failures |
| AC-8 | Hermetic in-image gate still green | `docker build -f lab/docker/Dockerfile.fleet --build-arg INSTALL_HERMES=0 -t hermes-fleet:gate .` → exit 0 (runs the pytest RUN-step) |

## B. Live GCP (OPERATOR-CHECKPOINTED before each)

| ID | Criterion | Verification |
|----|-----------|-------------|
| AC-9 | AR push lands in `saved-content` | `gcloud artifacts docker images list us-central1-docker.pkg.dev/$PROJECT_ID/saved-content/hermes-fleet --include-tags` lists `:<SHA>` + `:latest` |
| AC-10 | Controller live on the VM, reconciling | on VM: `systemctl is-active hermes-controller` → `active`; `journalctl -u hermes-controller` shows reconcile ticks |
| AC-11 | Cold-start → running (iMessage), real tenant | send inbound; `fleet:listReconcile` shows tenant `status=running`; `docker ps` shows `hermes-<userId>` |
| AC-12 | Serve, iMessage reply, no KeyError | tenant gets exactly one reply; `messages` row `status=done`; container logs have no `KeyError` |
| AC-13 | Serve, Telegram reply | inbound via `@e1isabot`; reply to `chat.id`; `messages.channel=telegram` |
| AC-14 | Two-tenant isolation, no cross-leak | V3: A↔A, B↔B replies only; `recentForUser(A)` excludes B; A's container claims only A's rows |
| AC-15 | Cutover no-loss / no-dup | V4: `done+error == N`, one outbound per inbound, owning worker wins, crash→requeue→exactly-once |
| AC-16 | Idle-reap + GCS mirror | V5: container gone after reap; `gcloud storage ls gs://hermes-fleet-state/tenants/<userId>/` non-empty; row `status=stopped` |
| AC-17 | Warm-restart durability | next inbound logs `rehydrate … ok` bytes>0; agent resumes prior state |
| AC-18 | `claimNextAny` retired (post-cutover) | `grep -n 'export const claimNextAny' control-plane/convex/messages.ts` → no match |
| AC-19 | Operator zero-downtime cut | `bash lab/scripts/live_ping.sh` → `LIVE_PING_OK` before AND after; Mac launchd daemon confirmed stopped |
| AC-20 | M7 tighten pushes clean on DEV | backfill audit missing-userId==0, then `cd control-plane && npx convex dev --once` → no schema rejection |

## Independent audits (separate context, as in SESSION 8)
- **Isolation**: no cross-tenant data/login/reply leak (A↔A, B↔B).
- **Runtime-readiness**: every container boots without KeyError; env contract live.
- **Producer↔consumer contract**: C1 (env names), C2 (cold-start wired), C3 (model
  endpoint), C4 (admin vs webhook URL), C5 (uid vs host dir owner) each pinned by a
  seam test that drives the consumer with the producer's real artifact.
