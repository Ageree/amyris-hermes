import { mutation } from "./_generated/server";
import { v } from "convex/values";
import { assertWorker, tierValidator } from "./lib/auth";
import { writeEntitlement } from "./billing/grant";

// ---------------------------------------------------------------------------
// admin.ts — operator/worker-facing maintenance (WORKER_SECRET gate, A4). This is
// NOT under app/ and never uses getAuthUserId — it's the privileged side. Used to
// manually grant a paid tier for testing before the billing provider is live
// (design §2.2: "admin.ts:grantTier — WORKER_SECRET-gated manual paid grant").
// Entitlement writes still funnel through the single writer (billing/grant).
// ---------------------------------------------------------------------------
export const grantTier = mutation({
  args: {
    workerSecret: v.string(),
    userId: v.id("users"),
    tier: tierValidator,
    quotaOverride: v.optional(v.number()),
  },
  returns: v.null(),
  handler: async (ctx, { workerSecret, userId, tier, quotaOverride }) => {
    assertWorker(workerSecret);
    await writeEntitlement(ctx, {
      userId,
      tier,
      status: "active",
      source: "stub",
      quotaOverride,
    });
    return null;
  },
});
