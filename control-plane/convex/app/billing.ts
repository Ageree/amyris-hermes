import { query } from "../_generated/server";
import { v } from "convex/values";
import { requireUser } from "./authGate";
import { tierValidator } from "../billing/tiers";
import { channelValidator } from "../lib/auth";

// ---------------------------------------------------------------------------
// app/billing (design §6) — the dashboard usage surface. getAuthUserId-gated (A4);
// reads ONLY the caller's own entitlement (entitlements.by_user) and usageEvents
// (by_user_at) — index-only, no row-scan predicate, no client id. Never returns another
// tenant's usage. app/usage.ts re-exports these so the existing dashboard import
// (api.app.usage.myUsage) keeps working unchanged.
// ---------------------------------------------------------------------------

// myUsage — current entitlement snapshot for the gauge (used/quota/remaining).
export const myUsage = query({
  args: {},
  returns: v.union(
    v.null(),
    v.object({
      tier: tierValidator,
      status: v.union(
        v.literal("active"),
        v.literal("past_due"),
        v.literal("canceled"),
      ),
      msgUsed: v.number(),
      msgQuota: v.number(),
      remaining: v.number(), // -1 => unlimited (operator)
      unlimited: v.boolean(),
      periodStart: v.number(),
      periodEnd: v.number(),
    }),
  ),
  handler: async (ctx) => {
    const userId = await requireUser(ctx);
    const e = await ctx.db
      .query("entitlements")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    if (!e) return null;
    const unlimited = e.msgQuota < 0;
    return {
      tier: e.tier,
      status: e.status,
      msgUsed: e.msgUsed,
      msgQuota: e.msgQuota,
      remaining: unlimited ? -1 : Math.max(0, e.msgQuota - e.msgUsed),
      unlimited,
      periodStart: e.periodStart,
      periodEnd: e.periodEnd,
    };
  },
});

// myUsageTimeline — recent per-turn meter events for the activity panel.
export const myUsageTimeline = query({
  args: { limit: v.optional(v.number()) },
  returns: v.array(
    v.object({
      at: v.number(),
      lane: v.union(v.string(), v.null()),
      channel: v.union(channelValidator, v.null()),
      units: v.number(),
    }),
  ),
  handler: async (ctx, { limit }) => {
    const userId = await requireUser(ctx);
    const n = Math.max(1, Math.min(100, Math.floor(limit ?? 30)));
    const rows = await ctx.db
      .query("usageEvents")
      .withIndex("by_user_at", (q) => q.eq("userId", userId))
      .order("desc")
      .take(n);
    return rows.map((r) => ({
      at: r.at,
      lane: r.lane ?? null,
      channel: r.channel ?? null,
      units: r.units,
    }));
  },
});
