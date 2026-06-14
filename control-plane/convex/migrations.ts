import { internalMutation, internalQuery } from "./_generated/server";
import { v } from "convex/values";
import { OPERATOR_EMAIL } from "./auth";
import { writeEntitlement } from "./billing/grant";

// ---------------------------------------------------------------------------
// One-off operator migration (design §10 step 5). Makes the operator (user #0) a
// first-class tenant WITHOUT touching his live path:
//   - find-or-create his users row (deduped by email; a later real sign-in links
//     to THIS row), force isOperator + max/unlimited entitlement,
//   - a VERIFIED (imessage, <operator number>) channelBinding — the tenant
//     resolver (A1) for him,
//   - tag every existing operator message/connectIntent with userId/channel/
//     replyTarget (the additive columns), and delete stray "+test*" intents.
//
// Idempotent: re-running only patches rows still missing the columns and never
// duplicates the user/binding. Run via `npx convex run migrations:backfillOperator`
// (admin-gated by the deploy key — internal, no client/worker secret on the CLI).
//
// IMPORTANT (liveness): this tags only EXISTING (terminal) rows. The operator's
// NEW messages keep flowing through the legacy claimNext path (userId===undefined)
// until the M6 container cutover to claimNextForUser — so his assistant never goes
// dark. countMessagesMissingUserId is checked right after this runs (== 0).
// ---------------------------------------------------------------------------

const OPERATOR_NUMBER = process.env.ALLOWED_USER_NUMBER ?? "+79217818876";

export const backfillOperator = internalMutation({
  args: {},
  returns: v.object({
    userId: v.id("users"),
    userCreated: v.boolean(),
    bindingCreated: v.boolean(),
    messagesPatched: v.number(),
    intentsPatched: v.number(),
    intentsDeleted: v.number(),
    missingAfter: v.number(),
  }),
  handler: async (ctx) => {
    const now = Date.now();

    // 1. Operator user — find by email, else create. Force operator flags.
    const existingUser = await ctx.db
      .query("users")
      .withIndex("email", (q) => q.eq("email", OPERATOR_EMAIL))
      .first();
    let userId: any;
    let userCreated = false;
    if (existingUser) {
      userId = existingUser._id;
      if (existingUser.isOperator !== true || existingUser.tier !== "max") {
        await ctx.db.patch(userId, { isOperator: true, tier: "max" });
      }
    } else {
      userId = await ctx.db.insert("users", {
        email: OPERATOR_EMAIL,
        isOperator: true,
        tier: "max",
        createdAt: now,
      });
      userCreated = true;
    }
    // max + unlimited entitlement (single writer).
    await writeEntitlement(ctx, {
      userId,
      tier: "max",
      status: "active",
      source: "stub",
      quotaOverride: -1,
    });

    // 2. Verified iMessage binding (the tenant resolver for the operator).
    const existingBinding = await ctx.db
      .query("channelBindings")
      .withIndex("by_address", (q) =>
        q.eq("channel", "imessage").eq("address", OPERATOR_NUMBER),
      )
      .first();
    let bindingCreated = false;
    if (existingBinding) {
      if (existingBinding.userId !== userId || !existingBinding.verified) {
        await ctx.db.patch(existingBinding._id, { userId, verified: true });
      }
    } else {
      await ctx.db.insert("channelBindings", {
        userId,
        channel: "imessage",
        address: OPERATOR_NUMBER,
        verified: true,
        createdAt: now,
      });
      bindingCreated = true;
    }

    // 3. Tag existing operator messages (index-scoped by userNumber).
    const msgs = await ctx.db
      .query("messages")
      .withIndex("by_user", (q) => q.eq("userNumber", OPERATOR_NUMBER))
      .collect();
    let messagesPatched = 0;
    for (const m of msgs) {
      const patch: Record<string, unknown> = {};
      if (m.userId === undefined) patch.userId = userId;
      if (m.channel === undefined) patch.channel = "imessage";
      if (m.replyTarget === undefined) patch.replyTarget = m.userNumber;
      if (Object.keys(patch).length > 0) {
        await ctx.db.patch(m._id, patch);
        messagesPatched++;
      }
    }

    // 4. connectIntents — patch operator's, delete "+test*" strays. Tiny table
    // (≤ a few rows) so a bounded full scan is fine; no userNumber index needed.
    const intents = await ctx.db.query("connectIntents").collect();
    let intentsPatched = 0;
    let intentsDeleted = 0;
    for (const it of intents) {
      if (it.userNumber === OPERATOR_NUMBER) {
        const patch: Record<string, unknown> = {};
        if (it.userId === undefined) patch.userId = userId;
        if (it.channel === undefined) patch.channel = "imessage";
        if (it.replyTarget === undefined) patch.replyTarget = it.userNumber;
        if (Object.keys(patch).length > 0) {
          await ctx.db.patch(it._id, patch);
          intentsPatched++;
        }
      } else if (it.userNumber.startsWith("+test")) {
        await ctx.db.delete(it._id);
        intentsDeleted++;
      }
    }

    // 5. Recount operator messages still missing userId (expect 0).
    const after = await ctx.db
      .query("messages")
      .withIndex("by_user", (q) => q.eq("userNumber", OPERATOR_NUMBER))
      .collect();
    let missingAfter = 0;
    for (const m of after) if (m.userId === undefined) missingAfter++;

    return {
      userId,
      userCreated,
      bindingCreated,
      messagesPatched,
      intentsPatched,
      intentsDeleted,
      missingAfter,
    };
  },
});

// Audit helper (design §10 verify): operator messages still lacking userId.
export const countMessagesMissingUserId = internalQuery({
  args: { userNumber: v.optional(v.string()) },
  returns: v.object({ missing: v.number(), total: v.number() }),
  handler: async (ctx, { userNumber }) => {
    const phone = userNumber ?? OPERATOR_NUMBER;
    const rows = await ctx.db
      .query("messages")
      .withIndex("by_user", (q) => q.eq("userNumber", phone))
      .collect();
    let missing = 0;
    for (const m of rows) if (m.userId === undefined) missing++;
    return { missing, total: rows.length };
  },
});

// Audit helper: exactly-one-verified-imessage-binding check for the operator.
export const operatorBindingStatus = internalQuery({
  args: {},
  returns: v.object({
    verifiedImessageBindings: v.number(),
    userId: v.union(v.id("users"), v.null()),
  }),
  handler: async (ctx) => {
    const binding = await ctx.db
      .query("channelBindings")
      .withIndex("by_address", (q) =>
        q.eq("channel", "imessage").eq("address", OPERATOR_NUMBER),
      )
      .first();
    return {
      verifiedImessageBindings: binding && binding.verified ? 1 : 0,
      userId: binding?.userId ?? null,
    };
  },
});
