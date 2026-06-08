import { mutation, internalMutation, query } from "./_generated/server";
import { v } from "convex/values";

// Shared-secret gate for the worker (brain) facing functions. The brain passes
// WORKER_SECRET on every call; without it these public functions reject. (The
// HTTP webhook uses its own path-token secret — see http.ts.)
function assertWorker(provided: string) {
  const expected = process.env.WORKER_SECRET ?? "";
  if (!expected || provided !== expected) {
    throw new Error("unauthorized worker");
  }
}

// Called only by the HTTP webhook (internal — not publicly callable).
// Idempotent on Sendblue's message_handle.
export const enqueue = internalMutation({
  args: {
    handle: v.string(),
    userNumber: v.string(),
    text: v.string(),
    mediaUrl: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("messages")
      .withIndex("by_handle", (q) => q.eq("handle", args.handle))
      .first();
    if (existing) return existing._id; // duplicate delivery — ignore
    return await ctx.db.insert("messages", {
      ...args,
      status: "queued",
      receivedAt: Date.now(),
    });
  },
});

// Brain polls this: atomically claim the oldest queued message.
export const claimNext = mutation({
  args: { workerSecret: v.string() },
  handler: async (ctx, { workerSecret }) => {
    assertWorker(workerSecret);
    const next = await ctx.db
      .query("messages")
      .withIndex("by_status", (q) => q.eq("status", "queued"))
      .order("asc")
      .first();
    if (!next) return null;
    await ctx.db.patch(next._id, { status: "processing", claimedAt: Date.now() });
    return {
      id: next._id,
      handle: next.handle,
      userNumber: next.userNumber,
      text: next.text,
      mediaUrl: next.mediaUrl ?? null,
    };
  },
});

export const complete = mutation({
  args: { workerSecret: v.string(), id: v.id("messages"), reply: v.string() },
  handler: async (ctx, { workerSecret, id, reply }) => {
    assertWorker(workerSecret);
    await ctx.db.patch(id, { status: "done", reply, completedAt: Date.now() });
  },
});

export const fail = mutation({
  args: { workerSecret: v.string(), id: v.id("messages"), error: v.string() },
  handler: async (ctx, { workerSecret, id, error }) => {
    assertWorker(workerSecret);
    await ctx.db.patch(id, { status: "error", error, completedAt: Date.now() });
  },
});

// Conversation memory: the worker fetches a user's recent completed turns and
// splices them into the prompt so the (otherwise stateless) assistant can follow
// a conversation. PII-gated by the worker secret. Returns chronological (oldest
// first) {text, reply} pairs, skipping synthetic auto-resume / e2e messages and
// any turn missing text or reply. Overfetches then trims because the status
// filter + skips can drop rows.
export const recentForUser = query({
  args: {
    workerSecret: v.string(),
    userNumber: v.string(),
    limit: v.number(),
  },
  handler: async (ctx, { workerSecret, userNumber, limit }) => {
    assertWorker(workerSecret);
    const n = Math.max(1, Math.min(20, Math.floor(limit)));
    const rows = await ctx.db
      .query("messages")
      .withIndex("by_user", (q) => q.eq("userNumber", userNumber))
      .order("desc")
      .filter((q) => q.eq(q.field("status"), "done"))
      .take(n * 3);
    const out: { text: string; reply: string; receivedAt: number }[] = [];
    for (const m of rows) {
      if (m.handle.startsWith("resume:") || m.handle.startsWith("e2e")) continue;
      if (!m.text || !m.reply) continue;
      out.push({ text: m.text, reply: m.reply, receivedAt: m.receivedAt });
      if (out.length >= n) break;
    }
    out.reverse(); // chronological: oldest first, so it reads as a transcript
    return out;
  },
});

// Operational read-only view (no PII gate needed for counts; gate full rows).
export const stats = query({
  args: {},
  handler: async (ctx) => {
    const all = await ctx.db.query("messages").collect();
    const by: Record<string, number> = {};
    for (const m of all) by[m.status] = (by[m.status] ?? 0) + 1;
    return { total: all.length, ...by };
  },
});
