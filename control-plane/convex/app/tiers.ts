import { query, mutation } from "../_generated/server";
import { v } from "convex/values";
import { requireUser } from "./authGate";
import { tierValidator, publicTiers } from "../billing/tiers";
import { channelValidator } from "../lib/auth";
import { writeEntitlement } from "../billing/grant";

// ---------------------------------------------------------------------------
// app/tiers — the tier picker. listTiers is the public catalog the landing
// renders. chooseTier is getAuthUserId-gated and ESCALATION-SAFE: it grants ONLY
// the free tier instantly (the floor); paid tiers are never written here — they
// return a checkout URL (stub: coming-soon) and an entitlement is written ONLY by
// a verified billing webhook / admin grant (design §2.2: "no public setTier").
// The operator (max/unlimited) is never downgraded.
// ---------------------------------------------------------------------------

const tierSpecValidator = v.object({
  name: tierValidator,
  label: v.string(),
  priceUsd: v.number(),
  msgQuota: v.number(),
  channels: v.array(channelValidator),
  blurb: v.string(),
});

export const listTiers = query({
  args: {},
  returns: v.array(tierSpecValidator),
  handler: async () => publicTiers(),
});

export const chooseTier = mutation({
  args: { tier: tierValidator },
  returns: v.object({
    ok: v.boolean(),
    tier: tierValidator,
    granted: v.boolean(),
    checkoutUrl: v.union(v.string(), v.null()),
    message: v.union(v.string(), v.null()),
  }),
  handler: async (ctx, { tier }) => {
    const userId = await requireUser(ctx);

    // Never downgrade the operator (user #0 is permanently max/unlimited).
    const me = await ctx.db.get(userId);
    if (me?.isOperator) {
      return { ok: true, tier: "max" as const, granted: false, checkoutUrl: null, message: null };
    }

    if (tier === "free") {
      await writeEntitlement(ctx, {
        userId,
        tier: "free",
        status: "active",
        source: "stub",
      });
      return { ok: true, tier, granted: true, checkoutUrl: null, message: null };
    }

    // Paid: do NOT grant — surface the checkout (stub returns a coming-soon URL).
    // The free entitlement (from signup) stays in force until a real purchase.
    return {
      ok: true,
      tier,
      granted: false,
      checkoutUrl: "/dashboard?upgrade=coming-soon",
      message: "paid plans are launching soon — you're on free for now.",
    };
  },
});
