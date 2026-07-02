import { internalQuery } from "../_generated/server";
import { v } from "convex/values";
import { channelValidator } from "./auth";

// ---------------------------------------------------------------------------
// THE tenant resolver (invariant A1: the tenant key is Id<"users">; the raw
// phone / Telegram chat-id is only an ADDRESS, never a join key). The inbound
// webhooks call this to turn a (channel, address) pair into the owning userId so
// every enqueued message carries its tenant. Index-only read (channelBindings
// .by_address) — never .filter() (A-security: index-only tenant reads).
//
// Internal: it's a control-plane primitive the httpAction calls via
// ctx.runQuery(internal.lib.identity.resolveUserByAddress, ...), not a public
// surface a client could probe to enumerate bindings.
// ---------------------------------------------------------------------------
export const resolveUserByAddress = internalQuery({
  args: {
    channel: channelValidator,
    address: v.string(),
  },
  // Only a VERIFIED binding resolves — an unverified row (mid-pairing) must NOT
  // start routing a stranger's messages to a tenant. null => unknown sender.
  returns: v.union(v.object({ userId: v.id("users") }), v.null()),
  handler: async (ctx, { channel, address }) => {
    const binding = await ctx.db
      .query("channelBindings")
      .withIndex("by_address", (q) =>
        q.eq("channel", channel).eq("address", address),
      )
      .first();
    if (!binding || !binding.verified) return null;
    return { userId: binding.userId };
  },
});

export const freshestVerifiedBinding = internalQuery({
  args: { userId: v.id("users") },
  returns: v.union(
    v.object({
      channel: channelValidator,
      address: v.string(),
      lastInboundAt: v.union(v.number(), v.null()),
    }),
    v.null(),
  ),
  handler: async (ctx, { userId }) => {
    const rows = await ctx.db
      .query("channelBindings")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .collect();
    const verified = rows.filter((r) => r.verified);
    if (!verified.length) return null;
    verified.sort((a, b) => {
      const aAt = a.lastInboundAt ?? a.createdAt;
      const bAt = b.lastInboundAt ?? b.createdAt;
      return bAt - aAt;
    });
    const best = verified[0];
    return {
      channel: best.channel,
      address: best.address,
      lastInboundAt: best.lastInboundAt ?? null,
    };
  },
});
