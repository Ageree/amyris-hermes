// Self-check for order routing: buildOrderArgs maps each service to the right engine
// params, taxi without endpoints asks instead of running, and formatOrderReply phrases
// per service. No env needed (drainer.mjs validates env only when run as the loop).
//   node control-plane/drainer/order-route.test.mjs
import assert from "node:assert";
import { buildOrderArgs, formatOrderReply } from "./drainer.mjs";

// 1. food → address+item, default address when none given.
let r = buildOrderArgs({ service: "food", item: "бургер" }, "Тверская 7");
assert.equal(r.service, "food");
assert.deepEqual(r.params, { address: "Тверская 7", item: "бургер" });
assert.ok(/еда/.test(r.ack) && !r.ask);

// 2. grocery → routed distinctly (Лавка ack), explicit address respected.
r = buildOrderArgs({ service: "grocery", address: "Арбат 1", item: "молоко" });
assert.equal(r.service, "grocery");
assert.deepEqual(r.params, { address: "Арбат 1", item: "молоко" });
assert.ok(/лавка/.test(r.ack));

// 3. taxi with both endpoints → from/to params, no ask.
r = buildOrderArgs({ service: "taxi", from: "Мичуринский 56", to: "Фрунзенская 4" });
assert.equal(r.service, "taxi");
assert.deepEqual(r.params, { from: "Мичуринский 56", to: "Фрунзенская 4" });
assert.ok(!r.ask && /такси/.test(r.ack));

// 4. taxi missing an endpoint → ask, never run a half-specified route.
r = buildOrderArgs({ service: "taxi", from: "дом" });
assert.ok(r.ask && !r.params, "taxi without `to` must ask, not run");
r = buildOrderArgs({ service: "taxi" });
assert.ok(r.ask && !r.params);

// 5. unknown/missing service → defaults to food (never silently drops an order).
r = buildOrderArgs({ service: "banana", item: "x" });
assert.equal(r.service, "food");
r = buildOrderArgs({ item: "x" });
assert.equal(r.service, "food");

// 6. formatOrderReply is service-aware: taxi says «вызывай», food/grocery «оплати».
assert.ok(/вызывай/.test(formatOrderReply({ ok: true, final_result: "Эконом 320₽" }, "taxi")));
assert.ok(/оплати/.test(formatOrderReply({ ok: true, final_result: "корзина 444₽" }, "food")));
assert.ok(/рассчитать поездку/.test(formatOrderReply({ ok: false, status: "failed" }, "taxi")));
assert.ok(/собрать заказ/.test(formatOrderReply({ ok: false, status: "failed" }, "grocery")));

// 7. a blocking `needs` signal becomes a friendly instruction (not the generic failure),
//    and NEVER leaks a raw signal token like "NEED_LOGIN" to the user.
const loginReply = formatOrderReply({ ok: false, status: "blocked", needs: "NEED_LOGIN" }, "food");
assert.ok(/войти в Яндекс/.test(loginReply), "NEED_LOGIN → login instruction");
assert.ok(!/NEED_LOGIN/.test(loginReply), "must not leak the raw signal token");
assert.ok(/3-D Secure/.test(formatOrderReply({ ok: false, needs: "NEED_3DS" }, "taxi")));
// an unknown needs falls through to the honest generic failure.
assert.ok(/не получилось/.test(formatOrderReply({ ok: false, needs: "WHATEVER" }, "food")));

console.log("order-route self-check PASS");
