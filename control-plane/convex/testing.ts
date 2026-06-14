import { mutation } from "./_generated/server";
import { v } from "convex/values";
import { assertWorker, channelValidator, tierValidator } from "./lib/auth";
import { PERIOD_MS } from "./billing/tiers";
import {
  issuePairingTokenImpl,
  redeemTelegramImpl,
  redeemImessageImpl,
} from "./pairing";

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

// ---------------------------------------------------------------------------
// Pairing test wrappers (M4, convex_e2e tier — test_pairing.py). Double-gated
// like the seeders (WORKER_SECRET + ALLOW_TEST_SEED), so they're inert in prod.
// They drive the EXACT pairing impls over HTTP to prove single-use / expiry /
// wrong-channel / cross-user-reject against the live indexes — properties mocks
// can't catch. testExpirePairing back-dates a token to simulate TTL elapse.
// ---------------------------------------------------------------------------
const redeemResult = v.object({
  ok: v.boolean(),
  userId: v.union(v.id("users"), v.null()),
  reason: v.optional(v.string()),
  idempotent: v.optional(v.boolean()),
});

export const testIssuePairing = mutation({
  args: { workerSecret: v.string(), userId: v.id("users"), channel: channelValidator },
  returns: v.object({
    token: v.string(),
    code: v.string(),
    expiresAt: v.number(),
    channel: channelValidator,
  }),
  handler: async (ctx, { workerSecret, userId, channel }) => {
    assertWorker(workerSecret);
    assertTestMode();
    return await issuePairingTokenImpl(ctx, userId, channel);
  },
});

export const testRedeemTelegram = mutation({
  args: { workerSecret: v.string(), token: v.string(), address: v.string() },
  returns: redeemResult,
  handler: async (ctx, { workerSecret, token, address }) => {
    assertWorker(workerSecret);
    assertTestMode();
    return await redeemTelegramImpl(ctx, token, address);
  },
});

export const testRedeemImessage = mutation({
  args: { workerSecret: v.string(), code: v.string(), address: v.string() },
  returns: redeemResult,
  handler: async (ctx, { workerSecret, code, address }) => {
    assertWorker(workerSecret);
    assertTestMode();
    return await redeemImessageImpl(ctx, code, address);
  },
});

// Back-date a token's expiry (and re-activate it) to simulate TTL elapse without
// a real 15-minute wait. Looks up by token OR code.
export const testExpirePairing = mutation({
  args: { workerSecret: v.string(), token: v.optional(v.string()), code: v.optional(v.string()) },
  returns: v.object({ ok: v.boolean() }),
  handler: async (ctx, { workerSecret, token, code }) => {
    assertWorker(workerSecret);
    assertTestMode();
    const row = token
      ? await ctx.db.query("pairingTokens").withIndex("by_token", (q) => q.eq("token", token)).first()
      : code
        ? await ctx.db.query("pairingTokens").withIndex("by_code", (q) => q.eq("code", code)).first()
        : null;
    if (!row) return { ok: false };
    await ctx.db.patch(row._id, { status: "active", expiresAt: Date.now() - 1000 });
    return { ok: true };
  },
});

// Set/replace a throwaway user's entitlement deterministically so the quota e2e
// can drive over_quota / canceled without 100 real reserves. Double-gated.
export const testSetEntitlement = mutation({
  args: {
    workerSecret: v.string(),
    userId: v.id("users"),
    tier: tierValidator,
    msgQuota: v.number(),
    msgUsed: v.number(),
    status: v.optional(
      v.union(v.literal("active"), v.literal("past_due"), v.literal("canceled")),
    ),
    periodEnd: v.optional(v.number()),
  },
  returns: v.id("entitlements"),
  handler: async (ctx, { workerSecret, userId, tier, msgQuota, msgUsed, status, periodEnd }) => {
    assertWorker(workerSecret);
    assertTestMode();
    const now = Date.now();
    const existing = await ctx.db
      .query("entitlements")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .first();
    const fields = {
      tier,
      status: status ?? ("active" as const),
      msgQuota,
      msgUsed,
      periodStart: now,
      periodEnd: periodEnd ?? now + PERIOD_MS,
      source: "stub" as const,
      updatedAt: now,
    };
    if (existing) {
      await ctx.db.patch(existing._id, fields);
      return existing._id;
    }
    return await ctx.db.insert("entitlements", { userId, ...fields });
  },
});

// Delete two throwaway tenants and all their messages (index-scoped, bounded).
export const cleanupTenants = mutation({
  args: { workerSecret: v.string(), userA: v.id("users"), userB: v.id("users") },
  returns: v.null(),
  handler: async (ctx, { workerSecret, userA, userB }) => {
    assertWorker(workerSecret);
    assertTestMode();
    // SAFETY: only ever delete THROWAWAY test users (tt-*@test.invalid). Even with
    // ALLOW_TEST_SEED on, a wrong/foreign id (incl. the operator) is skipped — this
    // can never nuke a real tenant.
    const isThrowaway = (email: string | undefined) =>
      /^tt-.*@test\.invalid$/.test(email ?? "");
    for (const uid of [userA, userB]) {
      const target = await ctx.db.get(uid);
      if (!target || !isThrowaway(target.email)) continue;
      const msgs = await ctx.db
        .query("messages")
        .withIndex("by_userId", (q) => q.eq("userId", uid))
        .collect();
      for (const m of msgs) await ctx.db.delete(m._id);
      // Also clean channelBindings + pairingTokens a redeem smoke-test may have created.
      const binds = await ctx.db
        .query("channelBindings")
        .withIndex("by_user", (q) => q.eq("userId", uid))
        .collect();
      for (const b of binds) await ctx.db.delete(b._id);
      for (const ch of ["imessage", "telegram"] as const) {
        const toks = await ctx.db
          .query("pairingTokens")
          .withIndex("by_user_channel", (q) => q.eq("userId", uid).eq("channel", ch))
          .collect();
        for (const t of toks) await ctx.db.delete(t._id);
      }
      // Entitlement + usage rows a quota test created.
      const ents = await ctx.db
        .query("entitlements")
        .withIndex("by_user", (q) => q.eq("userId", uid))
        .collect();
      for (const e of ents) await ctx.db.delete(e._id);
      const usage = await ctx.db
        .query("usageEvents")
        .withIndex("by_user_at", (q) => q.eq("userId", uid))
        .collect();
      for (const ev of usage) await ctx.db.delete(ev._id);
      await ctx.db.delete(uid);
    }
    return null;
  },
});
