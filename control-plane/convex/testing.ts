import { mutation } from "./_generated/server";
import { v } from "convex/values";
import { assertWorker } from "./lib/auth";

// ---------------------------------------------------------------------------
// TEST-ONLY seeding helpers for the convex_e2e integration tier
// (lab/tests/test_messages_claim_by_user.py). DOUBLE-GATED so this is inert in
// prod: it requires BOTH the WORKER_SECRET argument AND the deployment env var
// ALLOW_TEST_SEED==="1". Prod (adept-dragon-928) never sets ALLOW_TEST_SEED, so
// these throw there; only the dev deployment enables them. They let the test
// seed two REAL tenants over the public HTTP API (the worker's exact path) so
// claimNextForUser / recentForUser tenant isolation is proven against the live
// by_status_user / by_userId indexes — something mocks cannot catch.
//
// FOLLOW-UP (M7 hardening): remove this module, or move it behind a separate
// throwaway deployment, once the e2e harness has a dedicated dev deployment.
// ---------------------------------------------------------------------------
function assertTestMode() {
  if (process.env.ALLOW_TEST_SEED !== "1") {
    throw new Error(
      "test seeding disabled (set ALLOW_TEST_SEED=1 on a dev deployment only)",
    );
  }
}

// Create two throwaway tenants, each with one queued message. Handles use a
// "tt-" prefix (NOT "e2e"/"resume:") so recentForUser does NOT skip them —
// throwaway-user memory is isolated by userId, so this never touches the
// operator's conversation memory.
export const seedTwoTenants = mutation({
  args: { workerSecret: v.string(), tag: v.string() },
  returns: v.object({
    userA: v.id("users"),
    userB: v.id("users"),
    msgA: v.id("messages"),
    msgB: v.id("messages"),
    textA: v.string(),
    textB: v.string(),
  }),
  handler: async (ctx, { workerSecret, tag }) => {
    assertWorker(workerSecret);
    assertTestMode();
    const now = Date.now();
    const userA = await ctx.db.insert("users", {
      email: `tt-${tag}-A@test.invalid`, isOperator: false, createdAt: now,
    });
    const userB = await ctx.db.insert("users", {
      email: `tt-${tag}-B@test.invalid`, isOperator: false, createdAt: now,
    });
    const textA = `tt ${tag} A claim-me`;
    const textB = `tt ${tag} B leave-me`;
    const msgA = await ctx.db.insert("messages", {
      handle: `tt-${tag}-A`, userId: userA, channel: "imessage",
      replyTarget: "+1A", userNumber: "+1A", text: textA,
      status: "queued", receivedAt: now,
    });
    const msgB = await ctx.db.insert("messages", {
      handle: `tt-${tag}-B`, userId: userB, channel: "imessage",
      replyTarget: "+1B", userNumber: "+1B", text: textB,
      status: "queued", receivedAt: now + 1,
    });
    return { userA, userB, msgA, msgB, textA, textB };
  },
});

// Delete two throwaway tenants and all their messages (index-scoped, bounded).
export const cleanupTenants = mutation({
  args: { workerSecret: v.string(), userA: v.id("users"), userB: v.id("users") },
  returns: v.null(),
  handler: async (ctx, { workerSecret, userA, userB }) => {
    assertWorker(workerSecret);
    assertTestMode();
    for (const uid of [userA, userB]) {
      const msgs = await ctx.db
        .query("messages")
        .withIndex("by_userId", (q) => q.eq("userId", uid))
        .collect();
      for (const m of msgs) await ctx.db.delete(m._id);
      const u = await ctx.db.get(uid);
      if (u) await ctx.db.delete(uid);
    }
    return null;
  },
});
