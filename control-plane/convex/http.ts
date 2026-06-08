import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { internal } from "./_generated/api";

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

    const allowed = process.env.ALLOWED_USER_NUMBER ?? "";
    if (allowed && userNumber !== allowed) return jsonOk({ ignored: true });

    await ctx.runMutation(internal.messages.enqueue, {
      handle,
      userNumber,
      text,
      mediaUrl: payload?.media_url ? String(payload.media_url) : undefined,
    });
    return jsonOk({ ok: true });
  }),
});

export default http;
