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

const CONVEX = (process.env.CONVEX_URL || "").replace(/\/+$/, "");
const WORKER_SECRET = process.env.WORKER_SECRET || "";
const EVE_URL = (process.env.EVE_URL || "").replace(/\/+$/, "");
const EVE_SECRET = process.env.EVE_INGRESS_SECRET || "";
const SB_ID = process.env.SENDBLUE_API_KEY_ID || "";
const SB_SECRET = process.env.SENDBLUE_API_SECRET_KEY || "";
const SB_FROM = process.env.SENDBLUE_FROM_NUMBER || "";
const TG_TOKEN = process.env.TELEGRAM_BOT_TOKEN || "";
const IDLE_MS = Number(process.env.DRAINER_IDLE_MS || 1500);
const EVE_TIMEOUT_MS = Number(process.env.DRAINER_EVE_TIMEOUT_MS || 180000);

const log = (...a) => console.log(new Date().toISOString(), ...a);
const die = (m) => { console.error("FATAL:", m); process.exit(1); };
if (!CONVEX || !WORKER_SECRET) die("CONVEX_URL / WORKER_SECRET missing");
if (!EVE_URL || !EVE_SECRET) die("EVE_URL / EVE_INGRESS_SECRET missing");

// ---- Convex function-call HTTP API (same transport the Python worker used) --------
async function convex(kind, path, args) {
  const res = await fetch(`${CONVEX}/api/${kind}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path, args: { workerSecret: WORKER_SECRET, ...args }, format: "json" }),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok || data?.status === "error") {
    throw new Error(data?.errorMessage ?? `convex ${kind} ${path} -> HTTP ${res.status}`);
  }
  return data?.value ?? null;
}

// ---- Eve brain: fresh session + injected history, parse NDJSON reply ---------------
const eveAuth = "Basic " + Buffer.from(`convex:${EVE_SECRET}`).toString("base64");

function buildMessage(history, text) {
  if (!history?.length) return text;
  const lines = history.flatMap((t) => [`пользователь: ${t.text}`, `ты: ${t.reply}`]);
  return ["[недавний контекст диалога с этим пользователем]", ...lines,
    "[/контекст]", "", "текущее сообщение пользователя:", text].join("\n");
}

async function readEveReply(sessionId, signal) {
  const res = await fetch(`${EVE_URL}/eve/v1/session/${sessionId}/stream`, {
    headers: { authorization: eveAuth, accept: "application/x-ndjson" }, signal,
  });
  if (!res.ok || !res.body) throw new Error(`eve stream HTTP ${res.status}`);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "", reply = "";
  const consume = (line) => {
    line = line.trim();
    if (!line) return false;
    let ev; try { ev = JSON.parse(line); } catch { return false; }
    if (ev.type === "message.completed" && ev.data?.finishReason !== "tool-calls") {
      reply = ev.data?.message ?? reply;
    }
    return ev.type === "session.waiting" && reply !== "";
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
      if (consume(line)) { await reader.cancel().catch(() => {}); return reply; }
    }
  }
  if (buf && consume(buf)) return reply;
  if (!reply) throw new Error("eve stream ended with no answer");
  return reply;
}

async function callEve(history, text) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), EVE_TIMEOUT_MS);
  try {
    const res = await fetch(`${EVE_URL}/eve/v1/session`, {
      method: "POST",
      headers: { authorization: eveAuth, "content-type": "application/json" },
      body: JSON.stringify({ message: buildMessage(history, text) }),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`eve session HTTP ${res.status}`);
    const data = await res.json();
    if (!data.sessionId) throw new Error("eve session: no sessionId");
    return await readEveReply(data.sessionId, ctrl.signal);
  } finally { clearTimeout(t); }
}

// ---- Channel send -----------------------------------------------------------------
async function sendImessage(toNumber, content) {
  if (!SB_ID || !SB_SECRET || !SB_FROM) throw new Error("SENDBLUE_* not configured");
  const r = await fetch("https://api.sendblue.co/api/send-message", {
    method: "POST",
    headers: { "content-type": "application/json", "sb-api-key-id": SB_ID, "sb-api-secret-key": SB_SECRET },
    body: JSON.stringify({ number: toNumber, from_number: SB_FROM, content }),
  });
  if (!r.ok) throw new Error(`sendblue HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return true;
}

async function sendTelegram(chatId, text) {
  const api = `https://api.telegram.org/bot${TG_TOKEN}`;
  const post = async (m, p) => (await fetch(`${api}/${m}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(p),
  })).ok;
  try { if (await post("sendRichMessage", { chat_id: chatId, rich_message: { markdown: text } })) return true; } catch {}
  if (!await post("sendMessage", { chat_id: chatId, text })) throw new Error("telegram send failed");
  return true;
}

// ---- Drain loop -------------------------------------------------------------------
async function processRow(row) {
  const history = await convex("query", "messages:recentForUser", {
    userId: row.userId ?? undefined,
    userNumber: row.userId ? undefined : row.userNumber,
    limit: 10,
  });
  const reply = await callEve(history || [], row.text);
  if (row.channel === "telegram") await sendTelegram(row.replyTarget, reply);
  else await sendImessage(row.replyTarget, reply); // imessage (or legacy null channel)
  await convex("mutation", "messages:complete", { id: row.id, reply });
  log(`done id=${row.id} ch=${row.channel || "imessage"} -> "${reply.slice(0, 60)}"`);
}

async function main() {
  log(`eve-drainer up. convex=${CONVEX} eve=${EVE_URL}`);
  for (;;) {
    let row = null;
    try { row = await convex("mutation", "messages:claimNextAny", {}); }
    catch (e) { log("claim error:", e.message); await sleep(IDLE_MS * 2); continue; }
    if (!row) { await sleep(IDLE_MS); continue; }
    log(`claimed id=${row.id} ch=${row.channel || "imessage"} from=${row.userNumber} text="${(row.text || "").slice(0, 60)}"`);
    try { await processRow(row); }
    catch (e) {
      log(`FAIL id=${row.id}:`, e.message);
      try { await convex("mutation", "messages:fail", { id: row.id, error: String(e.message).slice(0, 300) }); }
      catch (e2) { log("fail() error:", e2.message); }
    }
  }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
main().catch((e) => die(e.message));
