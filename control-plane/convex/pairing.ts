import { internalMutation, type MutationCtx } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";
import type { Doc, Id } from "./_generated/dataModel";
import { channelValidator } from "./lib/auth";

// ---------------------------------------------------------------------------
// Pairing primitive (multi-tenancy connect flow). ONE pairingTokens row carries
// BOTH a base64url `token` (Telegram /start deep-link, <=64-char [A-Za-z0-9_-]
// payload) and a 6-char human-typable `code` (iMessage "pair <code>"). The
// landing mints (issuePairingToken, wrapped by the getAuthUserId-gated
// app/channels:createPairingToken in M4); the inbound webhooks consume
// (redeemTelegram / redeemImessage) to create a VERIFIED channelBinding —
// (channel,address) -> userId, the tenant resolver (A1).
//
// These are internalMutations: callable only by other Convex functions
// (httpActions / the user-facing wrapper), never directly by a client.
//
// Safety (design §7): consume validates status=="active" && expiresAt>now &&
// channel matches; re-tapping a consumed token is idempotent (re-greet, no 2nd
// binding); binding an address already owned by a DIFFERENT user is REJECTED
// (tenant-hijack guard). One active token per (user,channel) — minting supersedes.
// ---------------------------------------------------------------------------

const TOKEN_TTL_MS = 15 * 60 * 1000; // 15 minutes
const CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ23456789"; // 32 chars, no 0/1/O/I ambiguity

function _randomBytes(n: number): Uint8Array {
  const a = new Uint8Array(n);
  crypto.getRandomValues(a);
  return a;
}

// 16 random bytes -> 22-char base64url (no padding), Telegram-/start-safe.
function _genToken(): string {
  const bytes = _randomBytes(16);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// 6-char human-typable code from the unambiguous 32-char alphabet.
function _genCode(): string {
  const bytes = _randomBytes(6);
  let out = "";
  for (const b of bytes) out += CODE_ALPHABET[b % CODE_ALPHABET.length];
  return out;
}

// ---------------------------------------------------------------------------
// issuePairingTokenImpl — mint a fresh single-use token+code for (user,channel),
// superseding any still-active one. Plain helper so BOTH the internalMutation and
// the getAuthUserId-gated app wrapper (app/channels:createPairingToken) write in
// ONE transaction without a nested ctx.runMutation. Returns the token/code/expiry
// the connect UI renders (deep-link for Telegram, copyable code for iMessage).
// ---------------------------------------------------------------------------
export async function issuePairingTokenImpl(
  ctx: MutationCtx,
  userId: Id<"users">,
  channel: "imessage" | "telegram",
): Promise<{ token: string; code: string; expiresAt: number; channel: "imessage" | "telegram" }> {
  const now = Date.now();

  // Supersede any still-active token for this (user,channel) — only one live at a
  // time (index-scoped read, not a table scan). Bounded take(): steady state is
  // 1–2 rows, but consumed/expired/superseded rows accumulate per (user,channel),
  // so cap the read instead of an unbounded .collect() (the expireStaleTokens cron
  // keeps the tail trimmed). 200 dead rows for one user/channel is already absurd.
  const prior = await ctx.db
    .query("pairingTokens")
    .withIndex("by_user_channel", (q) => q.eq("userId", userId).eq("channel", channel))
    .take(200);
  for (const p of prior) {
    if (p.status === "active") await ctx.db.patch(p._id, { status: "superseded" });
  }

  const token = _genToken();
  const code = _genCode();
  const expiresAt = now + TOKEN_TTL_MS;
  await ctx.db.insert("pairingTokens", {
    userId, channel, token, code, status: "active", expiresAt, createdAt: now,
  });
  return { token, code, expiresAt, channel };
}

export const issuePairingToken = internalMutation({
  args: { userId: v.id("users"), channel: channelValidator },
  returns: v.object({
    token: v.string(),
    code: v.string(),
    expiresAt: v.number(),
    channel: channelValidator,
  }),
  handler: async (ctx, { userId, channel }) => {
    return await issuePairingTokenImpl(ctx, userId, channel);
  },
});

const redeemReturns = v.object({
  ok: v.boolean(),
  userId: v.union(v.id("users"), v.null()),
  reason: v.optional(v.string()),
  idempotent: v.optional(v.boolean()),
});

// Shared redeem core: validate the token row, then check-then-bind (channel,address)
// -> userId. `lookup` finds the row by token (Telegram) or code (iMessage).
async function _redeem(
  ctx: MutationCtx,
  channel: "imessage" | "telegram",
  address: string,
  lookup: () => Promise<Doc<"pairingTokens"> | null>,
): Promise<{ ok: boolean; userId: Id<"users"> | null; reason?: string; idempotent?: boolean }> {
  const now = Date.now();
  const addr = (address || "").trim();
  if (!addr) return { ok: false, userId: null, reason: "no_address" };

  const row = await lookup();
  if (!row || row.channel !== channel) {
    return { ok: false, userId: null, reason: "not_found" };
  }

  // Existing binding for this (channel,address)?
  const existing = await ctx.db
    .query("channelBindings")
    .withIndex("by_address", (q) => q.eq("channel", channel).eq("address", addr))
    .first();

  // Idempotent re-tap of a consumed token by the SAME owner -> re-greet, no-op.
  if (row.status === "consumed") {
    if (existing && existing.userId === row.userId && existing.verified) {
      return { ok: true, userId: row.userId, idempotent: true };
    }
    return { ok: false, userId: null, reason: "already_consumed" };
  }
  if (row.status !== "active" || row.expiresAt <= now) {
    return { ok: false, userId: null, reason: "expired" };
  }

  // Tenant-hijack guard: address already owned by a DIFFERENT user.
  if (existing && existing.userId !== row.userId) {
    return { ok: false, userId: null, reason: "address_taken" };
  }

  if (existing) {
    await ctx.db.patch(existing._id, { verified: true, lastInboundAt: now });
  } else {
    await ctx.db.insert("channelBindings", {
      userId: row.userId, channel, address: addr, verified: true, createdAt: now,
    });
  }
  await ctx.db.patch(row._id, { status: "consumed", consumedAt: now });
  return { ok: true, userId: row.userId };
}

// Plain redeem impls (exported so the double-gated test wrappers in testing.ts can
// drive the EXACT redeem path over HTTP — internalMutations aren't HTTP-callable).
export async function redeemTelegramImpl(ctx: MutationCtx, token: string, address: string) {
  return await _redeem(ctx, "telegram", address, () =>
    ctx.db.query("pairingTokens").withIndex("by_token", (q) => q.eq("token", token)).first(),
  );
}

export async function redeemImessageImpl(ctx: MutationCtx, code: string, address: string) {
  const norm = (code || "").trim().toUpperCase();
  return await _redeem(ctx, "imessage", address, () =>
    ctx.db.query("pairingTokens").withIndex("by_code", (q) => q.eq("code", norm)).first(),
  );
}

// ---------------------------------------------------------------------------
// redeemTelegram — /start <token>. Binds (telegram, chat.id) -> userId.
// ---------------------------------------------------------------------------
export const redeemTelegram = internalMutation({
  args: {
    token: v.string(),
    address: v.string(), // String(chat.id)
    replyTarget: v.optional(v.string()),
    firstName: v.optional(v.string()),
  },
  returns: redeemReturns,
  handler: async (ctx, { token, address }) => {
    return await redeemTelegramImpl(ctx, token, address);
  },
});

// ---------------------------------------------------------------------------
// redeemImessage — "pair <code>". Binds (imessage, E.164) -> userId.
// ---------------------------------------------------------------------------
export const redeemImessage = internalMutation({
  args: { code: v.string(), address: v.string() },
  returns: redeemReturns,
  handler: async (ctx, { code, address }) => {
    return await redeemImessageImpl(ctx, code, address);
  },
});

// ---------------------------------------------------------------------------
// expireStaleTokens (cron, internal) — housekeeping. consume already self-checks
// expiresAt>now, so this is non-load-bearing; it keeps the by_user_channel
// "one active per (user,channel)" invariant clean and the dashboard honest. Index
// scan by_status_expiry(status="active") ORDERED by expiresAt, so the oldest
// (definitely-expired) rows come first; stop at the first un-expired one. Paginate
// via self-reschedule.
// ---------------------------------------------------------------------------
const TOKEN_REAP_BATCH = 500;

export const expireStaleTokens = internalMutation({
  args: {},
  returns: v.object({ expired: v.number() }),
  handler: async (ctx) => {
    const now = Date.now();
    const stale = await ctx.db
      .query("pairingTokens")
      .withIndex("by_status_expiry", (q) =>
        q.eq("status", "active").lt("expiresAt", now),
      )
      .take(TOKEN_REAP_BATCH);
    for (const t of stale) await ctx.db.patch(t._id, { status: "expired" });
    if (stale.length === TOKEN_REAP_BATCH) {
      await ctx.scheduler.runAfter(0, internal.pairing.expireStaleTokens, {});
    }
    return { expired: stale.length };
  },
});
