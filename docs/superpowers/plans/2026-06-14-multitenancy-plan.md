# Hermes Fleet — Multi-Tenancy Implementation Plan (2026-06-14)

> Phased, TDD, each phase ends in working software and is independently testable.
> Design spec: `docs/superpowers/specs/2026-06-14-multitenancy-design.md`.
> Ordering principle: the most VALUABLE, lowest-risk slice first. De-hardcoding
> the worker to route by the message's OWN user/channel is the keystone — it's
> the documented critical bug and unblocks every other phase, so it lands first
> behind an additive schema.

## Conventions for every phase

- **TDD:** write the test (RED) → minimal impl (GREEN) → refactor. Keep the lab
  suite (currently ≥208 green) as a non-decreasing floor at every phase boundary.
- **Additive-then-tighten** for all Convex schema changes (new columns
  `v.optional`; tighten only after backfill verified). Never break the live
  brain contract (`messages:*`/`intents:*` WORKER_SECRET functions).
- **Index discipline:** every read path gets a named compound index; no
  `.filter()` for a WHERE-able predicate; object-form functions with arg+return
  validators.
- **Many small files** (200-400 lines, 800 max). Comprehensive error handling +
  input validation at every boundary; no hardcoded secrets.
- **Operator stays live (user #0):** the Mac launchd worker is untouched until
  M6's cutover. Run a live ping (`send a known message → assert one reply`) before
  and after each risky step.

---

## M0 — Foundations & test scaffolding (no behavior change)

**Goal:** safety nets in place so every later phase is verifiable and the operator
is protected. No user-visible change.

**Files:**
- `lab/tests/conftest.py` (NEW) — skip markers (`requires_convex`,
  `requires_live_channel`), fixtures: `fake_channel`, `dev_convex`, `seed_user`,
  `seed_message`, `two_workers`.
- `lab/pytest.ini` (EDIT) — register markers `unit, convex_e2e, live_channel`.
- `lab/tests/test_regression_single_user.py` (NEW) — freeze the operator golden
  path (inbound → claim → hermes → reply to operator number → complete).
- `lab/scripts/check_regression.sh`, `lab/scripts/live_ping.sh` (NEW).

**Tasks:** introduce the gating convention; freeze the canary; tag
`pre-multitenant-baseline`.

**Tests:** the canary + `pytest -m "not convex_e2e and not live_channel"` green.

**Exit:** `cd lab && python3 -m pytest -q` ≥ 208 passed; canary passes; CI gate
script exits 0.

---

## M1 — Convex multi-tenant schema (additive) + claimNextForUser

**Goal:** the data layer can represent tenants, channels, pairing, entitlements,
usage, and the fleet — WITHOUT breaking the operator. All new columns optional;
all new tables empty.

**Files:**
- `control-plane/convex/schema.ts` (EDIT) — full target schema (design §2):
  `...authTables`, overridden `users`, `channelBindings`, `pairingTokens`,
  evolved `messages` (+`userId`/`channel`/`replyTarget` optional, +
  `by_channel_handle`/`by_status_user`/`by_userId` indexes), evolved
  `connectIntents`, `entitlements`, `usageEvents`, `billingEvents`,
  `agentInstances`.
- `control-plane/convex/messages.ts` (EDIT) — `enqueue` gains optional
  `userId/channel/replyTarget`, idempotent on `(channel,handle)`; **add
  `claimNextForUser({workerSecret,userId})`** via `by_status_user`; `claimNext`
  returns `replyTarget`+`channel` (kept); `recentForUser` supports `userId`;
  `stats` switched off `.collect()`.
- `control-plane/convex/lib/identity.ts` (NEW) — `resolveUserByAddress`.
- `control-plane/convex/lib/auth.ts` (NEW) — shared `assertWorker` + validators.

**Tasks:** push additive schema; add the new function; add return validators.

**Tests:** `test_messages_claim_by_user.py` (CONVEX-INTEGRATION):
`claimNextForUser(A)` returns only A's queued rows, leaves B's; atomic claim →
`processing`; `recentForUser(A)` excludes B. Grep proves `withIndex("by_status_user")`.

**Exit:** additive push succeeds with no `Schema validation failed`;
`messages:stats` counts unchanged (operator data intact); the legacy launchd
worker still drains via `claimNext`; `npx tsc --noEmit -p control-plane` clean.

---

## M2 — Channel layer + worker de-hardcode (THE keystone)

**Goal:** the worker replies to the CLAIMED message's own `replyTarget`/`channel`,
never `cfg.reply_target` — fixing the documented critical single-user bug — behind
a channel-agnostic abstraction. Still iMessage-only in practice, but the seam is
multi-tenant and multi-channel ready. Highest value, lowest risk (no new infra).

**Files:**
- `lab/skeleton/channels/{__init__,base,registry,sendblue_channel}.py` (NEW) —
  `Channel` Protocol, `OutboundResult`, `InboundMessage`, `ChannelRegistry`,
  `SendblueChannel` wrapping the existing `SendblueClient`.
- `lab/skeleton/worker.py` (EDIT) — `process_one`: select channel + reply_target
  from the claimed row; `_BubbleEmitter`/`_make_typing` route through a `Channel`;
  `_ChannelTypingShim`; `_fetch_history` keys on `userId`; `process_one` accepts a
  `ChannelRegistry` OR a single client (back-compat); `WorkerConfig` adds
  `worker_mode`/`user_id`/`telegram_bot_token` (deprecate `reply_target` for
  routing, keep as fallback).
- `lab/tests/test_worker.py` etc. (EDIT) — additive `_claim()` fixtures gain
  `channel/replyTarget`; UPDATE the "replies to config target" test to "replies to
  the claimed message's own address".

**Tasks:** build the abstraction; route the emitter/typing/history; keep all
existing tests green with minimal fixture edits.

**Tests:** `test_channels.py` (registry, Protocol conformance);
`test_worker_routing.py` (replies to claimed channel not config target; outbound
client selected by `channel`; per-user `HERMES_HOME`).

**Exit:** `grep 'cfg.reply_target' worker.py` shows only the fallback/deprecated
comment in the reply path; full lab suite green; the live operator path still
works (live ping).

---

## M3 — Telegram channel (Bot API 10.1)

**Goal:** a second channel, end-to-end: inbound webhook → enqueue → worker → HTML
reply. Both channels now selectable.

**Files:**
- `lab/skeleton/telegram_client.py` (NEW) — `send_message` (HTML, 429
  retry_after, 400→plain retry), `send_chat_action`, `parse_inbound`.
- `lab/skeleton/tg_format.py` (NEW) — `render_html`, `split_html_safe`.
- `lab/skeleton/channels/telegram_channel.py`, `channels/pairing_parse.py` (NEW).
- `control-plane/convex/http.ts` (EDIT) — append `/telegram/inbound`
  (header constant-time auth, validate, `/start <token>` branch, idempotent
  `tg:<update_id>` enqueue, never 5xx); swap Sendblue allowlist for
  `resolveUserByAddress` (keep `ALLOWED_USER_NUMBER` fallback).
- `lab/skeleton/worker.py` (EDIT) — `_use_streaming(cfg, channel_kind)` disables
  streaming for telegram; registry builds Telegram when token present.

**Tasks:** outbound client + formatter; the webhook route; streaming gate.

**Tests:** `test_telegram_client.py` (HTML escape, 4096 split never cuts a tag,
429 retry, 400 plain fallback, chat_action); `test_tg_format.py`;
`test_worker_telegram.py` (claimed `telegram` row → TelegramChannel, no Sendblue
call, sendChatAction typing, streaming off).

**Exit:** new tests green; Convex push validates the new route; one LIVE Telegram
round-trip renders bold/escaped (operator-run, `RUN_LIVE_CHANNEL=1`).

---

## M4 — Auth + landing + connect flow (free path fully live)

**Goal:** a real signup → pick tier → press button → deep-link into iMessage OR
Telegram → bound tenant. Free tier 100% live (no payment).

**Files:**
- `control-plane/convex/{auth.ts,auth.config.ts,ResendOTP.ts}` (NEW);
  `http.ts` (EDIT — `auth.addHttpRoutes(http)`).
- `control-plane/convex/pairing.ts` (NEW) — `mintToken`, `redeemTelegram`,
  `redeemImessage` (idempotent, single-use, reject cross-user external id,
  enqueue `__welcome__`).
- `control-plane/convex/app/{account,channels,usage,tiers,upgrade}.ts` (NEW) —
  getAuthUserId-gated; `createPairingToken`, `myChannels`, `disconnectChannel`,
  `currentUser`, `myUsage`, `chooseTier`.
- `control-plane/convex/migrations.ts` (NEW) — `backfillOperator`,
  `countMessagesMissingUserId`.
- `web/` (NEW app) — Next.js 15 + Convex Auth: `layout/providers/middleware`,
  `app/{page,signin,dashboard,connect}`, components
  (`marketing/*`, `auth/*`, `dashboard/*`, `connect/*`), `lib/{deeplinks,tiers}`,
  `@cp/api` path alias.

**Tasks:** install + key-set Convex Auth (§9, no TTY); the pairing primitive; the
user-facing module; the Next.js app with the reactive connect wizard; backfill the
operator as user #0 + switch webhook resolution to `channelBindings`.

**Tests:** `test_pairing.py` (single-use/expiry/wrong-channel/cross-user reject);
`web/e2e/*.spec.ts` (auth-gate redirect, landing renders 3 tiers, connect-telegram
flips reactively on a simulated bind, isolation: user A's myChannels excludes B).

**Exit:** `cd web && npx tsc --noEmit && npm run build` clean; auth env keys
present on dev; a real Google/OTP signup creates a `users` + free `entitlements`
row; a Telegram deep-link tap binds + the dashboard flips to "connected";
operator backfill leaves `countMessagesMissingUserId == 0`; operator stays live.

---

## M5 — Tiers, quotas, metering, billing-stub

**Goal:** entitlements enforced; over-quota → friendly upsell with zero model
spend; free fully live; paid behind a clean adapter (stub now). Dashboard shows
live usage.

**Files:**
- `control-plane/convex/billing/{tiers,provider,stub,registry,grant,events}.ts`
  (NEW) — TIERS const, `BillingProvider` + `StubProvider`, `activeProvider`,
  `applyEntitlement` (the single entitlement writer) + `rollExpiredPeriods` +
  `pruneOldUsage`.
- `control-plane/convex/quota.ts` (NEW) — `checkAndReserve`, `recordUsage`,
  `releaseReserve`.
- `control-plane/convex/app/billing.ts` (NEW) — `myUsage`, `myUsageTimeline`.
- `control-plane/convex/admin.ts` (NEW) — `grantTier` (WORKER_SECRET, manual paid).
- `control-plane/convex/crons.ts` (NEW) — period roll + usage prune (+ later
  reapers share this file).
- `lab/skeleton/quota_client.py` (NEW); `worker.py` (EDIT — call check_and_reserve
  after claim, skip synthetic, upsell on deny, recordUsage on success,
  releaseReserve on hard fail); `config.py`/`WorkerConfig` (+`upsell_url`).
- Auth callback (EDIT) — write free entitlement at signup.

**Tasks:** data-driven tiers; atomic reserve; fail-open/closed semantics; the
adapter seam; the dashboard query; the reset cron.

**Tests:** `test_quota_client.py` (allowed/denied/fail-open/synthetic-skip + upsell
text); `test_worker_quota.py` (denied → upsell + complete, no lane; allowed →
reserve then lane + recordUsage); `test_entitlement_quota.py` (CONVEX-INTEGRATION:
over-quota blocks run, free-vs-paid gating, stub-upgrade unblocks, usage
increments).

**Exit:** a signed-up user gets a free entitlement and `checkAndReserve` allows up
to `msgQuota` then upsells; `myUsage` (getAuthUserId, by_user index, no `.filter`)
shows used/quota; `chooseTier("pro")` returns `checkoutUrl=null`; full lab suite
green; cron registered + paginated.

---

## M6 — Fleet container + orchestrator (GCP) + operator cutover

**Goal:** per-user containers, launched/stopped/health-checked/idle-reaped by a
controller reconciling Convex desired-state. The operator migrates LAST, atomically,
zero downtime.

**Files:**
- `lab/docker/Dockerfile.fleet`, `lab/docker/cloudbuild.fleet.yaml` (NEW).
- `control-plane/convex/fleet.ts` (NEW) — `requestInstance`,
  `claimInstanceForLaunch`, `heartbeat`, `markStopped`, `markError`,
  `listReconcile`, `setDesired`.
- `control-plane/convex/crons.ts` (EDIT) — `reapStaleProcessing`,
  `reapIdleInstances`, `expireStaleTokens`.
- `fleet/controller/{controller,docker_driver,placement,state_sync,secrets,convex_admin,config}.py`
  + `run.sh` + systemd unit (NEW).
- `fleet/local/{docker-compose.yml,mock_outbound.py,fake_controller.py,seed.py}`
  (NEW) — local-dev harness (2 scoped workers, fake controller, real dev Convex).
- `lab/skeleton/worker.py` (EDIT) — scoped mode: `claimNextForUser(USER_ID)`,
  heartbeat each loop; `from_env` reads `WORKER_MODE/USER_ID/INSTANCE_ID`.
- `scripts/fleet/provision-host.sh` (NEW) — enable APIs (correct project!),
  create host+controller VMs, GCS bucket, PD, install Docker.

**Tasks:** enable `compute`+`secretmanager` on `hermes-saved-content-lab`; build
the image (in-image mocked pytest gate); the desired-state functions; the
reconcile-loop controller; per-instance Secret-Manager secrets; the local harness;
then the operator cutover (parallel old+new worker, atomic claim, stop the Mac
daemon).

**Tests:** `test_fleet_isolation.py`, `test_claim_next_for_user.py` (mocked);
`fleet/controller/tests/{test_controller,test_placement,test_state_sync}.py`;
local docker-compose smoke (2 workers, mock outbound records correctly-routed,
non-cross-contaminated replies); fleet.ts typecheck + deploy.

**Exit:** image builds + in-image pytest passes; two scoped workers + fake
controller boot and route correctly (zero GCP); controller unit tests pass; APIs
enabled on the right project; the operator runs on a scoped container with the Mac
daemon stopped, exactly one reply per inbound (live cutover smoke).

---

## M7 — Big e2e suite + tighten + hardening

**Goal:** the full ~70-scenario matrix green; schema tightened; legacy removed;
per-tenant isolation proven end-to-end.

**Files:**
- `lab/tests/test_e2e_fleet_isolation.py` + `lab/tests/e2e/{run_two_user_e2e.py,
  seed_dev_convex.py,cleanup_dev_convex.py}` (NEW).
- `control-plane/convex/schema.ts` (EDIT) — tighten `messages.userId/channel/
  replyTarget` + `connectIntents.userId` to REQUIRED; remove `claimNext`; remove
  `ALLOWED_USER_NUMBER` fallback in `http.ts`.

**Tasks:** the isolation/quota/pairing/idempotency/cold-start/reaper e2e scenarios
(LOCAL on dev Convex + fakes; ~6 LIVE operator-run); then the final tighten.

**Tests (the matrix):** no-cross-talk, reply-to-own-channel, history-isolation,
HERMES_HOME-isolation, secret-cannot-cross-tenant, telegram/imessage round-trip,
HTML escape/split/429, pairing single-use/expiry/payload, unknown-sender-dropped,
quota-blocks-run/tier-gating/stub-upgrade/usage-increment, idempotent-duplicate,
cold-start-drains, no-double-claim, stale-processing-reaper.

**Exit:** `npx convex deploy` succeeds (proves 0 invalid rows after tighten);
`grep 'claimNext\b'` shows only `claimNextForUser`; CI gate green; the LIVE
provider webhook dispatch leg verified; the full matrix green.

---

## Phase dependency graph

```
M0 ──▶ M1 ──▶ M2 (keystone) ──▶ M3 ──▶ M4 ──▶ M5 ──▶ M6 ──▶ M7
                  │                        │
                  └── M2 alone fixes the live multi-tenant reply bug and is
                      independently shippable (operator benefits immediately).
```

M2 is the highest-value, lowest-risk slice and is shippable on its own. M3-M5 are
largely parallelizable once M1's schema and M2's channel seam exist. M6 (GCP) is
the heaviest and depends on M2's scoped worker + M5's tier field. M7 closes the
loop and tightens.
