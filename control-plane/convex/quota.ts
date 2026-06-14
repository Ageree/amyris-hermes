import { mutation } from "./_generated/server";
import { v } from "convex/values";
import { assertWorker, channelValidator, tierValidator } from "./lib/auth";
import { PERIOD_MS } from "./billing/tiers";
import type { MutationCtx } from "./_generated/server";
import type { Doc } from "./_generated/dataModel";

// ---------------------------------------------------------------------------
// Quota gate (design §6). WORKER_SECRET-gated (A4) — called by the brain worker
// right AFTER claim and BEFORE any model call, so an over-quota turn costs $0.
//   - checkAndReserve: atomic read → self-roll expired period → reserve one unit
//     (msgUsed++) or deny. Atomicity (one mutation txn) stops two concurrent
//     turns from both consuming the last unit.
//   - recordUsage: append one usageEvents audit row after a turn (dashboard).
//   - releaseReserve: refund a reserved unit on a HARD turn failure.
// The worker FAILS OPEN on a Convex *error* (a control-plane hiccup must not lock
// paying users out) but FAILS CLOSED on a clean over-quota (friendly upsell).
// Operator / unlimited (msgQuota < 0) is always allowed and never incremented.
// ---------------------------------------------------------------------------

// Self-roll an entitlement whose 30-day window has already ended, even if the
// cron hasn't fired yet. Returns the (possibly patched) live counters.
async function rollIfExpired(
  ctx: MutationCtx,
  e: Doc<"entitlements">,
  now: number,
): Promise<{ msgUsed: number; periodStart: number; periodEnd: number }> {
  if (e.periodEnd > now) {
    return { msgUsed: e.msgUsed, periodStart: e.periodStart, periodEnd: e.periodEnd };
  }
  const periodStart = now;
  const periodEnd = now + PERIOD_MS;
  await ctx.db.patch(e._id, { periodStart, periodEnd, msgUsed: 0, updatedAt: now });
  return { msgUsed: 0, periodStart, periodEnd };
}

export const checkAndReserve = mutation({
  args: { workerSecret: v.string(), userId: v.id("users") },
  returns: v.object({
    allowed: v.boolean(),
    tier: tierValidator,
    remaining: v.number(), // -1 => unlimited
    msgQuota: v.number(),
    periodEnd: v.number(),
    reason: v.optional(
      v.union(
        v.literal("over_quota"),
        v.literal("canceled"),
        v.literal("no_entitlement"),
      ),
    ),
  }),
  handler: async (ctx, { workerSecret, userId }) => {
    assertWorker(workerSecret);
    const now = Date.now();
    const e = await ctx.db
      .query("entitlements")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();

    // No entitlement at all → deny (fail closed). Signup always grants one, so
    // this only fires for a malformed/legacy user; the worker treats a clean deny
    // as "blocked", a thrown error as "fail open".
    if (!e) {
      return {
        allowed: false,
        tier: "free" as const,
        remaining: 0,
        msgQuota: 0,
        periodEnd: 0,
        reason: "no_entitlement" as const,
      };
    }

    // Unlimited (operator) — always allow, never increment.
    if (e.msgQuota < 0) {
      return { allowed: true, tier: e.tier, remaining: -1, msgQuota: e.msgQuota, periodEnd: e.periodEnd };
    }

    // A canceled plan blocks (past_due is allowed during grace).
    if (e.status === "canceled") {
      return {
        allowed: false,
        tier: e.tier,
        remaining: Math.max(0, e.msgQuota - e.msgUsed),
        msgQuota: e.msgQuota,
        periodEnd: e.periodEnd,
        reason: "canceled" as const,
      };
    }

    const rolled = await rollIfExpired(ctx, e, now);
    if (rolled.msgUsed >= e.msgQuota) {
      return {
        allowed: false,
        tier: e.tier,
        remaining: 0,
        msgQuota: e.msgQuota,
        periodEnd: rolled.periodEnd,
        reason: "over_quota" as const,
      };
    }

    // Reserve one unit atomically (this whole handler is one transaction).
    const msgUsed = rolled.msgUsed + 1;
    await ctx.db.patch(e._id, { msgUsed, updatedAt: now });
    return {
      allowed: true,
      tier: e.tier,
      remaining: e.msgQuota - msgUsed,
      msgQuota: e.msgQuota,
      periodEnd: rolled.periodEnd,
    };
  },
});

export const recordUsage = mutation({
  args: {
    workerSecret: v.string(),
    userId: v.id("users"),
    messageId: v.optional(v.id("messages")),
    lane: v.optional(v.string()),
    channel: v.optional(channelValidator),
    units: v.optional(v.number()),
    tokensIn: v.optional(v.number()),
    tokensOut: v.optional(v.number()),
  },
  returns: v.null(),
  handler: async (ctx, args) => {
    assertWorker(args.workerSecret);
    const now = Date.now();
    const e = await ctx.db
      .query("entitlements")
      .withIndex("by_user", (q) => q.eq("userId", args.userId))
      .first();
    await ctx.db.insert("usageEvents", {
      userId: args.userId,
      messageId: args.messageId,
      kind: "turn",
      lane: args.lane,
      channel: args.channel,
      units: args.units ?? 1,
      tokensIn: args.tokensIn,
      tokensOut: args.tokensOut,
      periodStart: e?.periodStart ?? now,
      at: now,
    });
    return null;
  },
});

export const releaseReserve = mutation({
  args: { workerSecret: v.string(), userId: v.id("users") },
  returns: v.object({ released: v.boolean() }),
  handler: async (ctx, { workerSecret, userId }) => {
    assertWorker(workerSecret);
    const e = await ctx.db
      .query("entitlements")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    // Only refund a real reservation; never go below zero, never touch unlimited.
    if (!e || e.msgQuota < 0 || e.msgUsed <= 0) return { released: false };
    await ctx.db.patch(e._id, { msgUsed: e.msgUsed - 1, updatedAt: Date.now() });
    return { released: true };
  },
});
