# Continuation — what shipped / what remains / blocked

## Turn 2 (autonomous in-worktree implementation A1–A8 + scripts + mirror timer)

All edits are in worktree `worktree-gcp-fleet` (base origin/main 049ada7).
NO live/paid GCP step taken — those are operator-gated (checkpoint below).

### Shipped & locally verified
- **Image (AC-1/AC-3):** `Dockerfile.fleet` — `HERMES_GIT_URL` arg defaults to the
  PUBLIC `Ageree/hermes-agent` fork (no `your-org`); non-root `USER hermes` (uid/gid
  10001) created after the in-image pytest gate; removed `VOLUME`; `HERMES_HOME`
  =/data/tenants/default; added `ENV PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=5` (the
  earlier full build flaked on a transient PyPI read-timeout — clone+chromium were
  fine).
- **cloudbuild.fleet.yaml:** push target `${_REGION}-docker.pkg.dev/$PROJECT_ID/
  ${_AR_REPO}/hermes-fleet` with `_AR_REPO=saved-content`, `_REGION=us-central1`.
- **provision-host.sh REWRITTEN** to the v1 single co-located VM model: enable APIs
  (compute/AR/cloudbuild/storage/logging/secretmanager); AR repo `saved-content`;
  GCS bucket `hermes-fleet-state` + object versioning; dedicated SA `hermes-fleet`
  with least-privilege IAM (artifactregistry.reader, logging.logWriter, bucket-scoped
  storage.objectAdmin; secretmanager.admin gated behind PER_INSTANCE_SECRETS); ONE
  e2-standard-2 debian-12 VM (8 GB — fits controller + 2 chromium tenants for the
  isolation proof) with the SA + startup-script. Dropped the 2nd VM + unattached disk.
- **vm-startup.sh NEW:** installs docker.io + gcloud (if absent); creates `hermes-fleet`
  uid 10001 in the docker group; /data/tenants chowned 10001 (== container USER, Bug
  C5); /opt/hermes-fleet + /etc/hermes-fleet dirs; configure-docker AR auth via VM SA.
- **C3 model endpoint:** `controller._build_env` derives base_url/model from the key
  prefix (`sk-or-`→OpenRouter `minimax/minimax-m3`, else native MiniMax); explicit env
  wins. (live system is OpenRouter.)
- **C5 bind-mount ownership:** `state_sync.rehydrate` makedirs the local bind-mount as
  the controller uid (10001) before docker run (controller is NoNewPrivileges, can't chown).
- **Deferred #2 GCS mirror timer:** `_mirror_running_tenants` + `MIRROR_INTERVAL_S`
  (default 300s) periodic best-effort mirror of running tenants in the run() loop;
  closes the crash-loss gap (was: mirror only on clean stop). 4 new tests.
- **Deferred #1 /metrics:** capacity is now `CAPACITY_PER_HOST` (config), .env.example=5.
  Real per-host /metrics is a multi-host concern — legitimately YAGNI for single-VM v1.
- **Deferred #3 per-instance secrets:** `PER_INSTANCE_SECRETS` flag (default OFF);
  Secret Manager path only runs when ON. v1 = shared WORKER_SECRET.
- **A6 docs:** controller `.env.example` (created) + README — correct env names
  (SENDBLUE_API_SECRET_KEY), OpenRouter, CONVEX_URL=.convex.cloud admin url, new knobs.
- **.dockerignore** (repo root) — keeps the build context small + secret-free.
- docker_driver: ponytail note on the `--env K=V` argv exposure (within the single-VM
  trust domain; --env-file upgrade path if hosts ever go multi-trust-domain).

### Green
- controller: **79 passed** (75 + 4 new mirror). lab: **313 passed** (21 deselected).
- Hermetic image build (INSTALL_HERMES=0) validated: uid=10001, VOLUMES=null,
  HERMES_HOME=/data/tenants/default, USER=hermes.
- provision-host.sh: bash -n OK; --dry-run prints the exact intended command set.

### Remains
- [in progress] full INSTALL_HERMES=1 build (clone OK, chromium OK, pip installing) →
  confirm AC-1 (Ageree fork) + AC-3 (chromium present, runs non-root).
- Commit worktree changes (reversible, no push).
- **OPERATOR CHECKPOINT (live/paid):** L1 enable Compute Engine; L2 `provision-host.sh
  --apply` (APIs, AR, bucket, SA, VM); L3 build+push image (cloudbuild); L4 deploy
  controller onto the VM (/opt + /etc/hermes-fleet/controller.env, systemd). Show exact
  commands, WAIT for approval before any live step.
- After checkpoint: live e2e V1–V6 (cold-start→serve→reap both channels; 2-tenant
  isolation; cutover no-loss/no-dup), independent audits, M7 tighten (operator-gated).

### Blocked
- Live GCP steps await operator approval at the checkpoint (Compute Engine API is the
  only hard gate not yet enabled; billing ON, other APIs enabled).
