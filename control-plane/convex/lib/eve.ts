// Pure Eve-brain client + Telegram sender for the Shape-A drainer (spec §2.1).
// NO convex/server imports → importable by the action AND runnable standalone as a
// check (node --experimental-strip-types). Talks the deployed Eve agent's HTTP API:
//   POST /eve/v1/session {message}        -> {sessionId, continuationToken}
//   GET  /eve/v1/session/<id>/stream      -> NDJSON event stream (one JSON per line)
// We create a FRESH session per inbound and inject recent dialogue as context, rather
// than resume a durable session: a tokenless follow-up is rejected (400) and the
// next continuationToken is not re-issued on the wire, so resume is fragile. Fresh +
// injected history is the same approach the legacy Python worker used (worker.py
// recentForUser), and M3's 1M context makes the re-sent transcript negligible.
// ponytail: per-message session, no token state. Ceiling: no cross-window durable
// facts (only the injected N turns). Upgrade path = durable-facts table + a custom
// Eve channel that plumbs the tenant userId into tool ctx (see docs/eve-core-spec §6).

export type Turn = { text: string; reply: string };

// Build the single user message we hand to Eve: a compact transcript preamble of the
// last turns, then the current message. Mirrors the legacy worker's history feed.
export function buildMessage(history: Turn[], text: string): string {
  if (!history.length) return text;
  const lines = history.flatMap((t) => [`пользователь: ${t.text}`, `ты: ${t.reply}`]);
  return [
    "[недавний контекст диалога с этим пользователем]",
    ...lines,
    "[/контекст]",
    "",
    "текущее сообщение пользователя:",
    text,
  ].join("\n");
}

function basicAuth(secret: string): string {
  // HTTP Basic "convex:<secret>" — matches agent/channels/eve.ts httpBasic({username:"convex"}).
  return "Basic " + Buffer.from(`convex:${secret}`).toString("base64");
}

// Read the NDJSON stream until the assistant's turn is final, return the reply text.
// Stops at the first message.completed whose finishReason is not "tool-calls" (that
// is the user-facing answer; tool-call steps stream their own message.completed).
async function readReply(
  base: string,
  secret: string,
  sessionId: string,
  signal: AbortSignal,
): Promise<string> {
  const res = await fetch(`${base}/eve/v1/session/${sessionId}/stream`, {
    headers: { authorization: basicAuth(secret), accept: "application/x-ndjson" },
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`eve stream HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let reply = "";
  const consume = (line: string) => {
    line = line.trim();
    if (!line) return false;
    let ev: { type?: string; data?: { message?: string; finishReason?: string } };
    try {
      ev = JSON.parse(line);
    } catch {
      return false;
    }
    if (ev.type === "message.completed" && ev.data?.finishReason !== "tool-calls") {
      reply = ev.data?.message ?? reply;
    }
    // After a completed answer the session goes to waiting — our turn is done.
    return ev.type === "session.waiting" && reply !== "";
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      if (consume(line)) {
        await reader.cancel().catch(() => {});
        return reply;
      }
    }
  }
  if (buf && consume(buf)) return reply;
  if (!reply) throw new Error("eve stream ended with no answer");
  return reply;
}

/**
 * One full brain turn: create a session with the history-injected message, stream the
 * reply. Bounded by timeoutMs (the stream stays open on session.waiting, so we abort).
 * Throws on transport/auth failure so the caller marks the queue row failed (never a
 * fabricated success).
 */
export async function callEve(opts: {
  baseUrl: string;
  secret: string;
  history: Turn[];
  text: string;
  timeoutMs?: number;
}): Promise<string> {
  const base = opts.baseUrl.replace(/\/+$/, "");
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 120_000);
  try {
    const message = buildMessage(opts.history, opts.text);
    const res = await fetch(`${base}/eve/v1/session`, {
      method: "POST",
      headers: { authorization: basicAuth(opts.secret), "content-type": "application/json" },
      body: JSON.stringify({ message }),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`eve session HTTP ${res.status}`);
    const data = (await res.json()) as { sessionId?: string };
    if (!data.sessionId) throw new Error("eve session: no sessionId");
    return await readReply(base, opts.secret, data.sessionId, ctrl.signal);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Send a Telegram reply via Bot API. Rich-markdown first (Bot API 10.1 sendRichMessage,
 * the raw text as rich_message.markdown — a superset of the markdown the brain emits),
 * falling back to plain sendMessage so a rich failure never loses the reply. Mirrors
 * the legacy TelegramChannel. Best-effort: returns false instead of throwing.
 */
export async function sendTelegram(opts: {
  token: string;
  chatId: string;
  text: string;
  replyMarkup?: unknown;
}): Promise<boolean> {
  const api = `https://api.telegram.org/bot${opts.token}`;
  const body = (opts.text || "").trim();
  if (!body) return false;
  const post = async (method: string, payload: unknown) => {
    const r = await fetch(`${api}/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    return r.ok;
  };
  try {
    if (!opts.replyMarkup && await post("sendRichMessage", { chat_id: opts.chatId, rich_message: { markdown: body } })) {
      return true;
    }
  } catch {
    /* fall through to plain */
  }
  try {
    // Plain text (no parse_mode) — the raw reply renders fine and can't 400 on bad HTML.
    return await post("sendMessage", {
      chat_id: opts.chatId,
      text: body,
      ...(opts.replyMarkup ? { reply_markup: opts.replyMarkup } : {}),
    });
  } catch {
    return false;
  }
}
