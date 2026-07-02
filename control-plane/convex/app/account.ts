import { query } from "../_generated/server";
import { v } from "convex/values";
import { requireUser } from "./authGate";
import { tierValidator } from "../billing/tiers";

// ---------------------------------------------------------------------------
// app/account — the authed user's own profile. getAuthUserId-gated (A4); reads
// ONLY the caller's own users row (the JWT subject), never another tenant's.
// ---------------------------------------------------------------------------
export const currentUser = query({
  args: {},
  returns: v.union(
    v.null(),
    v.object({
      _id: v.id("users"),
      email: v.union(v.string(), v.null()),
      phone: v.union(v.string(), v.null()),
      displayName: v.union(v.string(), v.null()),
      name: v.union(v.string(), v.null()),
      image: v.union(v.string(), v.null()),
      tier: v.union(tierValidator, v.null()),
      isOperator: v.boolean(),
      createdAt: v.union(v.number(), v.null()),
    }),
  ),
  handler: async (ctx) => {
    const userId = await requireUser(ctx);
    const u = await ctx.db.get(userId);
    if (!u) return null;
    return {
      _id: u._id,
      email: u.email ?? null,
      phone: u.phone ?? null,
      displayName: u.displayName ?? null,
      name: u.name ?? null,
      image: u.image ?? null,
      tier: u.tier ?? null,
      isOperator: u.isOperator ?? false,
      createdAt: u.createdAt ?? null,
    };
  },
});
