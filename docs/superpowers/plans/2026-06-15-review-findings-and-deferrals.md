# Independent multi-agent review of M5/M6/M7 — findings, fixes, deferrals

Date: 2026-06-15. Four independent-context audit agents reviewed the M5 (quotas/
billing), M6 (fleet), and M7 (e2e) work, each from scratch with its own lens and
real verification (no shared reasoning). Verdicts:

| Lens | Verdict | CRIT | HIGH | MED | LOW |
|---|---|---|---|---|---|
| Security / tenant isolation (A1–A4) | FIX_REQUIRED | 0 | 1 | 2 | 3 |
| Convex correctness | CONVEX_SOUND | 0 | 0 | 2 | 3 |
| Test integrity (re-ran everything) | FIX_REQUIRED (coverage) | 0 | 2 | 2 | 1 |
| Fleet runtime readiness | FIX_REQUIRED | 2 | 4 | 5 | 5 |

Isolation (A1/A2/A4) was confirmed sound and live-verified; no cross-tenant data
leak, no client-trusted userId, no secret baked into the image. The blockers were
runtime/wiring bugs masked by tests that exercised each side in isolation.

## Fixed in commit `1ae1d08` (all verified)
- **C1** controller→worker env-name mismatch (every container crashed on boot) +
  the regression contract test.
- **C2** cold-start unwired (`fleet:requestInstance` had no caller) → wired
  `requestInstanceInternal` into both webhooks; tier derived from entitlement.
- **HIGH** double-reply guard on `complete`/`fail` (status==="processing"); reap
  window 5m→15m.
- **HIGH** relaunch self-kill (controller `markStopped` before relaunch; fake fixed).
- **HIGH** crash-loop relaunch-storm guard (markError + stop after N).
- **HIGH** worker graceful SIGTERM/SIGINT drain + honor heartbeat desired==stopped.
- **Coverage** new live `test_e2e_fleet_lifecycle.py` (fleet.ts had zero live tests;
  the idle reaper had none) — request/reconcile/claim/heartbeat/setDesired/markStopped,
  at-most-once launch, idle-reap free-vs-paid, all against real dev.
- pairing supersede read bounded `take(200)`; testing cleanup reaps agentInstances;
  stale operator-cutover comment softened.

Verification after fixes: tsc 0 · convex_e2e 21/0 (live dev) · lab 307/0 ·
controller 69/0 · docker in-image gate 269/0 (hard).

## Deferred — infrastructure-dependent or operator-gated (NOT bugs blocking dev/local)
1. **Placement uses fabricated host metrics** (controller `_build_hosts_state`
   hardcodes capacity=50 / RAM=40%). The pure `placement.choose_host` refuse-when-
   full logic is correct + tested, but production will silently overcommit until a
   real per-host `/metrics` agent feeds true RAM/count. Needs the host-agent infra
   (not built). Until then: keep capacity conservative + log refusals.
2. **No periodic state mirror** — `state_sync` mirrors only on a clean `docker stop`,
   so a crash between stops loses state since the last clean stop. Add a timer-based
   background mirror before real multi-tenant load. (Rehydrate-on-launch already
   restores the last mirrored state; gcsfuse-on-live-profile is correctly avoided.)
3. **Per-instance secret machinery is half-built** (`WORKER_SECRET_REF` set but never
   consumed; `secrets.py` creates a value-less secret). v1 is single shared
   WORKER_SECRET — either wire the per-instance read or drop it; documented as v1.
4. **Test seams ship in the prod bundle**, gated only by `ALLOW_TEST_SEED`. The gate
   is correct (and `cleanupTenants` is further guarded to tt-*@test.invalid only),
   but prod safety rests on that env var being UNSET on `adept-dragon-928`. Operationally
   assert it's unset before/after every prod deploy; longer-term move testing.ts to a
   throwaway deployment.
5. **`rsync --delete-unmatched-destination-objects`** on the durable GCS side — a
   wrong exclude could prune durable state. Low risk (mirror only after clean stop);
   consider a versioned bucket + lifecycle instead.
6. **HERMES_HOME path mismatch** — controller uses `/data/tenants/<id>` (works, its
   env overrides the Dockerfile default `/hermes-home`), but the Dockerfile's
   `VOLUME /hermes-home` leaves a dangling anon volume per container, and compose
   exercises a different path than prod. Pick one canonical path.
7. **Containers run as root** (no `USER` in Dockerfile.fleet) — defense-in-depth gap.
8. **No concurrent last-unit quota race test** — `checkAndReserve` is atomic by Convex
   serializability (correct), but unguarded by a regression test.
9. **Idle-reap can stop a mid-task-but-quiet free user** — bounded by
   `reapStaleProcessing` re-queue; consider bumping `lastActiveAt` on `complete` too.

See also `2026-06-14-M7-tighten-and-cutover-DEFERRED.md` for the destructive
schema-tighten + `claimNext`/`ALLOWED_USER_NUMBER` removal, which remains
operator-gated (depends on the live operator's cutover to scoped mode).
