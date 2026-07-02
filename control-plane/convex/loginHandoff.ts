import { internalMutation, type MutationCtx } from "./_generated/server";
import { v } from "convex/values";
import type { Id } from "./_generated/dataModel";

export const LOGIN_HANDOFF_TTL_MS = 15 * 60 * 1000;
const TOKEN_BYTES = 24;
const TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;

type EnvLike = { LOGIN_HANDOFF_BASE?: string | undefined };

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function randomBase64Url(bytes: number): string {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  let bin = "";
  for (const b of a) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function loginHandoffBase(env: EnvLike = process.env): string {
  const base = (env.LOGIN_HANDOFF_BASE ?? "").trim().replace(/\/+$/, "");
  if (!base) throw new Error("LOGIN_HANDOFF_BASE not configured");
  return base;
}

export function loginHandoffUrl(token: string, env: EnvLike = process.env): string {
  return `${loginHandoffBase(env)}/login/${encodeURIComponent(token)}`;
}

export async function mintLoginHandoffImpl(
  ctx: MutationCtx,
  userId: Id<"users">,
  opts: { now?: number; env?: EnvLike } = {},
): Promise<{ url: string; expiresAt: number }> {
  const now = opts.now ?? Date.now();
  const token = randomBase64Url(TOKEN_BYTES);
  const expiresAt = now + LOGIN_HANDOFF_TTL_MS;
  await ctx.db.insert("loginHandoffTokens", {
    userId,
    token,
    expiresAt,
    createdAt: now,
  });
  return { url: loginHandoffUrl(token, opts.env), expiresAt };
}

export function normalizeLoginHandoffToken(input: string): string | null {
  let token: string;
  try {
    token = decodeURIComponent(input).trim();
  } catch {
    return null;
  }
  return TOKEN_RE.test(token) ? token : null;
}

export function loginHandoffTokenFromPath(pathname: string): string | null {
  if (!pathname.startsWith("/login/")) return null;
  const raw = pathname.slice("/login/".length).split("/")[0] ?? "";
  return normalizeLoginHandoffToken(raw);
}

type ConsumeResult = {
  ok: boolean;
  userId: Id<"users"> | null;
  expiresAt: number | null;
  reason?: string;
};

export async function consumeLoginHandoffTokenImpl(
  ctx: MutationCtx,
  token: string,
  now = Date.now(),
): Promise<ConsumeResult> {
  const normalized = normalizeLoginHandoffToken(token);
  if (!normalized) {
    return { ok: false, userId: null, expiresAt: null, reason: "not_found" };
  }
  const row = await ctx.db
    .query("loginHandoffTokens")
    .withIndex("by_token", (q) => q.eq("token", normalized))
    .first();
  if (!row || !safeEqual(row.token, normalized)) {
    return { ok: false, userId: null, expiresAt: null, reason: "not_found" };
  }
  if (row.expiresAt <= now) {
    return { ok: false, userId: row.userId, expiresAt: row.expiresAt, reason: "expired" };
  }
  if (row.consumedAt) {
    return { ok: false, userId: row.userId, expiresAt: row.expiresAt, reason: "consumed" };
  }
  await ctx.db.patch(row._id, { consumedAt: now });
  return { ok: true, userId: row.userId, expiresAt: row.expiresAt };
}

export const consumeForHttp = internalMutation({
  args: { token: v.string() },
  returns: v.object({
    ok: v.boolean(),
    userId: v.union(v.id("users"), v.null()),
    expiresAt: v.union(v.number(), v.null()),
    reason: v.optional(v.string()),
  }),
  handler: async (ctx, { token }) => consumeLoginHandoffTokenImpl(ctx, token),
});

function htmlResponse(html: string, status: number): Response {
  return new Response(html, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

export function loginHandoffInvalidHtml(): string {
  return [
    "<!doctype html>",
    "<meta charset=\"utf-8\">",
    "<title>Login link unavailable</title>",
    "<body style=\"font-family:system-ui,sans-serif;margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f7f5;color:#20201d\">",
    "<main style=\"max-width:520px;padding:32px\">",
    "<h1 style=\"font-size:24px;margin:0 0 12px\">Login link unavailable</h1>",
    "<p style=\"line-height:1.5;margin:0\">This login handoff link is invalid or expired. Ask Eve to send a fresh link by repeating the order.</p>",
    "</main>",
    "</body>",
  ].join("");
}

export function loginHandoffPendingHtml(): string {
  // TODO(controller/ops): replace this holding page with an embedded same-host,
  // auth-gated CDP DevTools/screencast proxy after the controller publishes the
  // tenant container's loopback Chrome port through the host bridge. Convex cannot
  // reach 127.0.0.1:9222 inside the fleet container.
  return [
    "<!doctype html>",
    "<meta charset=\"utf-8\">",
    "<title>Login handoff</title>",
    "<body style=\"font-family:system-ui,sans-serif;margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f7f5;color:#20201d\">",
    "<main style=\"max-width:620px;padding:32px\">",
    "<h1 style=\"font-size:24px;margin:0 0 12px\">Login handoff link verified</h1>",
    "<p style=\"line-height:1.5;margin:0 0 12px\">The secure live Chrome view is not published yet. Do not enter credentials on this page.</p>",
    "<p style=\"line-height:1.5;margin:0\">Operator action required: publish the auth-gated same-host CDP proxy for this tenant, then send a fresh login link.</p>",
    "</main>",
    "</body>",
  ].join("");
}

export async function loginHandoffGetResponse(
  request: Request,
  consume: (token: string) => Promise<ConsumeResult>,
): Promise<Response> {
  const token = loginHandoffTokenFromPath(new URL(request.url).pathname);
  if (!token) return htmlResponse(loginHandoffInvalidHtml(), 404);
  try {
    const result = await consume(token);
    if (!result.ok) return htmlResponse(loginHandoffInvalidHtml(), 404);
    return htmlResponse(loginHandoffPendingHtml(), 200);
  } catch {
    return htmlResponse(loginHandoffInvalidHtml(), 404);
  }
}
