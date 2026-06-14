import { mutation, internalMutation, query } from "./_generated/server";
import { v } from "convex/values";
import { assertWorker, channelValidator } from "./lib/auth";

// Durable inbound queue. Sendblue / Telegram webhooks enqueue here; the brain
// (Hermes + browser) polls claimNext / claimNextForUser, processes, then
// complete / fail. Because the queue is durable, messages are never lost while
// the brain is offline (A3). All worker-facing functions gate on the shared
// WORKER_SECRET argument (A4) via lib/auth.assertWorker.

// ---------------------------------------------------------------------------
// enqueue (internal — called only by the HTTP webhooks / resolveIntent).
// Idempotent on (channel, handle) via by_channel_handle, falling back to the
// legacy by_handle when channel is absent (pre-migration / operator rows). New
// userId/channel/replyTarget are optional during the additive migration window;
// they tighten to required after backfill (design §10 step 9).
// ---------------------------------------------------------------------------
export const enqueue = internalMutation({
  args: {
    handle: v.string(),
    userId: v.optional(v.id("users")),
    channel: v.optional(channelValidator),
    replyTarget: v.optional(v.string()),
    userNumber: v.string(),
    text: v.string(),
    mediaUrl: v.optional(v.string()),
  },
  returns: v.id("messages"),
  handler: async (ctx, args) => {
    // Dedup keyed by (channel, handle) when channel is known (Telegram update_ids
    // and Sendblue handles share no namespace, so the compound key is the precise
    // idempotency unit); fall back to the global by_handle for channel-less rows.
    const existing = args.channel
      ? await ctx.db
          .query("messages")
          .withIndex("by_channel_handle", (q) =>
            q.eq("channel", args.channel).eq("handle", args.handle),
          )
          .first()
      : await ctx.db
          .query("messages")
          .withIndex("by_handle", (q) => q.eq("handle", args.handle))
          .first();
    if (existing) return existing._id; // duplicate delivery — ignore

    return await ctx.db.insert("messages", {
      handle: args.handle,
      userId: args.userId,
      channel: args.channel,
      replyTarget: args.replyTarget,
      userNumber: args.userNumber,
      text: args.text,
      mediaUrl: args.mediaUrl,
      status: "queued",
      receivedAt: Date.now(),
    });
  },
});

// Shared return shape for a claimed message. mediaUrl/channel/replyTarget/userId
// are nullable because legacy rows predate them; the worker defaults channel ->
// "imessage" and replyTarget -> userNumber (A2: reply by the message's OWN
// address, never a global constant).
const claimReturns = v.union(
  v.null(),
  v.object({
    id: v.id("messages"),
    handle: v.string(),
    userId: v.union(v.id("users"), v.null()),
    channel: v.union(channelValidator, v.null()),
    replyTarget: v.string(),
    userNumber: v.string(),
    text: v.string(),
    mediaUrl: v.union(v.string(), v.null()),
  }),
);

// ---------------------------------------------------------------------------
// claimNext — KEPT for the operator/legacy launchd worker. Scoped to UNASSIGNED
// (userId === undefined) queued rows via by_status_user, NOT every queued row.
// Rationale (design §10 cutover safety): once the fleet starts enqueuing tenant
// rows (userId set) into the SAME deployment while the legacy global worker is
// still running, an unscoped claimNext would STEAL another tenant's message and
// reply to the operator (A2 violation). Restricting to userId===undefined means
// the legacy worker only ever drains the operator's own (un-backfilled) rows;
// tenant rows are reachable solely via claimNextForUser. The operator's 38 live
// rows are all userId-undefined, so behavior for him is unchanged. Same
// signature ({workerSecret}) — the brain contract is preserved. Removed at the
// final tighten step (design §10 step 9), after the operator is backfilled.
// ---------------------------------------------------------------------------
export const claimNext = mutation({
  args: { workerSecret: v.string() },
  returns: claimReturns,
  handler: async (ctx, { workerSecret }) => {
    assertWorker(workerSecret);
    const next = await ctx.db
      .query("messages")
      .withIndex("by_status_user", (q) =>
        q.eq("status", "queued").eq("userId", undefined),
      )
      .order("asc")
      .first();
    if (!next) return null;
    await ctx.db.patch(next._id, { status: "processing", claimedAt: Date.now() });
    return {
      id: next._id,
      handle: next.handle,
      userId: next.userId ?? null,
      channel: next.channel ?? null,
      replyTarget: next.replyTarget ?? next.userNumber,
      userNumber: next.userNumber,
      text: next.text,
      mediaUrl: next.mediaUrl ?? null,
    };
  },
});

// ---------------------------------------------------------------------------
// claimNextForUser — NEW (fleet). A scoped container (USER_ID pinned) claims only
// ITS user's oldest queued row via the by_status_user index — even with the first-
// cut single global WORKER_SECRET, server-side userId-scoping means a worker can
// only ever touch its own tenant's rows (design §8). Atomic patch to "processing"
// gives at-most-once claim (no double reply if old+new workers overlap during
// cutover). Bumps agentInstances.lastActiveAt so the idle-reaper keeps it warm.
// ---------------------------------------------------------------------------
export const claimNextForUser = mutation({
  args: { workerSecret: v.string(), userId: v.id("users") },
  returns: claimReturns,
  handler: async (ctx, { workerSecret, userId }) => {
    assertWorker(workerSecret);
    const next = await ctx.db
      .query("messages")
      .withIndex("by_status_user", (q) =>
        q.eq("status", "queued").eq("userId", userId),
      )
      .order("asc")
      .first();
    if (!next) return null;
    await ctx.db.patch(next._id, { status: "processing", claimedAt: Date.now() });

    // Idle-reap clock: bump the user's instance lastActiveAt (one row per user via
    // by_user). Best-effort — a missing instance row (pre-fleet) is not an error.
    const instance = await ctx.db
      .query("agentInstances")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    if (instance) {
      await ctx.db.patch(instance._id, { lastActiveAt: Date.now() });
    }

    return {
      id: next._id,
      handle: next.handle,
      userId: next.userId ?? null,
      channel: next.channel ?? null,
      replyTarget: next.replyTarget ?? next.userNumber,
      userNumber: next.userNumber,
      text: next.text,
      mediaUrl: next.mediaUrl ?? null,
    };
  },
});

// complete / fail — UNCHANGED signatures (live brain contract). Only a returns
// validator is added (it returns nothing; v.null() encodes "no return value").
export const complete = mutation({
  args: { workerSecret: v.string(), id: v.id("messages"), reply: v.string() },
  returns: v.null(),
  handler: async (ctx, { workerSecret, id, reply }) => {
    assertWorker(workerSecret);
    await ctx.db.patch(id, { status: "done", reply, completedAt: Date.now() });
    return null;
  },
});

export const fail = mutation({
  args: { workerSecret: v.string(), id: v.id("messages"), error: v.string() },
  returns: v.null(),
  handler: async (ctx, { workerSecret, id, error }) => {
    assertWorker(workerSecret);
    await ctx.db.patch(id, { status: "error", error, completedAt: Date.now() });
    return null;
  },
});

// ---------------------------------------------------------------------------
// recentForUser — conversation memory for the (otherwise stateless) assistant.
// Back-compat: read by_userId when a userId is given (the stable tenant key, A1),
// else fall back to by_user(userNumber) for the legacy/operator path. Strictly
// ONE user — no cross-tenant bleed. Keeps the resume:/e2e + empty-row skips, and
// now skips non-"done" rows in the JS loop (instead of a .filter() table-scan
// refinement) — overfetching n*4 to absorb the dropped rows.
// ---------------------------------------------------------------------------
export const recentForUser = query({
  args: {
    workerSecret: v.string(),
    userId: v.optional(v.id("users")),
    userNumber: v.optional(v.string()),
    limit: v.number(),
  },
  returns: v.array(
    v.object({
      text: v.string(),
      reply: v.string(),
      receivedAt: v.number(),
    }),
  ),
  handler: async (ctx, { workerSecret, userId, userNumber, limit }) => {
    assertWorker(workerSecret);
    const n = Math.max(1, Math.min(20, Math.floor(limit)));

    // Prefer the tenant key; fall back to the source address. With neither there
    // is no user to scope to — return empty rather than scan the whole table.
    const rows = userId
      ? await ctx.db
          .query("messages")
          .withIndex("by_userId", (q) => q.eq("userId", userId))
          .order("desc")
          .take(n * 4)
      : userNumber
        ? await ctx.db
            .query("messages")
            .withIndex("by_user", (q) => q.eq("userNumber", userNumber))
            .order("desc")
            .take(n * 4)
        : [];

    const out: { text: string; reply: string; receivedAt: number }[] = [];
    for (const m of rows) {
      if (m.status !== "done") continue;
      if (m.handle.startsWith("resume:") || m.handle.startsWith("e2e")) continue;
      if (!m.text || !m.reply) continue;
      out.push({ text: m.text, reply: m.reply, receivedAt: m.receivedAt });
      if (out.length >= n) break;
    }
    out.reverse(); // chronological: oldest first, so it reads as a transcript
    return out;
  },
});

// ---------------------------------------------------------------------------
// stats — operational counts. Replaces the full-table .collect() scan with one
// bounded indexed take per status via by_status (design §12 #9): a flood of rows
// can't blow the ~16k read limit / 1s CPU budget. Each .take(MAX) is index-
// ordered; counts above MAX are reported as MAX (good enough for an ops view).
// ---------------------------------------------------------------------------
const STATS_MAX = 5000;
const STATUSES = ["queued", "processing", "done", "error"] as const;

export const stats = query({
  args: { workerSecret: v.string() },
  returns: v.object({
    total: v.number(),
    queued: v.number(),
    processing: v.number(),
    done: v.number(),
    error: v.number(),
  }),
  handler: async (ctx, { workerSecret }) => {
    // Ops-only aggregate (no per-tenant data) — still WORKER_SECRET-gated so the
    // fleet-wide queue volume isn't readable by any anonymous client (A4).
    assertWorker(workerSecret);
    const counts: Record<(typeof STATUSES)[number], number> = {
      queued: 0,
      processing: 0,
      done: 0,
      error: 0,
    };
    for (const status of STATUSES) {
      const rows = await ctx.db
        .query("messages")
        .withIndex("by_status", (q) => q.eq("status", status))
        .take(STATS_MAX);
      counts[status] = rows.length;
    }
    const total =
      counts.queued + counts.processing + counts.done + counts.error;
    return { total, ...counts };
  },
});
