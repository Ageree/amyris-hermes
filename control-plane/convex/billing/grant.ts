import { internalMutation, type MutationCtx } from "../_generated/server";
import { v } from "convex/values";
import type { Id } from "../_generated/dataModel";
import { internal } from "../_generated/api";
import { TIERS, OPERATOR_QUOTA, PERIOD_MS, tierValidator } from "./tiers";

// ---------------------------------------------------------------------------
// applyEntitlement — THE single entitlement-writing primitive (design §5/§6).
// Reused by signup (auth.ts createOrUpdateUser), the admin manual grant
// (admin.ts:grantTier), the tier picker (app/tiers:chooseTier for the free path),
// and the FUTURE billing webhook. Centralizing the write means quota/period/mirror
// logic lives in exactly one place and can never disagree across call sites.
//
// `writeEntitlement` is a plain async helper so callers that are ALREADY inside a
// mutation (the auth callback) can write in the SAME transaction without a nested
// ctx.runMutation. `applyEntitlement` is the internalMutation wrapper for callers
// that need a standalone function reference.
// ---------------------------------------------------------------------------

const grantArgs = {
  userId: v.id("users"),
  tier: tierValidator,
  status: v.union(
    v.literal("active"),
    v.literal("past_due"),
    v.literal("canceled"),
  ),
  source: v.union(
    v.literal("stub"),
    v.literal("paddle"),
    v.literal("stripe"),
    v.literal("lemonsqueezy"),
  ),
  // Operator override: -1 => unlimited. Omit for normal tier quotas.
  quotaOverride: v.optional(v.number()),
  providerCustomerId: v.optional(v.string()),
  providerSubId: v.optional(v.string()),
};

export async function writeEntitlement(
  ctx: MutationCtx,
  args: {
    userId: Id<"users">;
    tier: "free" | "pro" | "max";
    status: "active" | "past_due" | "canceled";
    source: "stub" | "paddle" | "stripe" | "lemonsqueezy";
    quotaOverride?: number;
    providerCustomerId?: string;
    providerSubId?: string;
  },
): Promise<void> {
  const now = Date.now();
  const quota = args.quotaOverride ?? TIERS[args.tier].msgQuota;

  const existing = await ctx.db
    .query("entitlements")
    .withIndex("by_user", (q: any) => q.eq("userId", args.userId))
    .first();

  if (existing) {
    // Keep the running counter within the current period; reset only when the
    // window has already rolled (so a mid-period tier change doesn't refund usage
    // or wipe the meter). A fresh period resets msgUsed -> 0.
    const periodValid = existing.periodEnd > now;
    await ctx.db.patch(existing._id, {
      tier: args.tier,
      status: args.status,
      msgQuota: quota,
      source: args.source,
      providerCustomerId: args.providerCustomerId ?? existing.providerCustomerId,
      providerSubId: args.providerSubId ?? existing.providerSubId,
      ...(periodValid
        ? {}
        : { periodStart: now, periodEnd: now + PERIOD_MS, msgUsed: 0 }),
      updatedAt: now,
    });
  } else {
    await ctx.db.insert("entitlements", {
      userId: args.userId,
      tier: args.tier,
      status: args.status,
      msgQuota: quota,
      msgUsed: 0,
      periodStart: now,
      periodEnd: now + PERIOD_MS,
      source: args.source,
      providerCustomerId: args.providerCustomerId,
      providerSubId: args.providerSubId,
      updatedAt: now,
    });
  }

  // Denormalized mirror on the user row for fast tier reads (dashboard/UI).
  const u = await ctx.db.get(args.userId);
  if (u && u.tier !== args.tier) {
    await ctx.db.patch(args.userId, { tier: args.tier });
  }
}

export const applyEntitlement = internalMutation({
  args: grantArgs,
  returns: v.null(),
  handler: async (ctx, args) => {
    await writeEntitlement(ctx, args);
    return null;
  },
});

// Convenience used by the signup callback: operator => max + unlimited, else free.
export async function grantSignupEntitlement(
  ctx: MutationCtx,
  userId: Id<"users">,
  isOperator: boolean,
): Promise<void> {
  await writeEntitlement(ctx, {
    userId,
    tier: isOperator ? "max" : "free",
    status: "active",
    source: "stub",
    quotaOverride: isOperator ? OPERATOR_QUOTA : undefined,
  });
}

// ---------------------------------------------------------------------------
// rollExpiredPeriods (design §6) — cron-driven safety net that resets the rolling
// quota window for entitlements whose period has ended. checkAndReserve ALSO
// self-rolls on read, so this only matters for users who are idle across a period
// boundary (their dashboard shows a fresh window without waiting for a turn).
// Paginated: take(ROLL_BATCH) per run; rolled rows get a FUTURE periodEnd so they
// drop out of the by_periodEnd<=now scan, and the function self-reschedules until
// a short batch — bounding reads/writes per transaction (design "too many writes").
// ---------------------------------------------------------------------------
const ROLL_BATCH = 500;

export const rollExpiredPeriods = internalMutation({
  args: {},
  returns: v.object({ rolled: v.number(), more: v.boolean() }),
  handler: async (ctx) => {
    const now = Date.now();
    const due = await ctx.db
      .query("entitlements")
      .withIndex("by_periodEnd", (q) => q.lte("periodEnd", now))
      .take(ROLL_BATCH);
    for (const e of due) {
      // Unlimited (operator) never needs a quota reset, but rolling the window is
      // harmless and keeps periodEnd in the future so it leaves the scan.
      await ctx.db.patch(e._id, {
        periodStart: now,
        periodEnd: now + PERIOD_MS,
        msgUsed: 0,
        updatedAt: now,
      });
    }
    const more = due.length === ROLL_BATCH;
    if (more) {
      await ctx.scheduler.runAfter(0, internal.billing.grant.rollExpiredPeriods, {});
    }
    return { rolled: due.length, more };
  },
});
