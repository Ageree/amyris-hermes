import { mutation, query } from "./_generated/server";
import { v } from "convex/values";
import { assertWorker, channelValidator } from "./lib/auth";

// ---------------------------------------------------------------------------
// Connect-intents (Composio). Worker-facing (WORKER_SECRET) — the brain records
// an intent when it texts a connect-link, polls for completion, and resumes the
// task once the required toolkits are ACTIVE. Kept as PUBLIC functions because
// the Python worker calls them over the Convex HTTP API (which can only reach
// public functions); the constant-time WORKER_SECRET gate (lib/auth) is the
// authn boundary. Reads are bounded; A1/A2 routing fields (userId/channel/
// replyTarget) are carried through so a resumed task replies to the right tenant.
// ---------------------------------------------------------------------------

// Bound every pending scan so a flood of intents can't blow the read/CPU limit.
const PENDING_SCAN_LIMIT = 200;

const covers = (have: string[], need: string[]) => need.every((t) => have.includes(t));
const toolkitKey = (t: string[]) => t.slice().sort().join(",");

// Brain (pending.py) records the intent when it texts a connect-link.
// Light dedupe: an identical still-pending intent is returned, not duplicated.
export const addIntent = mutation({
  args: {
    workerSecret: v.string(),
    userNumber: v.string(),
    taskText: v.string(),
    requiredToolkits: v.array(v.string()),
    // A1/A2 routing (optional during migration; populated by the fleet worker).
    userId: v.optional(v.id("users")),
    channel: v.optional(channelValidator),
    replyTarget: v.optional(v.string()),
  },
  returns: v.id("connectIntents"),
  handler: async (
    ctx,
    { workerSecret, userNumber, taskText, requiredToolkits, userId, channel, replyTarget },
  ) => {
    assertWorker(workerSecret);
    // Dedupe scope: per-user (small, index-bounded) when we have a tenant key,
    // else the legacy global scan — bounded so it can't exceed the read limit.
    const pending = userId
      ? await ctx.db
          .query("connectIntents")
          .withIndex("by_user_status", (q) => q.eq("userId", userId).eq("status", "pending"))
          .take(PENDING_SCAN_LIMIT)
      : await ctx.db
          .query("connectIntents")
          .withIndex("by_status", (q) => q.eq("status", "pending"))
          .take(PENDING_SCAN_LIMIT);
    const dup = pending.find(
      (p) =>
        p.userNumber === userNumber &&
        p.taskText === taskText &&
        toolkitKey(p.requiredToolkits) === toolkitKey(requiredToolkits),
    );
    if (dup) return dup._id;
    return await ctx.db.insert("connectIntents", {
      userId,
      channel,
      replyTarget,
      userNumber,
      taskText,
      requiredToolkits,
      connectedToolkits: [],
      status: "pending",
      createdAt: Date.now(),
    });
  },
});

// Worker polls this each tick (single-worker model → global, bounded scan).
export const listPending = query({
  args: { workerSecret: v.string() },
  returns: v.array(
    v.object({
      id: v.id("connectIntents"),
      userNumber: v.string(),
      taskText: v.string(),
      requiredToolkits: v.array(v.string()),
      connectedToolkits: v.array(v.string()),
      createdAt: v.number(),
    }),
  ),
  handler: async (ctx, { workerSecret }) => {
    assertWorker(workerSecret);
    const rows = await ctx.db
      .query("connectIntents")
      .withIndex("by_status", (q) => q.eq("status", "pending"))
      .take(PENDING_SCAN_LIMIT);
    return rows.map((r) => ({
      id: r._id,
      userNumber: r.userNumber,
      taskText: r.taskText,
      requiredToolkits: r.requiredToolkits,
      connectedToolkits: r.connectedToolkits,
      createdAt: r.createdAt,
    }));
  },
});

// Worker reports the currently-ACTIVE toolkits. If they cover the requirement,
// mark resumed and enqueue a synthetic resume message (idempotent by handle).
// The resume message carries the intent's OWN routing fields (A1/A2), so a
// resumed task is claimed by the right tenant and replies to the right address.
export const resolveIntent = mutation({
  args: {
    workerSecret: v.string(),
    id: v.id("connectIntents"),
    connectedToolkits: v.array(v.string()),
  },
  returns: v.object({ resumed: v.boolean() }),
  handler: async (ctx, { workerSecret, id, connectedToolkits }) => {
    assertWorker(workerSecret);
    const intent = await ctx.db.get(id);
    if (!intent || intent.status !== "pending") return { resumed: false };
    await ctx.db.patch(id, { connectedToolkits });
    if (!covers(connectedToolkits, intent.requiredToolkits)) return { resumed: false };
    const handle = `resume:${id}`;
    const existing = await ctx.db
      .query("messages")
      .withIndex("by_handle", (q) => q.eq("handle", handle))
      .first();
    if (!existing) {
      await ctx.db.insert("messages", {
        handle,
        userId: intent.userId,
        channel: intent.channel,
        replyTarget: intent.replyTarget,
        userNumber: intent.userNumber,
        text: intent.taskText,
        status: "queued",
        receivedAt: Date.now(),
      });
    }
    await ctx.db.patch(id, { status: "resumed", resumedAt: Date.now() });
    return { resumed: true };
  },
});

export const expireIntent = mutation({
  args: { workerSecret: v.string(), id: v.id("connectIntents") },
  returns: v.null(),
  handler: async (ctx, { workerSecret, id }) => {
    assertWorker(workerSecret);
    const intent = await ctx.db.get(id);
    if (intent && intent.status === "pending") await ctx.db.patch(id, { status: "expired" });
    return null;
  },
});
