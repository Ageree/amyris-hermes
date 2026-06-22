# Phase 1 (CATALOG) Audit — audit-1

Catalog under audit: `docs/feature-audit/features.json` (123 rows) → `docs/feature-audit/feature-status.csv`.
Areas: web (34), control-plane (45), assistant (30), fleet-controller (14). Re-verified from scratch, read-only.

## Check results

| check | status | evidence |
|-------|--------|----------|
| 1. JSON validity (loads, 123 rows) | PASS | `json.load` returns 123; area counts match exactly (web 34, control-plane 45, assistant 30, fleet-controller 14). |
| 1. Required fields non-empty on every row | PASS | Programmatic scan of all 123 rows × 7 required fields (id, area, feature, user_story, expected_behavior, source_refs, verify_method): `total_missing=0`. |
| 1. IDs unique | PASS | `Counter(ids)` shows no duplicates (`dup_ids=[]`). |
| 2. Source-ref accuracy (10 spot-checks, all 4 areas) | PASS | All 10 cited file:line ranges exist (within file bounds) and the code matches expected_behavior. See per-row table below. |
| 2. Cited line ranges in bounds | PASS | All spot-checked files large enough (worker.py 1364, messages.ts 475, fleet.ts 335, pairing.ts 225, identity.ts 34, middleware.ts 27, SignInCard.tsx 208, controller.py 612, crons.ts 50, rich.py 216, quota_client.py 104). |
| 3. Coverage — web components/pages | PASS | All 31 `web/**/*.tsx` files are referenced by feature (plus web/lib/* helpers). No meaningful component/page unrepresented. |
| 3. Coverage — convex public surface | PASS | Every public module referenced (admin, app/account|billing|channels|tiers|upgrade|usage|authGate, auth, billing/grant|stub|tiers|provider, fleet, intents, messages, migrations, pairing, quota, ResendOTP, http routes, lib/identity, lib/auth). |
| 3. Coverage — assistant skeleton | PASS | All user-facing behaviors referenced. Only 4 unreferenced files, all pure plumbing (asgi.py, config.py, convex_client.py, channels/__init__.py) — not distinct features. |
| 3. Coverage — fleet controller | PASS | All 7 controller modules referenced (controller, config, convex_admin, docker_driver, placement, secrets, state_sync) + service/run.sh/compose. |
| 4. verify_method hermetic (no real channel sends / no prod) | PASS | Methods use pytest, convex_e2e against dev deployment, Playwright on local dev with explicit "do not complete real login", or static reasoning. One regex hit (CP-05) was a false positive ("8 numeric" token-gate reasoning). No real iMessage/Telegram sends, no `--prod`. |

## 10 spot-checked rows

| row | area | file:line | verdict |
|-----|------|-----------|---------|
| WEB-12 (Google OAuth sign-in) | web | SignInCard.tsx:70-83,182-208 | PASS — handleGoogle calls `signIn("google",{redirectTo:"/dashboard"})`, catch re-enables + friendly error; secondary Button w/ inline GoogleIcon SVG, "redirecting…"/"continue with google", disabled while googlePending\|\|pwPending. Exact match. |
| WEB-33 (route gating middleware) | web | middleware.ts:11-27 | PASS — authed-on-/signin→/dashboard; unauthed-on-/dashboard(.*)\|/connect(.*)→/signin; JWT cookie auth; matcher excludes _next + static. Exact match. |
| CP-09 (resolveUserByAddress) | control-plane | lib/identity.ts:16-34 | PASS — internalQuery, `by_address.first()`, returns `{userId}` only if `binding && binding.verified`, else null; index-only (no .filter). Exact match. |
| CP-14 (claimNextAny skips fleeted) | control-plane | messages.ts:272-309 | PASS — assertWorker(secret); fleeted set via by_desired_status desired="running"; oldest SHARED_CLAIM_SCAN=50 by_status queued; claims first not owned by fleeted user; legacy userId-less always claimable; atomic patch→processing. Exact match. |
| CP-20 (redeem bind / hijack guard) | control-plane | pairing.ts:108-196 | PASS — shared `_redeem`: trim→no_address; lookup (by_token/by_code uppercased); not_found on missing/channel mismatch; consumed→idempotent re-greet for same owner else already_consumed; non-active/expired→expired; existing.userId≠row.userId→address_taken; else upsert verified binding + consume; impls exported for test seam. Exact match. |
| CP-30 (reapIdleInstances cron DISABLED) | control-plane | fleet.ts:308-335 + crons.ts:31-39 | PASS — reapIdleInstancesImpl scans by_status_heartbeat("running"), free-tier+desired="running"+idle>IDLE_TTL_FREE_MS → desired="stopped", self-reschedule on full batch, internalMutation wrapper present; crons.ts schedule commented out (operator 2026-06-17 always-on). Exact match. |
| CP-45 (cron schedule registry) | control-plane | crons.ts:10-50 | PASS — exactly 3 active `crons.interval` (rollExpiredPeriods 1h, reapStaleProcessing 2min, expireStaleTokens 30min); reapIdleInstances commented out. Exact match. |
| ASST-13 (rich-message directive parsing) | assistant | rich.py:179-216,83-97,100-154 | PASS — parse_rich: leading `[[react:…]]`→ReactionPart(s); ```poll fence→PollPart; md `![](url)` / bare image-ext URL→ImagePart; md links stay opaque text; merge→TextPart; no-directive→single TextPart. Exact match. |
| ASST-25 (quota gate M5) | assistant | worker.py:911-937,1021-1030 + quota_client.py:25-104 | PASS — metered iff quota_enabled && client && user_id && !synthetic; check_and_reserve BEFORE model call; clean deny→upsell + complete + send + NO lane + return; fail_open reserves nothing; _fail_open / is_synthetic(resume:/e2e) / record_usage / release_reserve all present. Exact match. |
| CTRL-01 (reconcile loop) | fleet-controller | controller.py:473-504 | PASS — reconcile_once: list_reconcile(), per-instance _decide()→launch/relaunch/stop, noop/skip do nothing, per-instance try/except records `{action:"error"}` so one bad row doesn't abort others, returns action-summary list. Exact match. |

## Missing features

None major. Four assistant infrastructure files are not referenced by any row, but none is a distinct user-facing feature (their behavior is covered transitively by referenced rows):

- `lab/skeleton/asgi.py` — uvicorn ASGI entrypoint (wraps app.py/config.py, both referenced). Minor.
- `lab/skeleton/config.py` — env-backed Config loader (fail-fast KeyError on missing env). Minor follow-up: could warrant one "fail-fast config" row.
- `lab/skeleton/convex_client.py` — thin HTTP query/mutation wrapper (used by referenced worker/quota rows). Minor.
- `lab/skeleton/channels/__init__.py` — package init / channel factory. Minor.

These are optional follow-up rows at most; the catalog does not miss any whole sub-surface.

AUDIT_VERDICT=PASS
