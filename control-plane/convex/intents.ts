import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

function assertWorker(provided: string) {
  const expected = process.env.WORKER_SECRET ?? "";
  if (!expected || provided !== expected) throw new Error("unauthorized worker");
}

const covers = (have: string[], need: string[]) => need.every((t) => have.includes(t));

// Brain (pending.py) records the intent when it texts a connect-link.
// Light dedupe: an identical still-pending intent is returned, not duplicated.
export const addIntent = mutation({
  args: {
    workerSecret: v.string(),
    userNumber: v.string(),
    taskText: v.string(),
    requiredToolkits: v.array(v.string()),
  },
  handler: async (ctx, { workerSecret, userNumber, taskText, requiredToolkits }) => {
    assertWorker(workerSecret);
    const pending = await ctx.db
      .query("connectIntents")
      .withIndex("by_status", (q) => q.eq("status", "pending"))
      .collect();
    const dup = pending.find(
      (p) => p.userNumber === userNumber && p.taskText === taskText &&
        p.requiredToolkits.slice().sort().join(",") === requiredToolkits.slice().sort().join(","),
    );
    if (dup) return dup._id;
    return await ctx.db.insert("connectIntents", {
      userNumber, taskText, requiredToolkits, connectedToolkits: [],
      status: "pending", createdAt: Date.now(),
    });
  },
});

// Worker polls this each tick.
export const listPending = query({
  args: { workerSecret: v.string() },
  handler: async (ctx, { workerSecret }) => {
    assertWorker(workerSecret);
    const rows = await ctx.db
      .query("connectIntents")
      .withIndex("by_status", (q) => q.eq("status", "pending"))
      .collect();
    return rows.map((r) => ({
      id: r._id, userNumber: r.userNumber, taskText: r.taskText,
      requiredToolkits: r.requiredToolkits, connectedToolkits: r.connectedToolkits,
      createdAt: r.createdAt,
    }));
  },
});

// Worker reports the currently-ACTIVE toolkits. If they cover the requirement,
// mark resumed and enqueue a synthetic resume message (idempotent by handle).
export const resolveIntent = mutation({
  args: {
    workerSecret: v.string(),
    id: v.id("connectIntents"),
    connectedToolkits: v.array(v.string()),
  },
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
        handle, userNumber: intent.userNumber, text: intent.taskText,
        status: "queued", receivedAt: Date.now(),
      });
    }
    await ctx.db.patch(id, { status: "resumed", resumedAt: Date.now() });
    return { resumed: true };
  },
});

export const expireIntent = mutation({
  args: { workerSecret: v.string(), id: v.id("connectIntents") },
  handler: async (ctx, { workerSecret, id }) => {
    assertWorker(workerSecret);
    const intent = await ctx.db.get(id);
    if (intent && intent.status === "pending") await ctx.db.patch(id, { status: "expired" });
  },
});
