// Self-check for the drainer's order wiring (offline, deterministic). The expensive
// parts are proven elsewhere: classifyOrder live 5/5, the browser engine builds a real
// cart (eda_order.py --self-check). This pins the two pure pieces of the glue: the
// ORDER_HINT prefilter (bias-to-recall) and the ok/fail reply branch.
// Run: source the drainer env first (so the module's top-level env checks pass), then
//   node control-plane/drainer/order-glue.test.mjs
import assert from "node:assert";
import { ORDER_HINT, formatOrderReply } from "./drainer.mjs";

// --- ORDER_HINT: order-ish phrases pass, ordinary chat is skipped ---
for (const t of ["закажи чизбургер на тверскую 7", "хочу пиццу пепперони домой", "привези воды", "оформи доставку"])
  assert.ok(ORDER_HINT.test(t), `should match: ${t}`);
for (const t of ["как дела?", "сколько сейчас времени", "расскажи анекдот", "спасибо!"])
  assert.ok(!ORDER_HINT.test(t), `should NOT match: ${t}`);

// --- formatOrderReply: success carries cart + payment-deferred note ---
const ok = formatOrderReply({ ok: true, final_result: "Чизбургер 113₽, корзина собрана" });
assert.ok(ok.includes("113₽"), "success keeps the cart");
assert.ok(ok.includes("оплати"), "success defers payment");

// --- failure stays honest, no payment note ---
const fail = formatOrderReply({ ok: false, status: "failed" });
assert.ok(/не получилось/.test(fail), "failure is explicit");
assert.ok(!fail.includes("оплати"), "failure offers no payment");

console.log("order-glue self-check PASS");
