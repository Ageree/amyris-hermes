import { query, mutation } from "../_generated/server";
import { v } from "convex/values";
import { requireUser } from "./authGate";
import { channelValidator } from "../lib/auth";
import { issuePairingTokenImpl } from "../pairing";

// ---------------------------------------------------------------------------
// app/channels — the connect surface for the dashboard/wizard. All getAuthUserId-
// gated (A4) and tenant-scoped (A1): every read uses channelBindings.by_user
// q.eq("userId", me) — never .filter(), never a client userId. createPairingToken
// mints via the shared issuePairingTokenImpl (one transaction); the inbound
// webhook redeems it. A client can only ever touch its OWN bindings/tokens.
// ---------------------------------------------------------------------------

// myChannels — the user's own bindings (drives the live "connected" UI). The
// connect wizard subscribes to this; the webhook binding flips it with no polling.
export const myChannels = query({
  args: {},
  returns: v.array(
    v.object({
      kind: channelValidator,
      address: v.string(),
      verified: v.boolean(),
      lastInboundAt: v.union(v.number(), v.null()),
      createdAt: v.number(),
    }),
  ),
  handler: async (ctx) => {
    const userId = await requireUser(ctx);
    const rows = await ctx.db
      .query("channelBindings")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .collect();
    return rows.map((b) => ({
      kind: b.channel,
      address: b.address,
      verified: b.verified,
      lastInboundAt: b.lastInboundAt ?? null,
      createdAt: b.createdAt,
    }));
  },
});

// createPairingToken — mint a fresh single-use token+code for (me, channel),
// superseding any active one. Returns the deep-link (telegram) or copyable code
// (imessage) the wizard renders. The token is base64url <=64 chars (Telegram
// /start payload-safe). NO client userId — identity is the JWT subject.
export const createPairingToken = mutation({
  args: { channel: channelValidator },
  returns: v.object({
    token: v.string(),
    code: v.string(),
    expiresAt: v.number(),
    channel: channelValidator,
    deepLink: v.union(v.string(), v.null()),
  }),
  handler: async (ctx, { channel }) => {
    const userId = await requireUser(ctx);
    const minted = await issuePairingTokenImpl(ctx, userId, channel);

    // Telegram deep-link if the bot username is configured; else the client falls
    // back to instructing a manual /start. iMessage uses the code, not a link.
    const botUser = process.env.TELEGRAM_BOT_USERNAME ?? "";
    const deepLink =
      channel === "telegram" && botUser
        ? `https://t.me/${botUser}?start=${minted.token}`
        : null;

    return { ...minted, deepLink };
  },
});

// disconnectChannel — remove one of MY bindings (re-verify ownership after get;
// A8). A missing/foreign binding is a no-op (idempotent), never an error leak.
export const disconnectChannel = mutation({
  args: { channel: channelValidator, address: v.string() },
  returns: v.object({ ok: v.boolean() }),
  handler: async (ctx, { channel, address }) => {
    const userId = await requireUser(ctx);
    const binding = await ctx.db
      .query("channelBindings")
      .withIndex("by_address", (q) => q.eq("channel", channel).eq("address", address))
      .first();
    // Ownership re-check: only delete a binding that is actually mine.
    if (!binding || binding.userId !== userId) return { ok: false };
    await ctx.db.delete(binding._id);
    return { ok: true };
  },
});
