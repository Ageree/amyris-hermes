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
    .index("by_user_channel", ["userId", "channel"])
    .index("by_status_expiry", ["status", "expiresAt"]), // cron: expire stale active tokens

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
