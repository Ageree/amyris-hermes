import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { internal } from "./_generated/api";
import { auth } from "./auth";

const http = httpRouter();

function jsonOk(obj: unknown): Response {
  return new Response(JSON.stringify(obj), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

// Constant-time string compare (avoid leaking the secret via timing).
function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// Sendblue inbound webhook. Always-on at https://<deployment>.convex.site.
// Auth model (ported from the Python bridge, lab/skeleton/app.py):
//   1. high-entropy secret in the URL path (operator pastes it into the Sendblue
//      dashboard) — compared constant-time; wrong/absent -> 401.
//   2. reply-target allowlist: only accept inbound from ALLOWED_USER_NUMBER.
//   3. idempotency: dedup on message_handle happens in messages.enqueue.
// On success it ENQUEUES (durable) and returns 200 immediately — the brain
// processes asynchronously by polling. Never 5xx for payload problems (Sendblue
// retries on 5xx); auth failure is the one 4xx.
http.route({
  pathPrefix: "/sendblue/inbound/",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    const url = new URL(request.url);
    const token = url.pathname.slice("/sendblue/inbound/".length);
    const expected = process.env.WEBHOOK_SECRET ?? "";
    if (!expected || !safeEqual(token, expected)) {
      return new Response("unauthorized", { status: 401 });
    }

    let payload: any;
    try {
      payload = await request.json();
    } catch {
      return jsonOk({ ignored: true }); // malformed JSON — don't make Sendblue retry
    }

    if (payload?.is_outbound === true || payload?.opted_out === true) {
      return jsonOk({ ignored: true });
    }
    const text = String(payload?.content ?? "").trim();
    const userNumber = String(payload?.number ?? "").trim();
    const handle = String(payload?.message_handle ?? "");
    if (!text || !userNumber || !handle) return jsonOk({ ignored: true });
    const mediaUrl = payload?.media_url ? String(payload.media_url) : undefined;

    // "pair <code>" → redeem an iMessage pairing token (binds this sender's number
    // to the tenant who minted it). Open to ANY sender on the shared number — the
    // code is single-use + 15-min TTL + cross-user-rejected, so a stranger can't
    // hijack a binding. (Per-number failed-attempt rate-limiting is an M7 hardening.)
    const pairMatch = text.match(/^pair\s+([a-z2-9]{6})$/i);
    if (pairMatch) {
      await ctx.runMutation(internal.pairing.redeemImessage, {
        code: pairMatch[1],
        address: userNumber,
      });
      return jsonOk({ ok: true });
    }

    // Operator (user #0) stays on the LEGACY enqueue path (userId undefined) while
    // his launchd worker still polls the global claimNext — the container cutover to
    // claimNextForUser is operator-gated (design §10 step 8; see the M7-tighten
    // DEFERRED plan). Until that cutover completes, do NOT tag his rows here, or the
    // legacy worker (which claims only userId===undefined) would go dark.
    const allowed = process.env.ALLOWED_USER_NUMBER ?? "";
    if (allowed && userNumber === allowed) {
      await ctx.runMutation(internal.messages.enqueue, {
        handle,
        userNumber,
        text,
        mediaUrl,
      });
      return jsonOk({ ok: true });
    }

    // Multi-tenant resolution: a VERIFIED (imessage, number) binding → tenant. The
    // enqueued row carries userId/channel/replyTarget so the fleet worker claims
    // it via claimNextForUser and replies to the sender's OWN number (A1/A2).
    const resolved = await ctx.runQuery(
      internal.lib.identity.resolveUserByAddress,
      { channel: "imessage", address: userNumber },
    );
    if (!resolved) return jsonOk({ ignored: true }); // unknown sender → drop (no budget burn)

    await ctx.runMutation(internal.messages.enqueue, {
      handle,
      userId: resolved.userId,
      channel: "imessage",
      replyTarget: userNumber,
      userNumber,
      text,
      mediaUrl,
    });
    // Cold-start: ensure this tenant's container is desired-running so an idle /
    // never-launched instance gets relaunched by the controller (best-effort —
    // the message is already durable, so a transient failure here is recovered by
    // the next inbound or a warm worker; never 5xx the webhook over it).
    try {
      await ctx.runMutation(internal.fleet.requestInstanceInternal, {
        userId: resolved.userId,
        channel: "imessage",
      });
    } catch {
      // swallow — durable enqueue already succeeded
    }
    return jsonOk({ ok: true });
  }),
});

// Telegram inbound webhook. Always-on at https://<deployment>.convex.site.
// Auth model (design §3.1): the constant-time secret token in the
// `X-Telegram-Bot-Api-Secret-Token` header (set when registering the webhook via
// setWebhook), compared to TELEGRAM_WEBHOOK_SECRET. Wrong/absent -> 401.
// Validation: ignore bots, edits, non-private chats, and empty payloads. Never
// 5xx on a payload problem (Telegram retries non-2xx). `/start <token>` redeems a
// pairing token (binds chat.id -> userId). A normal message from a VERIFIED chat
// is enqueued (durable, channel="telegram", routed back to chat.id). Unknown
// senders are dropped (no enqueue, no send) so a stranger can't burn the shared
// bot's budget. handle = "tg:<update_id>" is the idempotency key.
http.route({
  path: "/telegram/inbound",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    const header = request.headers.get("X-Telegram-Bot-Api-Secret-Token") ?? "";
    const expected = process.env.TELEGRAM_WEBHOOK_SECRET ?? "";
    if (!expected || !safeEqual(header, expected)) {
      return new Response("unauthorized", { status: 401 });
    }

    let update: any;
    try {
      update = await request.json();
    } catch {
      return jsonOk({ ignored: true }); // malformed JSON — don't make Telegram retry
    }

    // Only fresh, private, human messages. Ignore edits/channel posts/bots.
    const msg = update?.message;
    if (!msg || update?.edited_message || update?.channel_post) {
      return jsonOk({ ignored: true });
    }
    if (msg?.chat?.type !== "private" || msg?.from?.is_bot === true) {
      return jsonOk({ ignored: true });
    }
    const text = String(msg?.text ?? "").trim();
    const chatId = msg?.chat?.id;
    const fromId = msg?.from?.id;
    if (!text || chatId === undefined || chatId === null || fromId === undefined || fromId === null) {
      return jsonOk({ ignored: true });
    }

    const replyTarget = String(chatId);
    const userNumber = String(fromId);
    const handle = `tg:${update?.update_id ?? ""}`;

    // /start <token> -> redeem the pairing token (onboard this chat).
    const start = text.match(/^\/start\s+([A-Za-z0-9_-]{1,64})$/);
    if (start) {
      await ctx.runMutation(internal.pairing.redeemTelegram, {
        token: start[1],
        address: replyTarget,
        replyTarget,
        firstName: msg?.from?.first_name ? String(msg.from.first_name) : undefined,
      });
      // Binding flips the dashboard live; the user's next message is answered.
      return jsonOk({ ok: true });
    }

    // Resolve the sender to a tenant via a VERIFIED binding. Unknown -> drop.
    const resolved = await ctx.runQuery(internal.lib.identity.resolveUserByAddress, {
      channel: "telegram",
      address: replyTarget,
    });
    if (!resolved) return jsonOk({ ignored: true });

    await ctx.runMutation(internal.messages.enqueue, {
      handle,
      userId: resolved.userId,
      channel: "telegram",
      replyTarget,
      userNumber,
      text,
    });
    // Cold-start (see Sendblue branch): flip this tenant's container desired-running.
    try {
      await ctx.runMutation(internal.fleet.requestInstanceInternal, {
        userId: resolved.userId,
        channel: "telegram",
      });
    } catch {
      // swallow — durable enqueue already succeeded
    }
    return jsonOk({ ok: true });
  }),
});

// Convex Auth sign-in / OAuth-callback / token routes (design §9). Appended to
// the SAME router so the always-on Sendblue + Telegram webhooks above keep working.
auth.addHttpRoutes(http);

export default http;
