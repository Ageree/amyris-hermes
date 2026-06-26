// Runnable check for the drainer's brain client (lib/eve.ts). No framework.
//   EVE_INGRESS_SECRET=... node --experimental-strip-types scripts/eve.check.ts
// Proves end-to-end against the LIVE deployed Eve agent: buildMessage shape, a real
// brain round-trip with NDJSON parsing, and that injected history is honored. Telegram
// is checked offline (empty + bogus-token graceful paths) so the check never spams.
import assert from "node:assert";
import { buildMessage, callEve, sendTelegram, type Turn } from "../convex/lib/eve.ts";

const EVE_URL = process.env.EVE_URL ?? "https://amyris-eve-core.vercel.app";
const SECRET = process.env.EVE_INGRESS_SECRET ?? "";

function checkBuildMessage() {
  assert.equal(buildMessage([], "привет"), "привет", "no history → raw text");
  const hist: Turn[] = [{ text: "меня зовут Лев", reply: "приятно, Лев" }];
  const m = buildMessage(hist, "как меня зовут?");
  assert.ok(m.includes("пользователь: меня зовут Лев"), "history user line");
  assert.ok(m.includes("ты: приятно, Лев"), "history assistant line");
  assert.ok(m.trim().endsWith("как меня зовут?"), "current message last");
  console.log("✓ buildMessage shape");
}

async function checkTelegramOffline() {
  assert.equal(await sendTelegram({ token: "x", chatId: "1", text: "  " }), false, "empty → false");
  // Bogus token → Bot API rejects; must degrade to false, never throw.
  const ok = await sendTelegram({ token: "0:bogus", chatId: "1", text: "hi" });
  assert.equal(ok, false, "bogus token → false (graceful)");
  console.log("✓ sendTelegram graceful failure");
}

async function checkCallEveLive() {
  if (!SECRET) {
    console.log("• skip live callEve (EVE_INGRESS_SECRET unset)");
    return;
  }
  // Inject a fact via history; the brain should answer from it, proving memory feed.
  const history: Turn[] = [{ text: "мой любимый цвет — бирюзовый", reply: "запомнил: бирюзовый" }];
  const reply = await callEve({
    baseUrl: EVE_URL,
    secret: SECRET,
    history,
    text: "какой мой любимый цвет? ответь одним словом.",
  });
  assert.ok(reply && reply.length > 0, "non-empty reply");
  assert.ok(/бирюз/i.test(reply), `history honored (got: ${reply})`);
  console.log(`✓ callEve live + history honored → "${reply.slice(0, 60)}"`);
}

async function main() {
  checkBuildMessage();
  await checkTelegramOffline();
  await checkCallEveLive();
  console.log("ALL CHECKS PASSED");
}
main().catch((e) => {
  console.error("CHECK FAILED:", e instanceof Error ? e.message : e);
  process.exit(1);
});
