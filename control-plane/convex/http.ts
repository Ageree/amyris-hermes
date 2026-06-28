import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { internal } from "./_generated/api";
import { auth } from "./auth";
import {
  listHabits,
  addHabit,
  checkToday,
  renderAppHtml,
  MAX_TITLE_LEN,
} from "./lib/habitApp";
import { injectRuntime, guardSql } from "./lib/sitelib";
import { execSql } from "./lib/turso";

const http = httpRouter();

function jsonOk(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function jsonError(status: number, message: string): Response {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
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
    // Carry the message_id so the worker can target reactions back at this inbound
    // (worker._provider_msg_id parses "tg:<update_id>:<message_id>"). update_id stays
    // FIRST so the by_channel_handle idempotency key stays unique per update.
    const handle = `tg:${update?.update_id ?? ""}:${msg?.message_id ?? ""}`;

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
    // Eve-core cutover (spec §2.1, Shape A): when enabled, kick the in-Convex Eve
    // drainer instead of waiting on the legacy Python worker. Off by default
    // (EVE_DRAINER_ENABLED unset) so this is dormant until the operator flips it and
    // stops the Python worker. Best-effort schedule — the durable enqueue already
    // happened, so a scheduling hiccup just leaves the row for the next kick/worker.
    if (process.env.EVE_DRAINER_ENABLED === "1") {
      try {
        await ctx.scheduler.runAfter(0, internal.agent.drainOne, {});
      } catch {
        // swallow — row is durably queued; a later inbound (or reaper) re-kicks it
      }
    }
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

// ---------------------------------------------------------------------------
// Personalized AI apps (Feature 5). Serve a generated, Turso-backed app at
// https://<deployment>.convex.site/app/<slug>:
//   GET  /app/<slug>               → the app page (server-rendered shell)
//   GET  /app/<slug>/api/habits    → list (public read)
//   POST /app/<slug>/api/habits        {title}  → add
//   POST /app/<slug>/api/habits/<id>/check       → check today
// The slug resolves to its Turso data plane via internal.apps.getBySlug; the
// data-plane token is read from process.env[app.dbTokenRef] INSIDE the action and
// never reaches the browser. Path is split on "/app/" then "/": first segment =
// slug, remainder = the in-app sub-route.
//
// ponytail ceiling: the REAL multi-tenant gate is per-user auth on /api/* (deferred
// — same posture as served/server.py's single-tenant note). v1 reads are public and
// the only served shape is the habit tracker (see lib/habitApp.ts). Writes are open
// by default; if APP_WRITE_SECRET is set, they additionally require a const-time
// X-App-Write-Secret header so an agent/automation path can lock writes without
// exposing the data token.
function appPath(request: Request): { slug: string; subpath: string } {
  const url = new URL(request.url);
  const rest = url.pathname.slice("/app/".length);
  const [slug, ...sub] = rest.split("/");
  return { slug, subpath: sub.join("/") };
}

http.route({
  pathPrefix: "/app/",
  method: "GET",
  handler: httpAction(async (ctx, request) => {
    const { slug, subpath } = appPath(request);
    if (!slug) return new Response("not found", { status: 404 });

    const app = await ctx.runQuery(internal.apps.getBySlug, { slug });
    if (!app) return new Response("not found", { status: 404 });

    if (subpath === "") {
      return new Response(renderAppHtml(slug, app.name), {
        status: 200,
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    }

    if (subpath === "api/habits") {
      const token = process.env[app.dbTokenRef];
      // TODO(deploy): the operator sets the data-plane token out-of-band via
      // `convex env set <dbTokenRef> <token>` (the Python provisioner does this);
      // the row only stores the NAME. Missing token → fail closed (never leak it).
      if (!token) return jsonError(500, "app data token not configured");
      try {
        return jsonOk({ habits: await listHabits(app.dbHostname, token) });
      } catch (e) {
        return jsonError(502, `database error: ${errMsg(e)}`);
      }
    }

    return new Response("not found", { status: 404 });
  }),
});

http.route({
  pathPrefix: "/app/",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    const { slug, subpath } = appPath(request);
    if (!slug) return new Response("not found", { status: 404 });

    const app = await ctx.runQuery(internal.apps.getBySlug, { slug });
    if (!app) return new Response("not found", { status: 404 });

    // Optional write gate (const-time, same primitive as the webhook secrets).
    const writeSecret = process.env.APP_WRITE_SECRET ?? "";
    if (writeSecret) {
      const provided = request.headers.get("X-App-Write-Secret") ?? "";
      if (!safeEqual(provided, writeSecret)) {
        return new Response("unauthorized", { status: 401 });
      }
    }

    const token = process.env[app.dbTokenRef];
    if (!token) return jsonError(500, "app data token not configured");

    if (subpath === "api/habits") {
      let body: any;
      try {
        body = await request.json();
      } catch {
        return jsonError(400, "body is not valid JSON");
      }
      // Trust-boundary validation: title required, non-empty, bounded.
      const title = typeof body?.title === "string" ? body.title.trim() : "";
      if (!title) return jsonError(400, "title is required and must be a non-empty string");
      if (title.length > MAX_TITLE_LEN) return jsonError(400, `title too long (max ${MAX_TITLE_LEN})`);
      try {
        return jsonOk(await addHabit(app.dbHostname, token, title), 201);
      } catch (e) {
        return jsonError(502, `database error: ${errMsg(e)}`);
      }
    }

    const checkMatch = subpath.match(/^api\/habits\/(\d+)\/check$/);
    if (checkMatch) {
      // Trust-boundary validation: id must be a positive integer.
      const habitId = Number(checkMatch[1]);
      if (!Number.isInteger(habitId) || habitId <= 0) {
        return jsonError(400, "habit id must be a positive integer");
      }
      try {
        const res = await checkToday(app.dbHostname, token, habitId);
        if (!res) return jsonError(404, "no such habit");
        return jsonOk(res);
      } catch (e) {
        return jsonError(502, `database error: ${errMsg(e)}`);
      }
    }

    return new Response("not found", { status: 404 });
  }),
});

// ---------------------------------------------------------------------------
// chat-sites: serve generated sites + proxy app data. Served from the
// `.convex.site` origin — DELIBERATELY separate from the dashboard origin so
// generated (LLM, possibly prompt-injected) JS cannot reach the dashboard's
// auth cookies. The per-site Turso token stays server-side; the browser only
// ever talks to /site-data/<handle> (same origin), which proxies guarded SQL to
// that one site's isolated DB.
// ---------------------------------------------------------------------------

function htmlResponse(html: string, status = 200): Response {
  return new Response(html, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      // user content on its own origin; don't let it be framed onto our dashboard
      "x-content-type-options": "nosniff",
    },
  });
}

const NOT_FOUND_HTML =
  "<!doctype html><meta charset=utf-8><title>Not found</title>" +
  "<body style='font-family:system-ui;display:grid;place-items:center;height:100vh;margin:0'>" +
  "<div><h1>404</h1><p>No site lives here (yet).</p></div>";

// GET /s/<handle> — serve the generated single-file document.
http.route({
  pathPrefix: "/s/",
  method: "GET",
  handler: httpAction(async (ctx, request) => {
    const url = new URL(request.url);
    const handle = decodeURIComponent(url.pathname.slice("/s/".length)).replace(/\/+$/, "");
    if (!handle) return htmlResponse(NOT_FOUND_HTML, 404);
    const site = await ctx.runQuery(internal.sites.getByHandle, { handle });
    if (!site) return htmlResponse(NOT_FOUND_HTML, 404);
    const html = injectRuntime(site.html, {
      handle: site.handle,
      kind: site.kind,
      apiBase: url.origin,
    });
    return htmlResponse(html);
  }),
});

function dataJson(obj: unknown, status = 200): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "content-type": "application/json",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "POST, OPTIONS",
      "access-control-allow-headers": "content-type",
    },
  });
}

// CORS preflight for the data proxy (apps may be embedded cross-origin).
http.route({
  pathPrefix: "/site-data/",
  method: "OPTIONS",
  handler: httpAction(async () => dataJson({ ok: true })),
});

// POST /site-data/<handle> — run ONE guarded SQL statement against the site's
// own isolated Turso DB. Open by design (public read+write to the site's own DB);
// blast radius is that single site. See lib/sitelib.guardSql.
http.route({
  pathPrefix: "/site-data/",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    const url = new URL(request.url);
    const handle = decodeURIComponent(url.pathname.slice("/site-data/".length)).replace(/\/+$/, "");
    const site = await ctx.runQuery(internal.sites.getByHandle, { handle });
    if (!site) return dataJson({ error: "site not found" }, 404);
    if (site.kind !== "app" || !site.tursoHostname || !site.tursoToken) {
      return dataJson({ error: "site has no data backend" }, 400);
    }
    let payload: any;
    try {
      payload = await request.json();
    } catch {
      return dataJson({ error: "invalid JSON body" }, 400);
    }
    let sql: string;
    try {
      sql = guardSql(String(payload?.sql ?? ""));
    } catch (e: any) {
      return dataJson({ error: String(e?.message ?? e) }, 400);
    }
    const args = Array.isArray(payload?.args) ? payload.args : [];
    try {
      const result = await execSql(site.tursoHostname, site.tursoToken, sql, args);
      return dataJson(result);
    } catch (e: any) {
      return dataJson({ error: String(e?.message ?? e) }, 400);
    }
  }),
});

// Convex Auth sign-in / OAuth-callback / token routes (design §9). Appended to
// the SAME router so the always-on Sendblue + Telegram webhooks above keep working.
auth.addHttpRoutes(http);

export default http;
