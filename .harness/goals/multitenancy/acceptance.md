# Acceptance criteria

All `verify` commands assume repo root `/Users/saveliy/Documents/Amyris`. The
isolated auditor re-runs these from scratch; do not trust prior reports.

## M0 — Foundations
- [ ] Baseline suite is the floor.
  `cd lab && python3 -m pytest -q`  → ≥ 208 passed, 0 failed
- [ ] Single-user golden-path canary exists and passes.
  `cd lab && python3 -m pytest -q tests/test_regression_single_user.py`
- [ ] CI gate runs only network-free tiers and is green.
  `cd lab && python3 -m pytest -q -m "not convex_e2e and not live_channel"`

## M1 — Convex schema (additive) + claimNextForUser
- [ ] Additive schema pushes cleanly (no Schema validation failed) on dev.
  `cd control-plane && npx convex dev --once 2>&1 | grep -iE 'error|validation' || echo PUSH_CLEAN`
- [ ] Additive push does not lose operator data (done count non-decreasing).
  `cd control-plane && npx convex run messages:stats`  → done ≥ pre-migration value
- [ ] New indexes exist; claimNextForUser scopes by user via by_status_user and returns replyTarget.
  `grep -nE 'by_status_user|by_userId|by_channel_handle' control-plane/convex/schema.ts && grep -n 'by_status_user' control-plane/convex/messages.ts && grep -n 'replyTarget' control-plane/convex/messages.ts`
- [ ] claimNextForUser claims ONLY the target user's queued rows, leaves another user's.
  `RUN_CONVEX_E2E=1 python3 -m pytest -q lab/tests/test_messages_claim_by_user.py`
- [ ] Brain contract intact: claimNext/complete/fail/recentForUser/intents:* still callable with original args.
  `grep -rn 'claimNext\b\|"complete"\|"fail"\|recentForUser\|listPending\|resolveIntent' lab/skeleton/worker.py`
- [ ] No .filter() for a WHERE-able predicate in new/edited Convex modules.
  `! grep -nE '\.filter\(' control-plane/convex/fleet.ts control-plane/convex/quota.ts 2>/dev/null`

## M2 — Channel layer + worker de-hardcode (keystone)
- [ ] Worker replies to the CLAIMED message's own address, NOT cfg.reply_target.
  `cd lab && python3 -m pytest -q tests/test_worker_routing.py::test_replies_to_claimed_channel_not_config_target`
- [ ] cfg.reply_target is gone from the reply path (only the migration-fallback comment remains).
  `cd lab/skeleton && grep -n 'cfg.reply_target' worker.py | grep -v 'fallback\|deprecated'; test $? -ne 0`
- [ ] ChannelRegistry builds from config, get() raises for missing kind, both impls satisfy the Protocol.
  `cd lab && python3 -m pytest -q tests/test_channels.py`
- [ ] Outbound client is selected by the claimed channel (imessage→Sendblue, telegram→Telegram, null→Sendblue).
  `cd lab && python3 -m pytest -q tests/test_worker_routing.py::test_outbound_client_selected_by_channel`
- [ ] Full lab suite still green after the additive fixture edits (no regression).
  `cd lab && python3 -m pytest -q`

## M3 — Telegram channel
- [ ] Telegram client sends HTML, honors 429 retry_after, falls back to plain on 400, non-2xx returns ok=False without raising.
  `cd lab && python3 -m pytest -q tests/test_telegram_client.py`
- [ ] tg_format escapes & < >, renders bold/italic/inline+fenced code; split_html_safe never cuts a tag and keeps chunks <=4096.
  `cd lab && python3 -m pytest -q tests/test_tg_format.py`
- [ ] process_one routes a claimed channel='telegram' row to its replyTarget via TelegramChannel (NO Sendblue call); streaming disabled for telegram.
  `cd lab && python3 -m pytest -q tests/test_worker_telegram.py`
- [ ] Telegram webhook wired with header constant-time auth, never 5xx on payload; Convex push validates.
  `grep -n 'X-Telegram-Bot-Api-Secret-Token' control-plane/convex/http.ts && cd control-plane && npx convex dev --once 2>&1 | tail -5`
- [ ] LIVE: one Telegram round-trip renders bold/escaped (operator-run).
  `RUN_LIVE_CHANNEL=1 python3 lab/tests/e2e/run_two_user_e2e.py --channel telegram`

## M4 — Auth + landing + connect
- [ ] Web app builds and typechecks against the control-plane generated API.
  `cd web && npm install && npx tsc --noEmit && npm run build`
- [ ] Convex Auth env keys present on dev (no null-redirect at sign-in).
  `cd control-plane && npx convex env list | grep -E 'JWT_PRIVATE_KEY|JWKS|SITE_URL'`
- [ ] User-facing module is getAuthUserId-gated and separate from the worker-secret module.
  `grep -RIl 'getAuthUserId' control-plane/convex/app/ && ! grep -RIl 'workerSecret' control-plane/convex/app/`
- [ ] createPairingToken produces a Telegram-safe token (base64url, <=64 chars, [A-Za-z0-9_-]).
  (convex run app/channels:createPairingToken with a dev JWT; assert /^[A-Za-z0-9_-]{1,64}$/)
- [ ] Pairing tokens are single-use, expiring, channel-checked, and reject a cross-user external id.
  `cd lab && python3 -m pytest -q tests/test_pairing.py`
- [ ] Dashboard flips to 'connected' reactively on a binding with no client polling.
  `cd web && npx playwright test e2e/connect-telegram.spec.ts`
- [ ] Tenant isolation: a user-facing query never returns another user's channels/usage.
  `cd web && npx playwright test e2e/isolation.spec.ts`
- [ ] Protected routes require auth; unauthed /dashboard redirects to /signin.
  `cd web && npx playwright test e2e/auth-gate.spec.ts`
- [ ] Operator backfill complete: 0 operator messages missing userId; exactly one verified imessage binding.
  (Convex runOneoffQuery: messages userId==undefined && userNumber=='+79217818876' → 0; channelBindings by_address('imessage','+79217818876').verified → 1)
- [ ] Operator stays live throughout (live ping before/after webhook cutover).
  `bash lab/scripts/live_ping.sh`

## M5 — Tiers, quotas, billing-stub
- [ ] Tiers are data-driven with both channels on every tier.
  `grep -E 'free:|pro:|max:|msgQuota|imessage.*telegram' control-plane/convex/billing/tiers.ts`
- [ ] checkAndReserve is WORKER_SECRET-gated, atomically increments msgUsed, returns allowed=false reason=over_quota when used>=quota.
  `grep -nE 'checkAndReserve|assertWorker|msgUsed|over_quota|allowed: false' control-plane/convex/quota.ts`
- [ ] myUsage is getAuthUserId-gated, reads only the authed user's entitlement via by_user (no .filter, no id arg).
  `grep -nE 'getAuthUserId|withIndex.*by_user|myUsage' control-plane/convex/app/billing.ts && ! grep -n '\.filter(' control-plane/convex/app/billing.ts`
- [ ] BillingProvider + StubProvider exist; stub createCheckout returns a coming-soon URL, handleWebhook returns {ok:false}.
  `grep -nE 'interface BillingProvider|createCheckout|handleWebhook|portalUrl' control-plane/convex/billing/provider.ts && grep -nE 'StubProvider|COMING_SOON|ok: false' control-plane/convex/billing/stub.ts`
- [ ] applyEntitlement is the single entitlement-writing internalMutation reused by signup + admin + (future) webhook.
  `grep -nE 'applyEntitlement|internalMutation' control-plane/convex/billing/grant.ts && grep -rnE 'applyEntitlement' control-plane/convex/ | grep -vE 'grant.ts'`
- [ ] Worker quota integration: denied → upsell + complete + NO lane; allowed → reserve then lane + recordUsage; fail-open on Convex error; synthetic unmetered.
  `cd lab && python3 -m pytest -q tests/test_quota_client.py tests/test_worker_quota.py`
- [ ] Over-quota blocks the run end-to-end and sends a friendly limit message.
  `RUN_CONVEX_E2E=1 python3 -m pytest -q lab/tests/test_entitlement_quota.py::test_over_quota_blocks_run`
- [ ] Quota reset cron registered as an internalMutation and paginates (take + self-reschedule).
  `grep -nE 'rollExpiredPeriods|cronJobs|interval' control-plane/convex/crons.ts && grep -nE 'take\(500\)|scheduler.runAfter' control-plane/convex/billing/grant.ts`
- [ ] Full lab suite stays green after quota integration.
  `cd lab && python3 -m pytest -q`

## M6 — Fleet container + orchestrator
- [ ] Required GCP APIs enabled on the correct project.
  `gcloud services list --enabled --project=hermes-saved-content-lab --filter='config.name:(compute.googleapis.com OR secretmanager.googleapis.com)' --format='value(config.name)'`
- [ ] The fleet image builds and its in-image mocked pytest gate passes (no network).
  `docker build -f lab/docker/Dockerfile.fleet -t hermes-fleet:test .`
- [ ] claimNextForUser + fleet isolation pass (mocked Convex unit).
  `cd lab && python3 -m pytest -q tests/test_claim_next_for_user.py tests/test_fleet_isolation.py`
- [ ] Two scoped workers + fake controller boot via docker-compose, each claims only its own user, mock outbound records non-cross-contaminated replies.
  `cd fleet/local && docker compose up --abort-on-container-exit --exit-code-from seed && docker compose logs mock_outbound | grep -E 'alice->alice|bob->bob'`
- [ ] Controller reconcile-loop unit tests pass (launch/heartbeat/idle-reap/placement, docker+gcloud mocked).
  `cd fleet/controller && python3 -m pytest -q tests/`
- [ ] fleet.ts + claimNextForUser typecheck and deploy to dev without schema errors.
  `cd control-plane && npx convex dev --once && npx tsc --noEmit -p .`
- [ ] Every scoped Convex function uses an index (no .filter scans).
  `grep -n 'by_status_user' control-plane/convex/messages.ts && ! grep -n '\.filter(' control-plane/convex/fleet.ts`
- [ ] LIVE cutover: one real inbound → exactly one reply (no double-reply during dual-worker overlap).
  `RUN_LIVE_CHANNEL=1 python3 lab/tests/e2e/run_two_user_e2e.py --live-smoke`

## M7 — Big e2e + tighten
- [ ] Two-user no-cross-talk e2e on real dev Convex + two worker loops + fake channels (zero GCP).
  `RUN_CONVEX_E2E=1 python3 -m pytest -q lab/tests/test_e2e_fleet_isolation.py::test_no_cross_talk`
- [ ] Conversation-memory isolation: recentForUser(+A) excludes +B's turns.
  `RUN_CONVEX_E2E=1 python3 -m pytest -q lab/tests/test_e2e_fleet_isolation.py::test_history_isolation`
- [ ] Idempotent duplicate webhook → exactly one row / one reply.
  `RUN_CONVEX_E2E=1 python3 -m pytest -q lab/tests/test_e2e_fleet_isolation.py::test_duplicate_webhook_one_row`
- [ ] Cold-start: a message enqueued with no worker running drains once a worker starts.
  `RUN_CONVEX_E2E=1 python3 -m pytest -q lab/tests/test_e2e_fleet_isolation.py::test_cold_start_drains`
- [ ] After tighten, schema push proves zero rows missing userId/channel.
  `cd control-plane && npx convex deploy`  (succeeds; Convex rejects if any row invalid)
- [ ] Legacy global claimNext removed after no worker calls it.
  `grep -rn 'claimNext\b' control-plane lab`  → only claimNextForUser remains
- [ ] CI gate stays green (regression guard).
  `cd lab && python3 -m pytest -q -m "not convex_e2e and not live_channel"`
