"use node";
// Node runtime: the drainer reads an open NDJSON stream incrementally (lib/eve.ts
// getReader()) and base64-encodes Basic auth (Buffer) — both need Node, not the
// default Convex runtime (which buffers fetch bodies and lacks Buffer).
import { internalAction } from "./_generated/server";
import { v } from "convex/values";
import { internal, api } from "./_generated/api";
import { callEve, sendTelegram, type Turn } from "./lib/eve";

// ---------------------------------------------------------------------------
// Shape-A drainer (spec §2.1): the Eve brain replaces the Python worker. Instead of
// a process polling claimNextAny, the Telegram inbound webhook SCHEDULES drainOne
// (event-kicked, no polling). drainOne claims the oldest queued row, asks the
// deployed Eve agent for a reply (history injected for memory), sends it back over
// Telegram, marks the row done, then reschedules itself to drain the next row.
//
// SAFETY / CUTOVER: the webhook only schedules this when EVE_DRAINER_ENABLED=1
// (http.ts). Until then the legacy Python worker serves traffic unchanged — this
// module is dormant. The atomic claim (status queued->processing) gives at-most-once
// delivery even if both run during cutover; flip the env AND stop the Python worker
// to complete the swap. Reverts by unsetting the env (Python resumes).
//
// Required Convex env at cutover: EVE_URL, EVE_INGRESS_SECRET, TELEGRAM_BOT_TOKEN
// (WORKER_SECRET already set). Missing EVE_URL/secret -> the row is failed loudly
// (never a fabricated success).
// ---------------------------------------------------------------------------

const HISTORY_LIMIT = 10;

export const drainOne = internalAction({
  args: {},
  returns: v.object({ drained: v.number() }),
  handler: async (ctx): Promise<{ drained: number }> => {
    const workerSecret = process.env.WORKER_SECRET ?? "";
    const eveUrl = process.env.EVE_URL ?? "";
    const eveSecret = process.env.EVE_INGRESS_SECRET ?? "";
    const tgToken = process.env.TELEGRAM_BOT_TOKEN ?? "";

    // Claim the oldest queued row across tenants (per-row userId keeps routing scoped).
    const row = await ctx.runMutation(api.messages.claimNextAny, { workerSecret });
    if (!row) return { drained: 0 };

    // Always reschedule after a claim so a backlog drains fully (one row per action
    // keeps each turn's CPU/time bounded). Scheduled first so an error below still
    // advances the queue.
    await ctx.scheduler.runAfter(0, internal.agent.drainOne, {});

    try {
      if (!eveUrl || !eveSecret) {
        throw new Error("EVE_URL / EVE_INGRESS_SECRET not configured");
      }
      // v1 new core is Telegram-only (spec Q4). A non-telegram row reaching the
      // drainer is a misconfiguration — fail it loudly rather than silently drop.
      if (row.channel !== "telegram") {
        throw new Error(`eve-core v1 is telegram-only; got channel=${row.channel}`);
      }

      // Conversation memory: feed the last done turns as context (the claimed row is
      // "processing", so recentForUser — which only returns done rows — excludes it).
      const recent = (await ctx.runQuery(api.messages.recentForUser, {
        workerSecret,
        userId: row.userId ?? undefined,
        userNumber: row.userId ? undefined : row.userNumber,
        limit: HISTORY_LIMIT,
      })) as Turn[];

      const reply = await callEve({
        baseUrl: eveUrl,
        secret: eveSecret,
        history: recent,
        text: row.text,
      });

      const sent = await sendTelegram({ token: tgToken, chatId: row.replyTarget, text: reply });
      if (!sent) throw new Error("telegram send failed");

      await ctx.runMutation(api.messages.complete, { workerSecret, id: row.id, reply });
      return { drained: 1 };
    } catch (e) {
      const error = e instanceof Error ? e.message : String(e);
      await ctx.runMutation(api.messages.fail, { workerSecret, id: row.id, error });
      return { drained: 0 };
    }
  },
});
