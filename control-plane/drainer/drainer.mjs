#!/usr/bin/env node
// Eve-core external drainer — REPLACES the Python worker (worker.py). Polls the SAME
// live Convex queue (messages:claimNextAny, worker-secret) the worker did, routes each
// row to the deployed Eve agent, and sends the reply back over the row's own channel
// (iMessage via Sendblue, Telegram via Bot API), then marks it done. Conversation
// memory = last-N turns injected (messages:recentForUser) — parity with the legacy
// worker. Self-contained plain JS (node 20+ global fetch): no deps, no build, runs
// from a TCC-safe dotfolder under launchd.
//
// Why an external poller and NOT an in-Convex action: the live deployment carries a
// `sites` table that the worktree schema no longer declares (it became `apps`), so a
// Convex push would fail/drop data. The poller reuses the EXISTING live functions
// untouched — zero Convex deploy, zero schema risk. Env from ~/.hermes-savedlab/.env
// (CONVEX_URL, WORKER_SECRET, SENDBLUE_*, TELEGRAM_BOT_TOKEN) + EVE_URL/EVE_INGRESS_SECRET.

import { spawn } from "node:child_process";
import { homedir } from "node:os";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";

const CONVEX = (process.env.CONVEX_URL || "").replace(/\/+$/, "");
const WORKER_SECRET = process.env.WORKER_SECRET || "";
// Scoped (per-user container) mode: when USER_ID is set, the loop claims ONLY this
// tenant's rows via messages:claimNextForUser. Unset → the shared Mac drainer claims
// across all tenants via messages:claimNextAny (behavior unchanged).
const USER_ID = process.env.USER_ID || "";
const EVE_URL = (process.env.EVE_URL || "").replace(/\/+$/, "");
const EVE_SECRET = process.env.EVE_INGRESS_SECRET || "";
const SB_ID = process.env.SENDBLUE_API_KEY_ID || "";
const SB_SECRET = process.env.SENDBLUE_API_SECRET_KEY || "";
const SB_FROM = process.env.SENDBLUE_FROM_NUMBER || "";
const TG_TOKEN = process.env.TELEGRAM_BOT_TOKEN || "";
const IDLE_MS = Number(process.env.DRAINER_IDLE_MS || 1500);
const EVE_TIMEOUT_MS = Number(process.env.DRAINER_EVE_TIMEOUT_MS || 180000);

// ---- Orders (browser-use engine on this Mac) --------------------------------------
// Eve is serverless → can't drive a browser; the Mac can. The drainer detects an
// order intent (cheap M3 classify) and routes it to the proven local executor.
const ORDERS_ENABLED = process.env.ORDERS_ENABLED !== "0"; // kill-switch
// Unified engine: order.py --service {food|grocery|taxi}. (EDA_ORDER_PY kept as a
// back-compat env name in case an old launchd plist still sets it.)
const ORDER_PY =
  process.env.ORDER_PY ||
  process.env.EDA_ORDER_PY ||
  `${homedir()}/.eve-orders/order.py`;
const ORDER_VENV =
  process.env.ORDER_VENV ||
  process.env.EDA_ORDER_VENV ||
  `${homedir()}/.eve-orders/.venv/bin/python`;
const PW_BROWSERS =
  process.env.PLAYWRIGHT_BROWSERS_PATH || `${homedir()}/Library/Caches/ms-playwright`;
const DEFAULT_ADDRESS = process.env.DEFAULT_ORDER_ADDRESS || "Тверская 7";
// When the operator's persistent logged-in Chrome is up, set ORDER_CDP_URL (e.g.
// http://127.0.0.1:9333) → order.py attaches to it (payment-capable). Unset → fresh
// profile, cart/route only. The drainer NEVER passes --pay: a real charge stays a
// per-order operator-confirmed step (safety), so autonomous runs only build the cart.
const ORDER_CDP_URL = process.env.ORDER_CDP_URL || "";
const OR_KEY = process.env.MINIMAX_API_KEY || "";
const OR_BASE = process.env.MINIMAX_BASE_URL || "https://openrouter.ai/api/v1";
const OR_MODEL = process.env.MINIMAX_MODEL || "minimax/minimax-m3";
const ORDER_TIMEOUT_MS = Number(process.env.ORDER_TIMEOUT_MS || 420000); // 7 min cap

const log = (...a) => console.log(new Date().toISOString(), ...a);
const die = (m) => {
  console.error("FATAL:", m);
  process.exit(1);
};
// Env validation runs only when RUN as the loop (see the run-guard at the bottom), NOT
// on import — so the pure-function self-checks can import this module without env set.

// ---- Convex function-call HTTP API (same transport the Python worker used) --------
// Every call is bounded by CONVEX_TIMEOUT_MS: on this host the network/DNS sometimes
// HANGS the TCP connect instead of failing fast, and a bare `await fetch` with no
// timeout would wedge the whole drain loop forever (no claim, no log). The abort turns
// a hung connection into a retryable error the claim loop already handles.
const CONVEX_TIMEOUT_MS = Number(process.env.DRAINER_CONVEX_TIMEOUT_MS || 20000);
async function convex(kind, path, args) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), CONVEX_TIMEOUT_MS);
  try {
    const res = await fetch(`${CONVEX}/api/${kind}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        path,
        args: { workerSecret: WORKER_SECRET, ...args },
        format: "json",
      }),
      signal: ctrl.signal,
    });
    const data = await res.json().catch(() => null);
    if (!res.ok || data?.status === "error") {
      throw new Error(
        data?.errorMessage ?? `convex ${kind} ${path} -> HTTP ${res.status}`,
      );
    }
    return data?.value ?? null;
  } finally {
    clearTimeout(t);
  }
}

// Bound any one-shot POST so a hung TCP connect can't freeze the drain loop AFTER a
// claim (same intermittent-network reason as convex() above — classify/send all run
// inside processRow, on the loop's critical path).
const HTTP_TIMEOUT_MS = Number(process.env.DRAINER_HTTP_TIMEOUT_MS || 30000);
async function tfetch(url, opts = {}, ms = HTTP_TIMEOUT_MS) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

// ---- Eve brain: fresh session + injected history, parse NDJSON reply ---------------
const eveAuth = "Basic " + Buffer.from(`convex:${EVE_SECRET}`).toString("base64");

function buildMessage(history, facts, text) {
  const blocks = [];
  if (facts?.length)
    blocks.push(
      "[что ты уже знаешь об этом человеке]",
      ...facts.map((f) => `- ${f}`),
      "[/память]",
      "",
    );
  if (history?.length) {
    const lines = history.flatMap((t) => [`пользователь: ${t.text}`, `ты: ${t.reply}`]);
    blocks.push(
      "[недавний контекст диалога с этим пользователем]",
      ...lines,
      "[/контекст]",
      "",
    );
  }
  if (!blocks.length) return text;
  blocks.push("текущее сообщение пользователя:", text);
  return blocks.join("\n");
}

// ---- Durable facts: a tiny per-user store the drainer injects (recall) + harvests ---
// from the brain's reply (`[[remember:факт]]`). Convex can't host it (the worktree
// schema isn't safely deployable — it would drop `sites`), and Eve's generic channel
// gives tools no tenant userId, so the drainer owns it — same inject-preamble +
// parse-marker pattern it already uses for history and rich tokens.
// ponytail: single-host JSON file (the drainer IS single-host; the serial loop means no
// concurrent writes). Ceiling = not shared with the web/fleet; upgrade = a Convex `facts`
// table once the schema is reconciled and deployable.
const FACTS_FILE =
  process.env.DRAINER_FACTS_FILE || `${homedir()}/.eve-drainer/facts.json`;
const FACTS_PER_USER = Number(process.env.DRAINER_FACTS_PER_USER || 50);
const RE_REMEMBER = /\[\[remember:([^\]\n]+?)\]\]/gi;
const SM_KEY = process.env.SUPERMEMORY_API_KEY || "";
const SM_BASE = (
  process.env.SUPERMEMORY_BASE_URL || "https://api.supermemory.ai"
).replace(/\/+$/, "");
const SM_ENABLED = process.env.SUPERMEMORY_ENABLED !== "0";
const SM_WRITE_ENABLED = process.env.SUPERMEMORY_WRITE_ENABLED !== "0";
const SM_LIMIT = Number(process.env.SUPERMEMORY_SEARCH_LIMIT || 8);

const smTag = (key) =>
  `hermes:user:${String(key || "unknown")
    .replace(/[^a-zA-Z0-9_.:-]+/g, "-")
    .slice(0, 96)}`;

async function smPost(path, body) {
  if (!(SM_ENABLED && SM_KEY)) throw new Error("SUPERMEMORY_API_KEY not set");
  const r = await tfetch(`${SM_BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${SM_KEY}` },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error(`supermemory ${path} HTTP ${r.status}`);
  return data;
}

function smItems(data) {
  if (Array.isArray(data)) return data;
  if (!data || typeof data !== "object") return [];
  for (const k of ["results", "memories", "documents", "items", "data"]) {
    if (Array.isArray(data[k])) return data[k];
  }
  return [];
}

function smText(item) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return "";
  for (const k of ["memory", "content", "chunk", "text", "summary", "title"]) {
    if (typeof item[k] === "string" && item[k].trim()) return item[k].trim();
  }
  return (
    smText(item.document) ||
    (typeof item.memory === "object" ? smText(item.memory) : "")
  );
}

async function recallFacts(key, query) {
  const local = factsFor(key);
  if (!(SM_ENABLED && SM_KEY && key)) return local;
  const body = {
    q: query || "user profile preferences facts",
    limit: SM_LIMIT,
    containerTag: smTag(key),
    searchMode: "hybrid",
  };
  for (const path of ["/v4/search", "/v3/search"]) {
    try {
      const remote = smItems(await smPost(path, body))
        .map(smText)
        .filter(Boolean)
        .slice(0, SM_LIMIT);
      return [...new Set([...remote, ...local])].slice(0, SM_LIMIT);
    } catch (e) {
      log(`supermemory recall via ${path} failed: ${e.message}`);
    }
  }
  return local;
}

async function rememberRemote(key, content, kind) {
  const text = (content || "").trim();
  if (!(SM_ENABLED && SM_WRITE_ENABLED && SM_KEY && key && text)) return false;
  const metadata = { kind };
  const tag = smTag(key);
  const customId = `${kind}:${key}:${createHash("sha256").update(text).digest("hex").slice(0, 32)}`;
  for (const [path, body] of [
    ["/v4/memories", { memories: [{ content: text, metadata }], containerTag: tag }],
    ["/v3/documents", { content: text, containerTag: tag, metadata, customId }],
  ]) {
    try {
      await smPost(path, body);
      return true;
    } catch (e) {
      log(`supermemory write via ${path} failed: ${e.message}`);
    }
  }
  return false;
}

function loadFacts() {
  try {
    return existsSync(FACTS_FILE) ? JSON.parse(readFileSync(FACTS_FILE, "utf8")) : {};
  } catch {
    return {};
  }
}
function factsFor(key) {
  if (!key) return [];
  return (loadFacts()[key] || []).map((f) => f.fact);
}
function addFact(key, fact) {
  const f = (fact || "").trim();
  if (!key || !f) return;
  const db = loadFacts();
  const list = db[key] || [];
  if (list.some((x) => x.fact === f)) return; // exact dedup
  list.push({ fact: f, at: Date.now() });
  db[key] = list.slice(-FACTS_PER_USER); // keep newest N
  try {
    writeFileSync(FACTS_FILE, JSON.stringify(db));
  } catch (e) {
    log(`facts write failed: ${e.message}`);
  }
}
// Pull `[[remember:…]]` markers out of the reply (so the user never sees them) and
// return the cleaned text + the harvested facts.
function extractMemories(reply) {
  const memories = [];
  const cleaned = (reply || "")
    .replace(RE_REMEMBER, (_, f) => {
      const t = f.trim();
      if (t) memories.push(t);
      return "";
    })
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { cleaned, memories };
}

// Reply selection (pure, unit-tested): a turn emits one or more `message.completed`
// events. Prefer the final answer (finishReason != "tool-calls"); fall back to a
// tool-call ack so an elicitation turn still yields SOME text instead of a dropped
// reply; "" only if Eve produced no text at all (→ caller retries once).
function foldEvent(state, ev) {
  if (ev?.type === "message.completed") {
    const m = ev.data?.message;
    if (m) {
      state.any = m;
      if (ev.data?.finishReason !== "tool-calls") state.stop = m;
    }
  }
  return state;
}
function selectReply(state) {
  return state.stop || state.any || "";
}

async function readEveReply(sessionId, signal) {
  const res = await fetch(`${EVE_URL}/eve/v1/session/${sessionId}/stream`, {
    headers: { authorization: eveAuth, accept: "application/x-ndjson" },
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`eve stream HTTP ${res.status}`);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  const state = { stop: "", any: "" };
  const consume = (line) => {
    line = line.trim();
    if (!line) return false;
    let ev;
    try {
      ev = JSON.parse(line);
    } catch {
      return false;
    }
    foldEvent(state, ev);
    return ev.type === "session.waiting" && selectReply(state) !== "";
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl);
      buf = buf.slice(nl + 1);
      if (consume(line)) {
        await reader.cancel().catch(() => {});
        return selectReply(state);
      }
    }
  }
  if (buf) consume(buf);
  return selectReply(state); // "" if Eve produced no text at all
}

// ponytail: a fresh Vercel serverless deploy COLD-STARTS — the first call can end
// with no answer (observed once, ~123s). One retry on an empty reply (warm hit)
// makes a quiet-period first message robust instead of silently failing.
async function callEve(history, facts, text) {
  const message = buildMessage(history, facts, text);
  let lastErr;
  for (let attempt = 0; attempt < 2; attempt++) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), EVE_TIMEOUT_MS);
    try {
      const res = await fetch(`${EVE_URL}/eve/v1/session`, {
        method: "POST",
        headers: { authorization: eveAuth, "content-type": "application/json" },
        body: JSON.stringify({ message }),
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error(`eve session HTTP ${res.status}`);
      const data = await res.json();
      if (!data.sessionId) throw new Error("eve session: no sessionId");
      const reply = await readEveReply(data.sessionId, ctrl.signal);
      if (reply) return reply;
      lastErr = new Error("eve stream ended with no answer");
      if (attempt === 0) log("eve empty reply — retrying once (cold start?)");
    } catch (e) {
      lastErr = e;
      if (attempt === 0) log(`eve call failed (${e.message}) — retrying once`);
    } finally {
      clearTimeout(t);
    }
  }
  throw lastErr ?? new Error("eve: no answer after retry");
}

// ---- Rich messages: parse the brain's flat reply into ordered parts ----------------
// Ported from lab/skeleton/channels/rich.py (the SHIPPED Hermes convention) — SAME
// tokens, so the brain needs no new protocol and a token-less reply degrades to one
// text part (the plain-text path). Tokens: a LEADING `[[react:EMOJI]]` → reaction;
// a ```poll\nQ\nopt…``` fence → poll; `![alt](url)` or a bare http(s) image URL
// (.png/.jpg/.jpeg/.gif/.webp) → image; everything else → text. Markdown LINKS stay
// opaque text so an image-extension URL inside `[t](…)` is not shredded into an image.
const RE_REACT = /^\s*\[\[react:([^\]\n]+?)\]\]\s*/;
const RE_POLL = /```poll[ \t]*\r?\n([\s\S]*?)\r?\n?```/g;

function stripLeadingReactions(reply) {
  const reactions = [];
  let rest = reply;
  for (;;) {
    const m = RE_REACT.exec(rest);
    if (!m) break;
    const emoji = m[1].trim();
    if (emoji) reactions.push({ t: "react", emoji });
    rest = rest.slice(m[0].length);
  }
  return [reactions, rest];
}

function splitImages(text) {
  // Earliest-first scan over {md image, md link, bare image url}; a md link is kept as
  // opaque text so the bare-URL scan can't peek inside its parens.
  const out = [];
  let pos = 0;
  const reImg = /!\[[^\]]*\]\((\S+?)\)/g;
  const reLink = /(?<!!)\[[^\]]*\]\(\S+?\)/g;
  const reBare = /https?:\/\/\S+?\.(?:png|jpe?g|gif|webp)(?:\?\S*)?/gi;
  for (;;) {
    reImg.lastIndex = reLink.lastIndex = reBare.lastIndex = pos;
    const cands = [reImg.exec(text), reLink.exec(text), reBare.exec(text)].filter(
      Boolean,
    );
    if (!cands.length) break;
    const m = cands.reduce((a, b) => (b.index < a.index ? b : a)); // earliest; md wins ties
    if (m.index > pos) out.push({ t: "text", text: text.slice(pos, m.index) });
    if (m[0][0] === "[")
      out.push({ t: "text", text: m[0] }); // md link → opaque text
    else out.push({ t: "image", src: m[0][0] === "!" ? m[1] : m[0] });
    pos = m.index + m[0].length;
  }
  if (pos < text.length) out.push({ t: "text", text: text.slice(pos) });
  return out;
}

function parsePoll(block) {
  const lines = block
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  if (lines.length < 2) return null; // need a question + at least one option
  const [question, ...options] = lines;
  return { t: "poll", question, options };
}

function mergeText(parts) {
  const out = [];
  let buf = [];
  const flush = () => {
    if (!buf.length) return;
    const m = buf.join("").trim();
    if (m) out.push({ t: "text", text: m });
    buf = [];
  };
  for (const p of parts) {
    if (p.t === "text") buf.push(p.text);
    else {
      flush();
      out.push(p);
    }
  }
  flush();
  return out;
}

function parseRich(reply) {
  if (reply == null) return [];
  const [reactions, body] = stripLeadingReactions(reply);
  const parts = [...reactions];
  let pos = 0,
    m;
  RE_POLL.lastIndex = 0;
  while ((m = RE_POLL.exec(body))) {
    const before = body.slice(pos, m.index);
    if (before) parts.push(...splitImages(before));
    const poll = parsePoll(m[1]);
    parts.push(...(poll ? [poll] : splitImages(m[0]))); // malformed fence → keep as text
    pos = m.index + m[0].length;
  }
  const tail = body.slice(pos);
  if (tail) parts.push(...splitImages(tail));
  const merged = mergeText(parts);
  if (!merged.length && (reply || "").trim())
    return [{ t: "text", text: reply.trim() }];
  return merged;
}

// Sendblue's /send-reaction accepts only these 6 tapbacks. Map the brain's free-form
// emoji onto the closest one; an unmappable emoji is SKIPPED (never a wrong sentiment).
const TAPBACKS = new Set(["love", "like", "dislike", "laugh", "emphasize", "question"]);
const EMOJI_TO_TAPBACK = {
  "❤️": "love",
  "❤": "love",
  "🩷": "love",
  "😍": "love",
  "🥰": "love",
  "💕": "love",
  "💖": "love",
  "💗": "love",
  "♥️": "love",
  "👍": "like",
  "🙂": "like",
  "✅": "like",
  "👌": "like",
  "👎": "dislike",
  "😂": "laugh",
  "🤣": "laugh",
  "😆": "laugh",
  "😅": "laugh",
  "😄": "laugh",
  "😹": "laugh",
  "‼️": "emphasize",
  "❗": "emphasize",
  "❗️": "emphasize",
  "🔥": "emphasize",
  "💯": "emphasize",
  "⚡": "emphasize",
  "🙌": "emphasize",
  "❓": "question",
  "❔": "question",
  "🤔": "question",
};
function emojiToTapback(emoji) {
  const e = (emoji || "").trim();
  if (TAPBACKS.has(e.toLowerCase())) return e.toLowerCase(); // literal `[[react:love]]`
  return EMOJI_TO_TAPBACK[e] || null;
}

const isRemote = (s) => typeof s === "string" && /^https?:\/\//.test(s);
const pollToText = (p) =>
  [p.question, ...p.options.map((o, i) => `${i + 1}. ${o}`)].join("\n");

// ---- Channel send -----------------------------------------------------------------
// content XOR mediaUrl: a media send carries `media_url` (real iMessage attachment),
// otherwise plain `content`. Only http(s) media is allowed (file-exfil guard).
async function sendImessage(toNumber, content, mediaUrl) {
  if (!SB_ID || !SB_SECRET || !SB_FROM) throw new Error("SENDBLUE_* not configured");
  const body = { number: toNumber, from_number: SB_FROM };
  if (mediaUrl) body.media_url = mediaUrl;
  else body.content = content;
  const r = await tfetch("https://api.sendblue.co/api/send-message", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "sb-api-key-id": SB_ID,
      "sb-api-secret-key": SB_SECRET,
    },
    body: JSON.stringify(body),
  });
  if (!r.ok)
    throw new Error(`sendblue HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return true;
}

// Tapback on the user's inbound message (its raw Sendblue handle). Best-effort.
async function sendReaction(messageHandle, tapback) {
  if (!SB_ID || !SB_SECRET || !SB_FROM) return false;
  const r = await tfetch("https://api.sendblue.co/api/send-reaction", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "sb-api-key-id": SB_ID,
      "sb-api-secret-key": SB_SECRET,
    },
    body: JSON.stringify({
      from_number: SB_FROM,
      message_handle: messageHandle,
      reaction: tapback,
    }),
  });
  return r.ok;
}

async function sendTelegram(chatId, text) {
  const api = `https://api.telegram.org/bot${TG_TOKEN}`;
  const post = async (m, p) =>
    (
      await tfetch(`${api}/${m}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(p),
      })
    ).ok;
  try {
    if (
      await post("sendRichMessage", {
        chat_id: chatId,
        rich_message: { markdown: text },
      })
    )
      return true;
  } catch {}
  if (!(await post("sendMessage", { chat_id: chatId, text })))
    throw new Error("telegram send failed");
  return true;
}

async function sendTelegramPhoto(chatId, photoUrl, caption) {
  const api = `https://api.telegram.org/bot${TG_TOKEN}`;
  return (
    await tfetch(`${api}/sendPhoto`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        photo: photoUrl,
        caption: caption || undefined,
      }),
    })
  ).ok;
}

// One plain text bubble over the row's own channel (the pre-rich behavior — throws so
// processRow can fail() the row).
async function sendText(row, text) {
  if (row.channel === "telegram") await sendTelegram(row.replyTarget, text);
  else await sendImessage(row.replyTarget, text);
}

// Parse the brain reply into rich parts and render each over the row's channel. A
// token-less reply is exactly one text part → identical to the old plain-text send
// (still throws on failure). Genuine rich replies render best-effort per part (one bad
// part must not drop the rest — mirrors the shipped send_rich).
async function sendReply(row, text) {
  const parts = parseRich(text);
  if (parts.length === 1 && parts[0].t === "text") return sendText(row, parts[0].text);

  const isImessage = row.channel !== "telegram";
  // A reaction targets the inbound's RAW Sendblue handle — only valid on iMessage rows
  // whose handle is unprefixed (telegram=`tg:…`, photon test rows=`photon:…`).
  const reactTarget =
    isImessage && row.handle && !/^(tg|photon):/.test(row.handle) ? row.handle : null;
  for (const p of parts) {
    try {
      if (p.t === "react") {
        const tb = emojiToTapback(p.emoji);
        if (reactTarget && tb) await sendReaction(reactTarget, tb);
        continue; // telegram / unmappable / no-target → skip (never a wrong tapback)
      }
      if (p.t === "poll") {
        await sendText(row, pollToText(p));
        continue;
      }
      if (p.t === "image") {
        if (!isRemote(p.src)) {
          await sendText(row, p.src);
          continue;
        } // refuse non-remote
        if (isImessage) {
          try {
            await sendImessage(row.replyTarget, null, p.src);
          } catch {
            await sendImessage(row.replyTarget, p.src);
          } // fallback: URL auto-unfurls
        } else if (!(await sendTelegramPhoto(row.replyTarget, p.src, ""))) {
          await sendTelegram(row.replyTarget, p.src);
        }
        continue;
      }
      await sendText(row, p.text);
    } catch (e) {
      log(`sendReply part(${p.t}) failed id=${row.id}: ${e.message}`);
    }
  }
}

// Cheap keyword prefilter (bias to recall) so the ~3-5s M3 classify never runs on
// ordinary chat — only on order-ish messages. A missed paraphrase just goes to Eve chat.
// NB: NO \b anchor — JS \b is defined via \w (ASCII-only, even under the u flag), so a
// \b before a Cyrillic letter never matches and would zero out EVERY Russian order phrase.
// Plain substring alternation is exactly right for a bias-to-recall prefilter anyway.
const ORDER_HINT =
  /(закаж|заказ|оформи|доставк|купи|купить|привез|принеси|поесть|пиццу|пицц|суши|роллы|бургер|шаурм|воды|продукт|лавк|вкусвилл|самокат|такси|убер|еда|еды|еду)/i;

// ---- Order intent: cheap M3 classify (reasoning OFF) ------------------------------
// Returns {is_order, service, address, item, from, to}. food/grocery use address+item;
// taxi uses from+to. Any field may be null (→ defaults / a clarifying ask).
async function classifyOrder(text) {
  if (!ORDERS_ENABLED || !OR_KEY) return { is_order: false };
  if (!ORDER_HINT.test(text || "")) return { is_order: false }; // fast path: ordinary chat
  const sys =
    "Ты классификатор. Пользователь пишет ассистенту. Определи, просит ли он СЕЙЧАС оформить " +
    "реальный заказ: доставку ЕДЫ из ресторана (food), продукты из магазина/Лавки (grocery), " +
    "или вызвать ТАКСИ (taxi). Вопрос/болтовня — не заказ. " +
    'Ответь СТРОГО JSON: {"is_order":bool,"service":"food|grocery|taxi|null","address":str|null,' +
    '"item":str|null,"from":str|null,"to":str|null}. ' +
    "Для food/grocery: address — адрес доставки если назван, item — что заказать. " +
    "Для taxi: from — откуда, to — куда (если названы), иначе null.";
  try {
    const r = await tfetch(`${OR_BASE}/chat/completions`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${OR_KEY}`,
      },
      body: JSON.stringify({
        model: OR_MODEL,
        messages: [
          { role: "system", content: sys },
          { role: "user", content: text },
        ],
        temperature: 0,
        max_tokens: 160,
        response_format: { type: "json_object" },
        extra_body: { reasoning: { enabled: false } },
        reasoning: { enabled: false },
      }),
    });
    const j = await r.json();
    const content = j?.choices?.[0]?.message?.content || "{}";
    const out = JSON.parse(content.replace(/```json|```/g, "").trim());
    const service = ["food", "grocery", "taxi"].includes(out.service)
      ? out.service
      : null;
    return {
      is_order: !!out.is_order,
      service,
      address: out.address,
      item: out.item,
      from: out.from,
      to: out.to,
    };
  } catch (e) {
    log("classifyOrder error:", e.message);
    return { is_order: false };
  }
}

// ---- Run the local browser-use executor (order.py), parse its JSON result ---------
// Routes by service: food/grocery pass --address/--item, taxi passes --from/--to.
// ORDER_CDP_URL (if set) flows through the env → order.py attaches to the persistent
// logged-in Chrome. NEVER passes --pay (autonomous = cart/route only; pay is operator-gated).
function runOrder(service, params) {
  return new Promise((resolve) => {
    const args = [ORDER_PY, "--service", service, "--max-steps", "34"];
    if (service === "taxi") args.push("--from", params.from, "--to", params.to);
    else args.push("--address", params.address, "--item", params.item);
    const env = { ...process.env, PLAYWRIGHT_BROWSERS_PATH: PW_BROWSERS };
    if (ORDER_CDP_URL) env.ORDER_CDP_URL = ORDER_CDP_URL;
    const child = spawn(ORDER_VENV, args, { env });
    let out = "",
      err = "";
    const t = setTimeout(() => {
      child.kill("SIGKILL");
    }, ORDER_TIMEOUT_MS);
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("close", (code) => {
      clearTimeout(t);
      try {
        return resolve(JSON.parse(out.trim()));
      } catch {
        return resolve({
          ok: false,
          status: "error",
          error: `exit ${code}: ${err.slice(-200)}`,
        });
      }
    });
  });
}

// A blocking signal from order.py (`needs`) → a friendly instruction. NEVER leaks the
// raw engine signal; the live-view handoff URL is appended separately after minting.
const NEEDS_MSG = {
  NEED_LOGIN:
    "нужно один раз войти в Яндекс и привязать карту в твоём браузере — после входа повтори заказ, и дальше всё соберу сам.",
  NEED_CARD: "не вижу привязанной карты в Яндексе — добавь карту, и я закончу заказ.",
  NEED_3DS:
    "банк просит подтверждение (3-D Secure) — подтверди в приложении банка и скажи «повтори».",
  WEB_NO_ORDER: "через сайт оформить не вышло — попробую иначе или подскажи детали.",
};

// Pure: turn an engine result into the user-facing reply (the one branch with logic).
// A success carries the cart/route + a checkout-deferred note; a blocking `needs`
// becomes a friendly instruction; any other failure stays honest.
function formatOrderReply(res, service = "food") {
  if (res.ok && res.final_result) {
    const tail =
      service === "taxi"
        ? "\n\nне вызывал — скажи «вызывай», когда готов (оплата привязанной картой)."
        : "\n\nоплату не трогал — скажи «оплати», когда будешь готов.";
    return `${res.final_result}${tail}`;
  }
  if (res.needs && NEEDS_MSG[res.needs]) return NEEDS_MSG[res.needs];
  const what = service === "taxi" ? "рассчитать поездку" : "собрать заказ";
  return `не получилось ${what} автоматически (${res.status || "ошибка"}). попробую иначе или подскажи детали.`;
}

async function appendLoginHandoff(reply, res, row, deps = {}) {
  if (res?.needs !== "NEED_LOGIN") return reply;
  const userId = row?.userId || USER_ID;
  if (!userId) return reply;
  const callConvex = deps.convex || convex;
  const writeLog = deps.log || log;
  try {
    const handoff = await callConvex("mutation", "fleet:mintLoginHandoff", { userId });
    const url = typeof handoff?.url === "string" ? handoff.url : "";
    if (!url) throw new Error("empty handoff url");
    return `${reply}\n\nВременная ссылка для входа (15 минут): ${url}`;
  } catch (e) {
    writeLog(`login handoff mint failed user=${userId}: ${e.message}`);
    return `${reply}\n\nСсылку для входа сейчас не удалось создать; повтори заказ через минуту, и я попробую ещё раз.`;
  }
}

// Pure routing (unit-tested): map an order to the engine's per-service params/ack, or a
// clarifying ask when taxi lacks endpoints. `addr` lets the test pin the default.
function buildOrderArgs(order, addr = DEFAULT_ADDRESS) {
  const service = ["food", "grocery", "taxi"].includes(order.service)
    ? order.service
    : "food";
  if (service === "taxi") {
    if (!order.from || !order.to) {
      return {
        service,
        ask: "куда и откуда едем? напиши «откуда → куда», и я посмотрю цену.",
      };
    }
    return {
      service,
      params: { from: order.from, to: order.to },
      ack: `смотрю такси: ${order.from} → ${order.to}. пара минут…`,
    };
  }
  const address = order.address || addr;
  const item = order.item || "что-нибудь популярное";
  const ack = `принял. ${service === "grocery" ? "лавка" : "еда"}: ${item}${order.address ? "" : ` на ${address}`}. пара минут, собираю…`;
  return { service, params: { address, item }, ack };
}

async function handleOrder(row, order) {
  const { service, params, ack, ask } = buildOrderArgs(order);
  if (ask) {
    await sendReply(row, ask);
    await convex("mutation", "messages:complete", { id: row.id, reply: ask });
    return log(`order id=${row.id} taxi missing from/to — asked`);
  }
  await sendReply(row, ack);
  log(
    `order id=${row.id} service=${service} ${JSON.stringify(params)} cdp=${ORDER_CDP_URL ? "on" : "off"} — running engine`,
  );
  // ponytail: blocks the loop ~2-4min/attempt (1 global lock). Upgrade: separate
  // order-worker/queue at >1 concurrent user. Retry once — the address picker is flaky.
  let res = await runOrder(service, params);
  if (!res.ok) {
    log(`order id=${row.id} attempt1 not ok (${res.status}) — retry`);
    res = await runOrder(service, params);
  }
  if (!(res.ok && res.final_result))
    log(`order id=${row.id} FAILED:`, JSON.stringify(res).slice(0, 200));
  const reply = await appendLoginHandoff(formatOrderReply(res, service), res, row);
  await sendReply(row, reply);
  await convex("mutation", "messages:complete", { id: row.id, reply });
  log(`order done id=${row.id} service=${service} ok=${!!res.ok}`);
}

// ---- Drain loop -------------------------------------------------------------------
const defaultProcessDeps = {
  classifyOrder,
  handleOrder,
  convex,
  recallFacts,
  callEve,
  extractMemories,
  addFact,
  rememberRemote,
  sendReply,
  log,
};

function shortCrewFailureReason(error) {
  const msg = String(error?.message || error || "eve failed")
    .replace(/\s+/g, " ")
    .trim();
  return (msg || "eve failed").slice(0, 160);
}

async function failCrewTask(row, error, deps) {
  const reason = shortCrewFailureReason(error);
  try {
    await deps.convex("mutation", "crew:failTask", {
      taskId: row.crewTaskId,
      reason,
    });
  } catch (e) {
    deps.log(`crew failTask failed id=${row.id} task=${row.crewTaskId}: ${e.message}`);
  }
}

async function runEveForRow(row, deps) {
  const userKey = row.userId || row.userNumber; // legacy operator → his number
  const history = await deps.convex("query", "messages:recentForUser", {
    userId: row.userId ?? undefined,
    userNumber: row.userId ? undefined : row.userNumber,
    limit: 10,
  });
  const facts = await deps.recallFacts(userKey, row.text);
  const raw = await deps.callEve(history || [], facts, row.text);
  const { cleaned, memories } = deps.extractMemories(raw); // harvest [[remember:…]] markers
  for (const f of memories) {
    deps.addFact(userKey, f);
    await deps.rememberRemote(userKey, f, "explicit_fact");
  }
  return { userKey, facts, cleaned, memories };
}

async function processCrewRow(row, deps) {
  let turn;
  try {
    turn = await runEveForRow(row, deps);
    if (!turn.cleaned) throw new Error("eve returned empty crew reply");
  } catch (e) {
    await failCrewTask(row, e, deps);
    throw e;
  }

  await deps.convex("mutation", "crew:submitResult", {
    taskId: row.crewTaskId,
    resultText: turn.cleaned,
  });
  await deps.convex("mutation", "messages:complete", { id: row.id, reply: turn.cleaned });
  await deps.rememberRemote(
    turn.userKey,
    `User: ${row.text}\nAssistant: ${turn.cleaned}`,
    "conversation_turn",
  );
  deps.log(
    `crew done id=${row.id} task=${row.crewTaskId} facts=${turn.facts.length}+${turn.memories.length} -> "${turn.cleaned.slice(0, 60)}"`,
  );
}

async function processRow(row, depsArg = {}) {
  const deps = { ...defaultProcessDeps, ...depsArg };
  if (row.crewTaskId) return processCrewRow(row, deps);

  const order = await deps.classifyOrder(row.text);
  if (order.is_order) return deps.handleOrder(row, order);

  const turn = await runEveForRow(row, deps);
  await deps.sendReply(row, turn.cleaned);
  await deps.convex("mutation", "messages:complete", { id: row.id, reply: turn.cleaned });
  await deps.rememberRemote(
    turn.userKey,
    `User: ${row.text}\nAssistant: ${turn.cleaned}`,
    "conversation_turn",
  );
  deps.log(
    `done id=${row.id} ch=${row.channel || "imessage"} facts=${turn.facts.length}+${turn.memories.length} -> "${turn.cleaned.slice(0, 60)}"`,
  );
}

// Pure (unit-tested): pick the claim mutation by mode. USER_ID set → scoped per-user
// container claim (messages:claimNextForUser, userId-pinned, server-side tenant scoping).
// Unset → shared drainer claim across all tenants (messages:claimNextAny, unchanged).
// workerSecret is added by convex(); both mutations return the same claimReturns shape,
// so EVERYTHING downstream (processRow, Eve call, order routing, rich, facts) is identical.
function claimSpec(env = process.env) {
  const userId = env.USER_ID || "";
  return userId
    ? { path: "messages:claimNextForUser", args: { userId } }
    : { path: "messages:claimNextAny", args: {} };
}

async function main() {
  const claim = claimSpec();
  log(
    `eve-drainer up. convex=${CONVEX} eve=${EVE_URL} claim=${claim.path}${USER_ID ? ` user=${USER_ID}` : ""}`,
  );
  for (;;) {
    let row = null;
    try {
      row = await convex("mutation", claim.path, claim.args);
    } catch (e) {
      log("claim error:", e.message);
      await sleep(IDLE_MS * 2);
      continue;
    }
    if (!row) {
      await sleep(IDLE_MS);
      continue;
    }
    log(
      `claimed id=${row.id} ch=${row.channel || "imessage"} from=${row.userNumber} text="${(row.text || "").slice(0, 60)}"`,
    );
    try {
      await processRow(row);
    } catch (e) {
      log(`FAIL id=${row.id}:`, e.message);
      try {
        await convex("mutation", "messages:fail", {
          id: row.id,
          error: String(e.message).slice(0, 300),
        });
      } catch (e2) {
        log("fail() error:", e2.message);
      }
    }
  }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Only spin the loop when RUN directly; importing (the self-check) just gets the funcs.
import { fileURLToPath } from "node:url";
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  if (!CONVEX || !WORKER_SECRET) die("CONVEX_URL / WORKER_SECRET missing");
  if (!EVE_URL || !EVE_SECRET) die("EVE_URL / EVE_INGRESS_SECRET missing");
  main().catch((e) => die(e.message));
}

export {
  ORDER_HINT,
  formatOrderReply,
  appendLoginHandoff,
  classifyOrder,
  buildOrderArgs,
  parseRich,
  emojiToTapback,
  buildMessage,
  extractMemories,
  factsFor,
  addFact,
  foldEvent,
  selectReply,
  claimSpec,
  processRow,
};
