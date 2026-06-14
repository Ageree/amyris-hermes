# Hermes Fleet — Multi-Tenancy Design (2026-06-14)

> Authoritative spec for turning the LIVE single-user assistant into a real
> multi-tenant product: landing → signup/login → pick tier (free + paid) → press
> a button → deep-link into iMessage OR Telegram → a per-user isolated assistant
> that just works. This document is the single source of truth; the phased build
> plan lives in `docs/superpowers/plans/2026-06-14-multitenancy-plan.md`.

## 0. Locked operator decisions (design to THESE)

1. **Execution = per-user container fleet on GCP.** One Hermes container per
   user. Real orchestration: launch/stop/health/cold-start/bin-pack.
2. **Billing = stubbed.** Free tier fully live; paid tiers behind a clean
   provider-adapter interface; real payment wired later. No payment account yet.
3. **Channels = BOTH iMessage (Sendblue) AND Telegram on ALL tiers**; user picks
   at connect time.
4. **Auth = Convex Auth** (built-in) on the landing.
5. **Telegram = NEW channel**; Bot API 10.1 (2026-06-11) rich formatting.

Hard constraint threaded throughout: **the operator (`+79217818876`) is user #0
and must keep answering with zero downtime** while the system evolves. Every
schema change is additive-then-tighten; the operator's Mac launchd worker is
untouched until the very last cutover.

---

## 1. Architecture

```
                              ┌──────────────────────────────────────────────────────┐
                              │                  LANDING (web/, Next.js 15)            │
   user's browser  ───────────▶  marketing → Convex Auth (Google + email-OTP)         │
                              │  → pick tier → press Connect → choose channel          │
                              │  → show pairing (Telegram deep-link/QR | iMessage code)│
                              │  → dashboard (live tier + usage + connections)         │
                              └───────────────┬──────────────────────────────────────┘
                                              │ getAuthUserId-gated app/* functions
                                              │ (reactive useQuery — connected flips live)
                                              ▼
 ┌─────────────────────────── CONVEX CONTROL PLANE (zany-tapir-501 dev / adept-dragon-928 prod) ───┐
 │  USER-FACING  (getAuthUserId gate)      │   WORKER-FACING  (WORKER_SECRET arg gate)              │
 │  app/account, app/channels, app/usage,  │   messages (enqueue/claimNext/claimNextForUser/        │
 │  app/tiers, app/upgrade                 │   complete/fail/recentForUser), intents, fleet,        │
 │                                         │   quota (checkAndReserve/recordUsage/release),         │
 │  TABLES (one schema, indexed, validated):                                                        │
 │   users · channelBindings · pairingTokens · messages · connectIntents ·                          │
 │   entitlements · usageEvents · billingEvents · agentInstances                                    │
 │                                                                                                  │
 │  HTTP routes (http.ts):                                                                          │
 │   POST /sendblue/inbound/<WEBHOOK_SECRET>   (constant-time path token)                           │
 │   POST /telegram/inbound  (X-Telegram-Bot-Api-Secret-Token header)                               │
 │   auth.addHttpRoutes(http)  (OIDC/JWKS/OAuth callbacks)                                          │
 │   POST /billing/<provider>  (LATER, when a real provider is wired)                               │
 │                                                                                                  │
 │  crons.ts: reapStaleProcessing · reapIdleInstances · rollExpiredPeriods · expireStaleTokens     │
 └──────────────┬───────────────────────────────────────────────┬───────────────────────────────┘
        inbound │ webhooks resolve (channel,address)→userId        │ desired-state (agentInstances)
                │ enqueue {userId, channel, replyTarget}            │
                ▼                                                   ▼
        ┌───────────────┐                                  ┌──────────────────────────────┐
 Sendblue / Telegram     │                                  │  CONTROLLER VM (e2-small)     │
 (one shared number /    │                                  │  reconcile loop: launch/stop/ │
  one shared bot)        │                                  │  health/idle-reap/bin-pack    │
        ▲                │                                  │  docker + gcloud + Secret Mgr  │
        │ reply to       │                                  └───────────────┬──────────────┘
        │ replyTarget    │                                                  │ docker run / stop
        │                ▼ poll claimNextForUser(userId)                    ▼
 ┌──────┴───────────────────────────────────────────────────────────────────────────────┐
 │  HOST VM(s)  (e2-standard-8, Docker)        balanced PD: /data/tenants/<userId>         │
 │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐                       │
 │  │ container userA  │  │ container userB  │  │ container userC  │   ... bin-packed       │
 │  │ worker.py SCOPED │  │ worker.py SCOPED │  │ worker.py SCOPED │                       │
 │  │ USER_ID=A        │  │ USER_ID=B        │  │ USER_ID=C        │                       │
 │  │ HERMES_HOME=…/A  │  │ HERMES_HOME=…/B  │  │ HERMES_HOME=…/C  │   (browser+M3+exa)     │
 │  └──────────────────┘  └──────────────────┘  └──────────────────┘                       │
 │       │ mirror on stop + timer                                                          │
 └───────┼────────────────────────────────────────────────────────────────────────────────┘
         ▼
   gs://hermes-fleet-state/<userId>/   (durable HERMES_HOME backup; rehydrate on cold-start)

   user #0 (operator) stays on the Mac launchd worker in LEGACY mode (messages:claimNext,
   reply to ALLOWED_USER_NUMBER) until the very last cutover — see §10 migration.
```

**The four invariants the whole design protects:**

- **A1 — tenant key is `Id<"users">`.** Every owned row carries `userId`; every
  read path is an index keyed on it. The raw phone / Telegram chat-id is only an
  *address*, never a join key.
- **A2 — reply by the message's OWN address.** The worker replies to the claimed
  message's `replyTarget`/`channel`, NEVER a global constant. (Kills the
  documented single-user `cfg.reply_target = ALLOWED_USER_NUMBER` bug.)
- **A3 — durable queue, never lost.** Inbound is enqueued before any container
  exists; cold-start is latency, never message loss (the worker is outbound-only,
  no inbound port).
- **A4 — two gate modules, never mixed.** Browser callers use `getAuthUserId`;
  the brain uses the `WORKER_SECRET` argument. No function uses both gates.

---

## 2. Convex schema (final target)

All tables in `control-plane/convex/schema.ts`. Object-form, arg/return
validators on every function, a named compound index on every read path, **never
`.filter()` for a WHERE-able predicate**. Migration adds new columns as
`v.optional(...)` then tightens (see §10).

```ts
import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";
import { authTables } from "@convex-dev/auth/server";

// Reusable literal unions — single source so validators never drift.
const channel = v.union(v.literal("imessage"), v.literal("telegram"));
const tier = v.union(v.literal("free"), v.literal("pro"), v.literal("max"));

export default defineSchema({
  // ----- Convex Auth system tables (users/authSessions/authAccounts/...) -----
  ...authTables,

  // users overridden to add app fields. Convex Auth writes base fields; the
  // createOrUpdateUser callback sets tier/isOperator/createdAt at signup.
  users: defineTable({
    email: v.optional(v.string()),
    name: v.optional(v.string()),
    image: v.optional(v.string()),
    emailVerificationTime: v.optional(v.number()),
    phone: v.optional(v.string()),
    phoneVerificationTime: v.optional(v.number()),
    isAnonymous: v.optional(v.boolean()),
    // ---- app-specific ----
    displayName: v.optional(v.string()),
    tier: v.optional(tier),          // denormalized mirror of entitlements.tier (fast read)
    isOperator: v.optional(v.boolean()), // user #0 — never reaped, unlimited quota
    createdAt: v.optional(v.number()),
  }).index("email", ["email"]),

  // THE tenant resolver. Inbound (channel,address) -> userId. Uniqueness of
  // (channel,address) is enforced check-then-insert inside one mutation.
  channelBindings: defineTable({
    userId: v.id("users"),
    channel,
    address: v.string(),       // E.164 for imessage; Telegram chat.id (string) for telegram
    verified: v.boolean(),     // true once a pairing token is consumed
    lastInboundAt: v.optional(v.number()),
    createdAt: v.number(),
  })
    .index("by_address", ["channel", "address"]) // webhook lookup (the unique key)
    .index("by_user", ["userId", "channel"]),    // list a user's channels

  // One-time deep-link / connect tokens. Landing mints; webhook consumes.
  pairingTokens: defineTable({
    userId: v.id("users"),
    channel,
    token: v.string(),         // base64url, <=64 chars (Telegram /start payload cap, [A-Za-z0-9_-])
    code: v.string(),          // 6-char A-Z2-9 human-typable (iMessage "pair <code>")
    status: v.union(
      v.literal("active"), v.literal("consumed"),
      v.literal("superseded"), v.literal("expired"),
    ),
    expiresAt: v.number(),     // now + 15 min
    consumedAt: v.optional(v.number()),
    createdAt: v.number(),
  })
    .index("by_token", ["token"])
    .index("by_code", ["code"])
    .index("by_user_channel", ["userId", "channel"]),

  // Durable inbound queue — EVOLVED. userId/channel/replyTarget added (optional
  // during migration, required after backfill). userNumber kept for back-compat.
  messages: defineTable({
    handle: v.string(),               // idempotency key (channel-prefixed for telegram: "tg:<update_id>")
    userId: v.optional(v.id("users")), // resolved owner (optional -> required)
    channel: v.optional(channel),      // imessage | telegram (optional -> required)
    replyTarget: v.optional(v.string()), // address to reply TO — fixes the single-user bug
    userNumber: v.string(),           // LEGACY source address; kept for e2e + back-compat
    text: v.string(),
    mediaUrl: v.optional(v.string()),
    status: v.union(
      v.literal("queued"), v.literal("processing"),
      v.literal("done"), v.literal("error"),
    ),
    reply: v.optional(v.string()),
    receivedAt: v.number(),
    claimedAt: v.optional(v.number()),
    completedAt: v.optional(v.number()),
    error: v.optional(v.string()),
  })
    .index("by_handle", ["handle"])                          // legacy global idempotency
    .index("by_channel_handle", ["channel", "handle"])       // idempotency keyed by (channel,handle)
    .index("by_status", ["status", "receivedAt"])            // LEGACY global claim (operator transition)
    .index("by_status_user", ["status", "userId", "receivedAt"]) // claimNextForUser (fleet)
    .index("by_user", ["userNumber", "receivedAt"])          // legacy recentForUser
    .index("by_userId", ["userId", "receivedAt"]),           // recentForUser by userId

  // Connect intents (Composio) — add userId/channel/replyTarget so a resume
  // message routes to the right user/channel.
  connectIntents: defineTable({
    userId: v.optional(v.id("users")),
    channel: v.optional(channel),
    replyTarget: v.optional(v.string()),
    userNumber: v.string(),
    taskText: v.string(),
    requiredToolkits: v.array(v.string()),
    connectedToolkits: v.array(v.string()),
    status: v.union(v.literal("pending"), v.literal("resumed"), v.literal("expired")),
    createdAt: v.number(),
    resumedAt: v.optional(v.number()),
  })
    .index("by_status", ["status", "createdAt"])
    .index("by_user_status", ["userId", "status"]),

  // Source-of-truth entitlement (one row per user). Written at signup (stub:free)
  // and by future billing webhooks. The quota gate reads this.
  entitlements: defineTable({
    userId: v.id("users"),
    tier,
    status: v.union(v.literal("active"), v.literal("past_due"), v.literal("canceled")),
    msgQuota: v.number(),        // per-period cap (-1 = unlimited, used for operator)
    msgUsed: v.number(),         // HOT atomic counter (read-modify-write in checkAndReserve)
    periodStart: v.number(),     // rolling 30-day window start (ms epoch)
    periodEnd: v.number(),       // periodStart + PERIOD_MS
    source: v.union(             // who set it
      v.literal("stub"), v.literal("paddle"),
      v.literal("stripe"), v.literal("lemonsqueezy"),
    ),
    providerCustomerId: v.optional(v.string()),
    providerSubId: v.optional(v.string()),
    updatedAt: v.number(),
  })
    .index("by_user", ["userId"])
    .index("by_providerSubId", ["providerSubId"]) // billing webhook reconcile (future)
    .index("by_periodEnd", ["periodEnd"]),        // cron: roll periods forward

  // Append-only per-turn meter (no OCC contention). Drives the dashboard.
  usageEvents: defineTable({
    userId: v.id("users"),
    messageId: v.optional(v.id("messages")),
    kind: v.union(v.literal("turn"), v.literal("adjust")),
    lane: v.optional(v.string()),    // "fastlane" | "medium" | "hermes" (observability)
    channel: v.optional(channel),
    units: v.number(),               // turns charged (normally 1; allows future weighting)
    tokensIn: v.optional(v.number()),
    tokensOut: v.optional(v.number()),
    periodStart: v.number(),         // window this counted against
    at: v.number(),
  })
    .index("by_user_at", ["userId", "at"])           // dashboard timeline
    .index("by_user_period", ["userId", "periodStart"]),

  // Idempotent ingest log for FUTURE provider webhooks (dedup by event id).
  billingEvents: defineTable({
    provider: v.string(),
    eventId: v.string(),
    type: v.string(),
    processedAt: v.number(),
  }).index("by_event", ["provider", "eventId"]),

  // Fleet map — desired + actual state of each user's container. The controller
  // reconciles toward this; the worker heartbeats into it.
  agentInstances: defineTable({
    userId: v.id("users"),
    channel: v.optional(channel),
    desired: v.union(v.literal("running"), v.literal("stopped")), // control-loop target
    status: v.union(
      v.literal("provisioning"), v.literal("running"),
      v.literal("stopping"), v.literal("stopped"), v.literal("error"),
    ),
    tier: v.union(v.literal("free"), v.literal("paid")),
    hostVm: v.optional(v.string()),
    containerId: v.optional(v.string()),
    workerSecretRef: v.optional(v.string()), // Secret Manager NAME, never the secret
    lastActiveAt: v.optional(v.number()),    // bumped per claimed msg -> idle reap
    heartbeatAt: v.optional(v.number()),     // bumped each loop -> health
    wantsAt: v.optional(v.number()),         // when desired flipped to running (cold-start clock)
    startedAt: v.optional(v.number()),
    stoppedAt: v.optional(v.number()),
    errorCount: v.optional(v.number()),
    error: v.optional(v.string()),
  })
    .index("by_user", ["userId"])                       // route inbound / 1 instance per user
    .index("by_desired_status", ["desired", "status"])  // reconcile loop
    .index("by_status_heartbeat", ["status", "heartbeatAt"]) // health + idle scan
    .index("by_host_status", ["hostVm", "status"]),     // bin-pack / drain a host
});
```

### 2.1 Worker-facing functions (WORKER_SECRET gate) — brain contract preserved

`messages.ts` — KEEP existing function paths (`claimNext`, `complete`, `fail`,
`recentForUser`) so the live launchd worker never breaks; ADD `claimNextForUser`.

| Function | Kind | Notes |
|---|---|---|
| `enqueue` | internalMutation | idempotent on `(channel,handle)` via `by_channel_handle`, falls back to `by_handle` when channel absent. Sets `status:"queued", receivedAt`. |
| `claimNext` | mutation | **KEPT** for operator/legacy. Claims globally-oldest `queued`. Now also returns `replyTarget` (= `replyTarget ?? userNumber`) + `channel`. Removed only in the final tighten step. |
| `claimNextForUser` | mutation | **NEW.** `withIndex("by_status_user", q=>q.eq("status","queued").eq("userId",userId)).order("asc").first()`. Atomic `patch(status:"processing")`. Returns `{id,handle,userId,channel,replyTarget,userNumber,text,mediaUrl}`. Bumps `agentInstances.lastActiveAt`. |
| `complete` / `fail` | mutation | **UNCHANGED signatures.** |
| `recentForUser` | query | Back-compat: read `by_userId` if `userId` given, else `by_user(userNumber)`. Strictly one user — no cross-tenant bleed. Keeps the `resume:`/`e2e` + empty-row skips. |
| `stats` | query | Replace `.collect()` table scan with per-status counts via `by_status` index. |

`fleet.ts` (NEW): `requestInstance`, `claimInstanceForLaunch`, `heartbeat`,
`markStopped`, `markError`, `listReconcile`, `setDesired` — all WORKER_SECRET / a
dedicated `CONTROLLER_SECRET` gate, indexed, validated.

`quota.ts` (NEW): `checkAndReserve`, `recordUsage`, `releaseReserve` — see §6.

`intents.ts`: `addIntent` gains `userId/channel/replyTarget`; `resolveIntent`
copies them onto the synthetic `resume:` message so it routes correctly; add
`returns` validators to all four.

`lib/identity.ts` (NEW): `resolveUserByAddress({channel,address}) → {userId}|null`
(internalQuery) via `channelBindings.by_address`, returns only **verified** rows.

`pairing.ts` (NEW, internal): `mintToken({userId,channel})`,
`redeemTelegram({token,address,replyTarget,firstName})`,
`redeemImessage({code,address})` — one primitive, both channels (see §7).

### 2.2 User-facing functions (`app/*`, getAuthUserId gate)

`requireUser(ctx)` = `getAuthUserId` then `null → throw`. Every list read uses a
`by_user` index `q.eq("userId", userId)`; after any `ctx.db.get(id)` re-verify
`doc.userId === userId` before returning/mutating.

| Path | Kind | Returns (summary) |
|---|---|---|
| `app/account:currentUser` | query | `{_id,email,displayName,tier,isOperator,createdAt}` of the authed user only |
| `app/channels:myChannels` | query | own `channelBindings` (kind,address,verified,lastInboundAt) |
| `app/channels:createPairingToken` | mutation | `{token,code,expiresAt,channel,deepLink?}`; supersede prior active token for (user,channel) |
| `app/channels:disconnectChannel` | mutation | delete own binding (re-check `userId`) |
| `app/usage:myUsage` | query | `{tier,status,msgUsed,msgQuota,remaining,periodStart,periodEnd}` |
| `app/usage:myUsageTimeline` | query | last N `usageEvents` (own) |
| `app/tiers:chooseTier` | mutation | free → grant entitlement instantly; paid → `{ok, checkoutUrl}` (stub null) |
| `app/upgrade:startCheckout` | action | `activeProvider().createCheckout(userId,tier)` (stub → coming-soon URL) |

**There is NO public `setTier`** — tier changes only via the signup stub and
future billing webhooks (`entitlements` writes), so a client can never escalate.

`admin.ts:grantTier` — WORKER_SECRET-gated manual paid grant for testing.

---

## 3. Channel layer

### 3.1 Inbound (Convex httpAction)

Both webhooks normalize to one `enqueue({handle, userId, channel, replyTarget,
userNumber, text, mediaUrl})`. Both: validate every field (never trust the
payload), authenticate on the one trust boundary, return 200 fast, **never 5xx**
on payload issues (both providers retry on non-2xx).

- **Sendblue** `/sendblue/inbound/<WEBHOOK_SECRET>` — keep the path-token
  constant-time compare. Replace the `ALLOWED_USER_NUMBER` allowlist with
  `resolveUserByAddress("imessage", number)`. `pair <code>` first-message →
  `redeemImessage`. Unknown verified address → ignore (transitional fallback:
  still accept the operator's `ALLOWED_USER_NUMBER` until his binding exists).
- **Telegram** `/telegram/inbound` — auth on the
  `X-Telegram-Bot-Api-Secret-Token` header (`safeEqual` vs
  `TELEGRAM_WEBHOOK_SECRET`). Validate `message.text` + `message.chat.id`; ignore
  `is_bot`, `edited_message`, non-`private` chats. `/start <token>` →
  `redeemTelegram`. Idempotency `handle = "tg:" + update_id`. `replyTarget =
  String(chat.id)`, `userNumber = String(from.id)`.

**Unknown-sender policy:** hint-once-then-drop with a per-address cooldown (a
stranger can't burn the shared bot's 30/s budget or the Sendblue spend). Bots /
channel posts / non-private / edits silently ignored.

### 3.2 The `Channel` abstraction (Python)

`lab/skeleton/channels/` — small focused files. A `Channel` Protocol (duck-typed,
matches the repo style) so the worker is provider-agnostic and one instance
serves all tenants on that provider (address passed per call):

```python
@runtime_checkable
class Channel(Protocol):
    kind: str                                            # "imessage" | "telegram"
    def send_message(self, address: str, text: str) -> OutboundResult: ...
    def send_typing(self, address: str, *, state="start") -> OutboundResult: ...
    def split(self, text: str) -> list[str]: ...         # provider-aware split
    def render(self, text: str) -> str: ...              # plain text -> wire format
```

- `SendblueChannel` wraps the existing `SendblueClient` (zero churn). `render` =
  strip (plain text). `split` = `bubbles.split_into_bubbles` (~1200 chars, ≤4
  Poke bubbles).
- `TelegramChannel` wraps a new `TelegramClient`. `render` = `tg_format.render_html`.
  `split` = `split_html_safe` (≤3800 chars/chunk, never cuts a tag, hard cap 4096).
- `ChannelRegistry.from_config(cfg)` builds only the channels whose creds exist;
  `process_one` selects by the claimed message's `channel`.

`OutboundResult(ok, provider_id, error)` — sends are **best-effort** (`ok=False`
logged, never raised, so a provider hiccup can't kill the always-on loop).

### 3.3 Telegram Bot API 10.1 — outbound formatting

**v1 uses `parse_mode="HTML"`, NOT MarkdownV2, NOT (yet) `sendRichMessage`.**

- HTML escapes only `& < >` — robust for LLM output. MarkdownV2's 18-char escape
  set (`_ * [ ] ( ) ~ \` > # + - = | { } . !` — `.`/`-`/`!`/`=` appear in every
  list/decimal/sentence) is a chronic bug source; avoid it.
- `tg_format.render_html`: escape `& < >` FIRST on dynamic text, stash fenced
  code blocks before inline parsing, then map `**b**→<b>`, `*i*→<i>`,
  `` `code`→<code> ``, ```` ```lang→<pre><code class="language-lang"> ````, long
  tool dumps → `<blockquote expandable>` (the one fancy block parse_mode gives
  for free). The lowercase SOUL voice is untouched — formatting is structural,
  applied after generation.
- **400 fallback:** if a rendered HTML send returns 400, retry once WITHOUT
  `parse_mode` (plain text) so the user always gets the answer.
- `link_preview_options.is_disabled = true` (no giant cards).
- **Streaming is iMessage-only.** Telegram uses ONE batch-rendered message
  (multi-bubble would hit the ~1/s per-chat limit). Gate via `_use_streaming(cfg,
  channel_kind)`.
- **Typing:** `sendChatAction(chat_id,"typing")` re-fired every ≤4.5s
  (auto-clears ~5s); the `stop` fire is a no-op on Telegram. iMessage keeps 6s +
  explicit stop. Reuse `TypingKeepalive` via a thin `_ChannelTypingShim`.
- **Rate limits are PER BOT TOKEN** (~30/s global, ~1/s per chat, 429 →
  `parameters.retry_after`). The worker is the single send path; `TelegramClient`
  honors `retry_after` with one bounded retry.

**Deferred to a later milestone:** the 10.1 `sendRichMessage` object model
(headings/tables/lists/LaTeX/maps/media-in-text) — the underlying agent
(NousResearch/hermes-agent) has it only as open issue #44428, and the model emits
text not a RichBlock tree. The `render()` seam absorbs the swap; for streaming,
`sendRichMessageDraft` is the future native analog of Poke bubbles.

### 3.4 The worker de-hardcode (the keystone fix)

Today (`worker.py:524-525`) every reply is pinned to `cfg.reply_target`
(`= ALLOWED_USER_NUMBER`). The fix, anchored to current code:

```python
# process_one, after claim:
claimed      = convex.mutation(claim_path, claim_args)  # claim_path = "messages:claimNextForUser" in scoped mode
channel_kind = claimed.get("channel") or "imessage"     # default keeps legacy rows working
reply_target = claimed.get("replyTarget") or claimed.get("userNumber") or cfg.reply_target
channel      = channels.get(channel_kind)               # ChannelRegistry, injected
typing  = _make_typing(channel, cfg, reply_target)      # was (sendblue, cfg, cfg.reply_target)
emitter = _BubbleEmitter(channel, reply_target, cfg, typing=typing, sleep_fn=sleep_fn)
```

`_BubbleEmitter` talks to a `Channel` (`render` → `split` → `send_message`), not
Sendblue. `_fetch_history` keys on `userId` (scoped) so no tenant's transcript
bleeds into another's prompt. `cfg.reply_target` survives ONLY as the
migration/legacy fallback for rows predating `replyTarget`.

**Backward-compat:** `process_one(convex, channels_or_client, cfg, ...)` accepts a
`ChannelRegistry` OR a single client (wrapped as `imessage`), so the 200+ existing
tests need only additive `_claim()` fixture edits (add `channel`/`replyTarget`),
not a rewrite. The one test asserting "replies to config target not payload
number" is intentionally UPDATED to "replies to the claimed message's own
address" (the security property changes from a constant to per-message routing).

---

## 4. Fleet orchestrator (GCP)

**Substrate = GCE VM + Docker.** Rejected: Cloud Run Services (no continuous CPU
for a poll loop), Worker Pools (no per-tenant scale-to-zero, ~$16+/mo each),
GKE Autopilot ($73/mo cluster floor + per-pod premium), Filestore ($164/mo
floor). A **stopped container costs $0 compute** — the only shape where idle free
users are ~free and active cost stays at the measured $2-4/mo on M3.

- 1× `e2-standard-8` (32 GB) host running Docker; bin-pack ~20-30 agents
  (RE-MEASURE browser-inclusive RAM first — REPORT's 290-500 MB is browserless;
  resident Chrome adds 150-400 MB → realistic ~700 MB-1 GB/agent). Spill to a 2nd
  host at ~70% RAM.
- 1× `e2-small` controller VM (~$13/mo) running the reconcile loop.
- **First gcloud action:** `gcloud services enable compute.googleapis.com
  secretmanager.googleapis.com --project=hermes-saved-content-lab` (compute is
  currently DISABLED; the active default project is `tensol-scanners`, so EVERY
  fleet `gcloud` MUST pass `--project=hermes-saved-content-lab`).

**Container image** (`lab/docker/Dockerfile.fleet`): layers on the existing
`resolver-core:lab` base + Hermes (git clone + venv, pinned via `HERMES_REF` build
arg) + `chromium` (agent-browser local profile, the shipped path — NOT Camoufox) +
worker modules + SOUL + `tini` PID-1 (clean `docker stop`). `HERMES_HOME` is a
runtime VOLUME, never baked in. In-image mocked pytest gate (hermetic, no network).

**Container env contract** (12-factor): `WORKER_MODE=scoped`, `USER_ID`,
`CONVEX_URL`, `WORKER_SECRET` (per-instance, from Secret Manager), `HERMES_HOME`,
`MINIMAX_API_KEY`/`MINIMAX_MODEL=MiniMax-M3`, Sendblue creds (shared number),
`TELEGRAM_BOT_TOKEN` (shared bot), `EXA_API_KEY`, `INSTANCE_ID`. **No
`ALLOWED_USER_NUMBER`/`cfg.reply_target` in scoped mode.**

**Persistence — "local-disk live, GCS durable":** live `HERMES_HOME` on the
host's balanced PD at `/data/tenants/<userId>` (0700, sound SQLite/browser-cookie
locking; gcsfuse on a live profile corrupts SQLite — forbidden). Mirror per-user
to `gs://hermes-fleet-state/<userId>/` on container stop + on a timer (`gcloud
storage rsync`, exclude `*.lock`/`SingletonLock`/`*-journal`/`*-wal`, **quiesce
the browser via `docker stop` first**). Rehydrate from GCS on cold-start.
Rebalancing = stop → sync up → rehydrate on target → start.

**Controller** (`fleet/controller/`): `controller.py` (reconcile loop, ~3s poll
of `fleet:listReconcile`, backs off + logs on error, never dies), `docker_driver`
(launch/stop/inspect, mockable), `placement` (greedy least-loaded-fit, 30%
headroom), `state_sync` (GCS rehydrate/mirror), `secrets` (Secret Manager:
`ensure_worker_secret(userId)`), `convex_admin`, `config`. Responsibilities:
- **Launch** (cold-start): inbound webhook enqueues durably AND calls
  `fleet:requestInstance(desired=running)`; controller picks a host → rehydrate →
  ensure secret → `docker run` → `claimInstanceForLaunch`. New worker drains the
  queue. Hide latency with the existing fast-lane "одну сек…" / typing.
- **Health:** worker writes `heartbeatAt` each loop; stale (> `STALE_TTL`) →
  inspect/relaunch; mark `error` after N fails + alert.
- **Idle-reap:** free `IDLE_TTL=30min` → quiesce → mirror → `docker stop` →
  `markStopped` ($0 idle). Paid `IDLE_TTL=0` (stays warm).
- **Bin-pack:** placement on every launch; spill / refuse-with-alert when full.

A crashed-mid-flight `processing` row is reset to `queued` by the
`reapStaleProcessing` cron (this area DEPENDS on that cron).

---

## 5. Tiers (data-driven)

`control-plane/convex/billing/tiers.ts` — a const so changing a number is a
one-line edit, never a migration. Sized off the measured **~$2-4/active-user/mo
on M3**. A "message" = one inbound turn the worker actually runs (fast/medium/
heavy all == 1; synthetic `resume:`/`e2e` == 0).

| Tier | $/mo (placeholder) | msgQuota / 30d | Concurrency | Channels | History depth | Purchasable |
|------|--------------------|----------------|-------------|----------|---------------|-------------|
| Free | $0 | 100 | 1 | iMessage + Telegram | 6 | auto at signup |
| Pro  | $19 | 1000 | 2 | iMessage + Telegram | 12 | yes (stubbed) |
| Max  | $49 | 5000 | 3 | iMessage + Telegram | 20 | yes (stubbed) |

Free 100 turns ≈ $0.5-1/mo model spend (safe for a flood of idle free signups —
idle containers are $0 compute). Pro 1000 lands on the measured $2-4 envelope.
Max 5000 for heavy browser/video users. `PERIOD_MS = 30 days`. Prices are
placeholders since billing is stubbed; channel list is data so it can diverge
later, but is identical across tiers per decision #3.

---

## 6. Quotas, metering, billing adapter

**Quota gate = `checkAndReserve`, placed in the WORKER right after claim**
(not in the webhook): the upsell reply uses the existing channel/emitter path,
the webhook stays dumb + non-5xx, and over-quota costs zero model spend. The
reserve happens before any model call.

`quota.ts` (WORKER_SECRET-gated):
- `checkAndReserve({workerSecret,userId}) → {allowed,tier,remaining,msgQuota,periodEnd,reason?}`.
  Atomic in ONE mutation transaction: read entitlement → `rollIfExpired` (period
  boundary self-rolls even if the cron hasn't fired) → if room, `msgUsed++` and
  allow; else deny with `reason` (`over_quota`/`canceled`/`no_entitlement`).
  Atomicity prevents two concurrent turns from both consuming the last unit.
- `recordUsage(...)` — append one `usageEvents` row after a turn (audit/dashboard).
- `releaseReserve({workerSecret,userId})` — refund on a hard turn failure so the
  user isn't charged for an undelivered turn.

`lab/skeleton/quota_client.py` (NEW, thin): `check_and_reserve` called after the
claim, **skipped for synthetic `resume:`/`e2e`** (avoid double-charge the connect
flow). **FAIL OPEN on a Convex error** (a control-plane hiccup must not lock every
paying user out), **FAIL CLOSED on a clean over-quota** (send a friendly lowercase
upsell with `UPGRADE_URL` and `messages:complete`, run NO lane). `user_id=None`
(pre-migration / operator) → unmetered.

**Billing adapter seam** (`control-plane/convex/billing/`):
- `provider.ts` — `BillingProvider { id, createCheckout(userId,tier),
  handleWebhook(req), portalUrl(userId) }` + `EntitlementChange`.
- `stub.ts` — `StubProvider` ACTIVE now: `createCheckout` → coming-soon URL,
  `handleWebhook` → `{ok:false}`. Free fully live.
- `registry.ts` — `activeProvider()` keyed on `BILLING_PROVIDER` env (default
  `stub`).
- `grant.ts` — `applyEntitlement` internalMutation: THE single place entitlements
  are written (signup, admin grant, AND every future webhook funnel through it),
  plus `rollExpiredPeriods` + `pruneOldUsage` (paginated `take(500)` + self-
  reschedule). The signup callback calls `applyEntitlement(userId,"free","active")`.

**Where Paddle/Stripe/LemonSqueezy drops in later (and what stays unchanged):**
one new `billing/<provider>.ts` (implements `BillingProvider`, signature-verifies
its webhook) + one `registry.ts` line + one `http.ts` route
(`/billing/<provider>`: verify → dedup on `billingEvents.by_event` →
`applyEntitlement`). Unchanged: `tiers.ts`, the schema, `quota.ts`, `grant.ts`,
`app/billing.ts`, the worker, and the WORKER_SECRET gate model.

---

## 7. Landing + connect flow

**App = `web/`** (top-level, flat — no workspace tooling). Next.js 15 App Router +
React 19 + TS + Tailwind v4 + shadcn/ui + `@convex-dev/auth` (pin
`@auth/core@0.37.0`). **Deploy on Vercel**; Convex Cloud is the backend
(`NEXT_PUBLIC_CONVEX_URL` → `zany-tapir-501.convex.cloud`; auth code lives in
`control-plane/convex/`). The web app imports the control-plane generated `api`
via a path alias (`@cp/api`) for end-to-end type safety. Identity is ALWAYS the
JWT subject — no function takes a client-supplied `userId`.

- **Auth:** Google OAuth + email-OTP (8-digit via Resend) for SMS-parity UX; both
  dedupe to one `users` row by email. Wiring: `ConvexAuthNextjsServerProvider`
  (root layout) + `ConvexAuthNextjsProvider` (client) +
  `convexAuthNextjsMiddleware` gating `/dashboard(.*)` + `/connect(.*)`,
  bouncing authed off `/signin`.
- **Routes:** `/` (marketing), `/signin`, `/dashboard` (TierCard + UsagePanel +
  ConnectionsPanel), `/connect` (ConnectWizard).

**Pairing primitive** (the keystone): one `pairingTokens` row carries BOTH a
base64url 22-char `token` (Telegram `/start`, within the 64-char `[A-Za-z0-9_-]`
cap — strip `=` padding, use `-`/`_`) and a 6-char human-typable `code` (iMessage
`pair <code>`). 15-min TTL, single-use, one active per (user,channel),
supersede-on-remint.

**Connect wizard state machine** (driven by reactive Convex reads — no polling):

```
[choose tier] -> chooseTier()
   free -> entitlement granted instantly -> [choose channel]
   paid -> checkoutUrl===null -> toast "paid plans launching soon; you're on free" -> [choose channel]
[choose channel]  iMessage | Telegram  -> createPairingToken({channel}) -> {token, code, expiresAt}
[show pairing]
   telegram -> deep-link button (t.me/<bot>?start=<token>) + QR + live "waiting…"
   imessage -> imessage:/sms: link prefilled "pair <code>" + copyable code chip
[verified]  (myChannels shows {kind, verified:true}) -> "you're connected — say hi 👋"
```

`PairingStatus` subscribes to `useQuery(myChannels)`; the webhook binding flips
the UI live with zero client polling. A countdown shows `expiresAt`; on expiry,
"get a new link" re-mints.

**Telegram sequence:** mint token → deep-link/QR → user taps START → webhook sees
`/start <token>` → `redeemTelegram` binds `(telegram, chat.id) → userId`, marks
consumed, replies a canned welcome → dashboard flips. **iMessage sequence:** mint
code → `imessage://<number>?body=pair%20<code>` → user sends `pair <code>` →
webhook detects `/^pair\s+([A-Z2-9]{6})$/i` → `redeemImessage` binds
`(imessage, E.164) → userId`, replies welcome → dashboard flips.

**Pairing safety:** consume validates `status=="active" && expiresAt>now &&
channel matches`; re-tapping a consumed token is idempotent (re-greet, no 2nd
binding); binding an external id already owned by a DIFFERENT user is REJECTED
("already linked to another account" — prevents tenant hijack); the iMessage
webhook rate-limits failed `pair` attempts per number (the 6-char code is ~31
bits — TTL + single-use + silent-fail mitigate brute force).

**Design system:** dark "calm terminal for a living assistant" — near-black canvas,
one signal-lime accent for the live connected-pulse + primary CTAs, mono wordmark
+ humanist body, lowercase voice echoing the product. Hero = oversized lowercase
headline + a live-typing iMessage/Telegram bubble mock. Connect wizard =
one-thing-per-screen with a big QR / mono code chip + a "waiting…" dot that turns
into a lime check on bind. Restrained motion.

---

## 8. Security & per-tenant isolation

- **A1/A2/A4** (§1) enforced structurally: tenant key is `Id<"users">`; the
  worker replies only to the claimed row's `replyTarget`; the two gate modules
  never mix.
- **Index-only tenant reads.** Every owned read uses a `by_user`/`by_userId`/
  `by_address` index `q.eq("userId"|"address", …)` — never `.filter()`, never
  fetch-all-then-check. After `ctx.db.get(id)`, re-verify `doc.userId === userId`.
- **Per-instance WORKER_SECRET** in Secret Manager (`hermes-worker-<userId>`);
  Convex stores only `workerSecretRef`. First cut: one global `WORKER_SECRET` gate
  + strict server-side `userId`-scoping of every scoped function (so even the
  global secret can only touch its own user's rows via `claimNextForUser(userId)`);
  hardened drop-in: `assertWorkerForUser(secret,userId)` validating a per-user
  secret hash. **Per-user secrets are required before real paying tenants.**
- **Inbound trust boundary** = the path token (Sendblue) / the
  `X-Telegram-Bot-Api-Secret-Token` header (Telegram), both constant-time. Every
  payload field is validated; unknown senders dropped (hint-once + cooldown).
- **Container OS isolation:** separate `HERMES_HOME` mount + separate container ⇒
  separate browser session, model context, saved-content DB. One user can never
  see another's data, history, or browser.
- **No hardcoded secrets:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, JWT
  keys, per-instance worker secrets, model/Exa/Sendblue keys all in Convex env /
  Secret Manager / the worker `.env` (chmod 600). (Hygiene carry-forward: 6
  previously-pasted keys still pending rotation.)

---

## 9. Convex Auth setup (no interactive CLI)

`npm i @convex-dev/auth @auth/core@0.37.0` in `control-plane/`. Generate keys
with the `jose` one-liner and `npx convex env set` them on BOTH `zany-tapir-501`
and `adept-dragon-928` (avoids the TTY prompt that else causes the
`Cannot read properties of null (reading 'redirect')` sign-in error):

```bash
node -e 'import("jose").then(async (j)=>{const k=await j.generateKeyPair("RS256",{extractable:true});const pk=await j.exportPKCS8(k.privateKey);const jwk=await j.exportJWK(k.publicKey);console.log(`JWT_PRIVATE_KEY="${pk.trimEnd().replace(/\n/g," ")}"`);console.log("JWKS="+JSON.stringify({keys:[{use:"sig",...jwk}]}));})'
npx convex env set JWT_PRIVATE_KEY "..."; npx convex env set JWKS '...'; npx convex env set SITE_URL https://<landing-domain>
```

`auth.ts` (Google + ResendOTP) with a `createOrUpdateUser` callback that dedupes
by email, sets `isOperator` on the operator's email, and calls
`applyEntitlement(userId,"free","active")` (operator → `"max"`, `msgQuota:-1`).
`auth.addHttpRoutes(http)` is APPENDED to the existing `http.ts` router (the
Sendblue route stays).

---

## 10. Zero-downtime migration (operator = user #0)

Grounded in live `zany-tapir-501`: **39 messages (all operator `+79217818876`, 38
done / 1 error), 3 connectIntents (2 operator + 1 stray `+test-ignore`).** Convex
rejects a push that invalidates existing rows (`Schema validation failed`) — that
is the safety net. Keep BOTH `claimNext` and `claimNextForUser` for the whole
window; remove `claimNext` only at the end.

| Step | Action | Verify |
|---|---|---|
| **0** | Freeze a single-user golden-path canary (`test_regression_single_user.py`); tag `pre-multitenant-baseline`. | `cd lab && python3 -m pytest -q` ≥ 208 passed |
| **1** | Auth keys + Telegram env set on BOTH deployments (§9). | `npx convex env list \| grep -E 'JWT_PRIVATE_KEY\|JWKS\|SITE_URL'` |
| **2** | Additive schema push: spread `...authTables`, add all new tables, add `messages`/`connectIntents` new columns as `v.optional`, add all new indexes. 39 rows still validate. | push succeeds, `messages:stats` counts unchanged |
| **3** | Add `claimNextForUser` ALONGSIDE `claimNext` (unchanged). | enqueue two userIds → `claimNextForUser(A)` returns only A's row |
| **4** | Operator signs in once on the landing → `users` row; callback sets `isOperator` + `max` entitlement. | `currentUser` shows isOperator |
| **5** | One-off `backfillOperator` internalMutation: insert verified `channelBindings{imessage,+79217818876}`; patch all operator `messages`/`connectIntents` with `userId/channel/replyTarget`. Delete the `+test-ignore` intent. | `countMessagesMissingUserId` == 0; binding verified |
| **6** | Switch webhook resolution constant→`resolveUserByAddress`, keep `ALLOWED_USER_NUMBER` fallback one deploy. Add `/telegram/inbound`. | operator inbound → 200 + row has userId; unknown → ignored |
| **7** | Bring up a SECOND test user on the new path; prove no cross-talk with two local workers while the Mac worker runs unchanged. | two-user isolation e2e green |
| **8** | Cut the operator over: deploy his scoped container (`USER_ID=+operator`, `claimNextForUser`), sync `~/.hermes-savedlab` → GCS, run old+new in PARALLEL briefly (atomic `status->processing` ⇒ at-most-once claim, no double reply), then stop the Mac daemon. | one real iMessage → exactly one reply |
| **9** | Tighten: re-push `messages.userId/channel/replyTarget` + `connectIntents.userId` REQUIRED; remove the `ALLOWED_USER_NUMBER` fallback; remove `claimNext`. | `npx convex deploy` succeeds; `grep claimNext\\b` shows only `claimNextForUser` |

Run Steps 2/5/9 on prod `adept-dragon-928` too (operator-run; re-derive the
backfill from prod's actual rows first). Rollback before Step 9 = redeploy
previous functions (everything additive; the legacy `claimNext`/launchd path is
still present and serving).

---

## 11. Test strategy (summary; full matrix in the plan)

Three tiers, with a NEW gating convention (`conftest.py` skip markers +
`pytest.ini` markers) since none exists today:
- **UNIT** — MagicMock collaborators, network-free, CI default.
- **CONVEX-INTEGRATION** — real Convex functions via the HTTP API / `convex run`,
  gated `RUN_CONVEX_E2E` (catches a wrong index / missing validator the mocks miss).
- **E2E** — LOCAL (real dev Convex + two SAME-code worker loops pinned to
  `USER_ID=A/B` + fake channels capturing sends + an echo `run_fn` encoding the
  tenant home → isolation provable for $0, zero GCP) and LIVE (~6 operator-run:
  real Telegram render, real Sendblue iMessage, real deep-link tap, real provider
  webhook dispatch, live cutover smoke).

CI runs `pytest -m "not convex_e2e and not live_channel"`. Use a THROWAWAY dev
deployment (or `e2e`/`resume:` handle prefixes that `recentForUser` already skips)
so e2e seeds never pollute the operator's live queue/memory. The most important
tests: reply-to-claimed-channel-not-config-target, two-user no-cross-talk,
recentForUser isolation, per-user HERMES_HOME isolation, pairing single-use/expiry,
quota-blocks-run, idempotent duplicate webhook, cold-start drains.

---

## 12. Conflicts between area designs — resolved

The six area designs were merged; where they differed, this spec picks ONE answer.

1. **Quota gate placement (research/Convex-tenancy said webhook-side; billing area
   said worker-side).** → **Worker-side `checkAndReserve` after claim.** The
   webhook stays dumb + non-5xx, the upsell reuses the channel/emitter path, and
   the reserve is still pre-model so over-quota costs $0 tokens. The webhook does
   NOT gate.

2. **`claimNextForUser` arg = `userNumber` (fleet/migration areas) vs `userId`
   (Convex-tenancy/billing areas).** → **`userId`** (the stable tenant key, A1).
   The fleet container is pinned by `USER_ID`. Legacy `claimNext` (operator
   transition) keeps using the global path; `userNumber` survives only as a
   fallback address on `messages`.

3. **`messages` reply field name: `replyTo` (fleet area) vs `replyTarget`
   (Convex-tenancy/channels areas).** → **`replyTarget`** everywhere (matches the
   most areas + the channel layer). The fleet `claimNextForUser` returns
   `replyTarget`.

4. **`agentInstances` fields: two slightly different shapes (Convex-tenancy used
   `lastHeartbeat`; fleet used `heartbeatAt`+`desired`).** → **Fleet's
   desired-state shape wins** (`desired` + `status` + `heartbeatAt` +
   `lastActiveAt` + `wantsAt`) because the controller is a reconcile loop that
   needs an explicit desired column. Index `by_status_heartbeat` (not
   `by_status[status,lastActiveAt]`).

5. **Billing tables: Convex-tenancy proposed `usage` (counter row per period) +
   `entitlements.msgQuota`; billing area proposed `usageEvents` (append-only) +
   `entitlements.msgUsed` hot counter.** → **Billing area's model wins:**
   `entitlements.msgUsed` is the O(1) race-free gate counter; `usageEvents` is the
   append-only audit ledger (no OCC contention). The landing's `myUsage` reads
   `entitlements.msgUsed/msgQuota` directly (no separate `usage` table). One
   `entitlements` table, one `usageEvents` table.

6. **Pairing token: Convex-tenancy used `pairingTokens{token}` only; channels area
   added a copy-paste `pair <token>` for iMessage; landing area added a separate
   6-char `code` column.** → **One row with BOTH `token` (Telegram deep-link) and
   `code` (iMessage typed)** — the landing's design, which is the cleanest UX for
   each channel. The iMessage command is `pair <code>` (6-char), not `pair <token>`.

7. **`billingEvents` ownership (Convex-tenancy flagged it unowned).** → **Owned by
   the billing area, defined in the one `schema.ts`** (it's in §2 above). Empty
   until a real provider is wired.

8. **Unknown inbound address (Convex-tenancy: silent drop; channels: hint-once +
   cooldown).** → **Hint-once-then-drop with a per-address cooldown** (better UX,
   still spam-safe). Bots/non-private/edits silently ignored.

9. **`stats` query — both flagged the `.collect()` scan.** → **Replace with
   per-status counts via `by_status`** in this migration (not deferred).

10. **Welcome-on-pair delivery (channels area asked queue vs direct).** → **The
    redeem mutation enqueues a synthetic welcome message** (reuses the durable
    queue + channel send path; the worker turns a `__welcome__` sentinel into a
    canned lowercase greeting WITHOUT a model call, charged 0). No special-case
    outbound in Convex.
