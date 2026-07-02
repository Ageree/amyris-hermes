"use node";

import { internalAction } from "../_generated/server";
import { v } from "convex/values";
import { internal } from "../_generated/api";
import { sendTelegram } from "./eve";

const internalAny = internal as any;

const tgButton = v.object({
  text: v.string(),
  callback_data: v.string(),
});

const notifyArgs = {
  userId: v.id("users"),
  text: v.string(),
  tgButtons: v.optional(v.array(v.array(tgButton))),
};

type NotifyChannel = "imessage" | "telegram";
type NotifyEnv = Record<string, string | undefined>;

function loudMissing(message: string): never {
  console.error(message);
  throw new Error(message);
}

export function notifyEnvForChannel(
  channel: "telegram",
  env?: NotifyEnv,
): { token: string };
export function notifyEnvForChannel(
  channel: "imessage",
  env?: NotifyEnv,
): { keyId: string; secret: string; fromNumber: string };
export function notifyEnvForChannel(channel: NotifyChannel, env: NotifyEnv = process.env) {
  if (channel === "telegram") {
    const token = env.TELEGRAM_BOT_TOKEN;
    if (!token) loudMissing("TELEGRAM_BOT_TOKEN not configured");
    return { token };
  }

  const keyId = env.SENDBLUE_API_KEY_ID;
  const secret = env.SENDBLUE_API_SECRET_KEY;
  const fromNumber = env.SENDBLUE_FROM_NUMBER;
  if (!keyId || !secret || !fromNumber) {
    loudMissing("SENDBLUE_API_KEY_ID / SENDBLUE_API_SECRET_KEY / SENDBLUE_FROM_NUMBER not configured");
  }
  return { keyId, secret, fromNumber };
}

async function sendImessage(opts: {
  number: string;
  content: string;
  keyId: string;
  secret: string;
  fromNumber: string;
}) {
  const res = await fetch("https://api.sendblue.co/api/send-message", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "sb-api-key-id": opts.keyId,
      "sb-api-secret-key": opts.secret,
    },
    body: JSON.stringify({
      number: opts.number,
      from_number: opts.fromNumber,
      content: opts.content,
    }),
  });
  if (!res.ok) {
    throw new Error(`sendblue notify HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
}

export const notifyUser = internalAction({
  args: notifyArgs,
  returns: v.null(),
  handler: async (ctx, { userId, text, tgButtons }) => {
    const binding: {
      channel: NotifyChannel;
      address: string;
      lastInboundAt: number | null;
    } | null = await ctx.runQuery(internalAny.lib.identity.freshestVerifiedBinding, { userId });
    if (!binding) throw new Error(`no verified channel binding for user ${userId}`);

    const body = text.trim();
    if (!body) return null;

    if (binding.channel === "telegram") {
      const cfg = notifyEnvForChannel("telegram");
      const ok = await sendTelegram({
        token: cfg.token,
        chatId: binding.address,
        text: body,
        replyMarkup: tgButtons ? { inline_keyboard: tgButtons } : undefined,
      });
      if (!ok) throw new Error("telegram notify failed");
      return null;
    }

    const cfg = notifyEnvForChannel("imessage");
    await sendImessage({
      number: binding.address,
      content: body,
      keyId: cfg.keyId,
      secret: cfg.secret,
      fromNumber: cfg.fromNumber,
    });
    return null;
  },
});
