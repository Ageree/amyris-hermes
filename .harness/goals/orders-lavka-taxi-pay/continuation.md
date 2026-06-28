# Continuation — orders-lavka-taxi-pay

## Shipped (turn 1)
- **Unified engine `~/.eve-orders/order.py`** (`--service {food|grocery|taxi}`):
  per-service vision templates (eda/lavka/taxi), `--attach`/`ORDER_CDP_URL` →
  `Browser(cdp_url=…)` (payment-capable persistent profile) else fresh profile,
  `--pay` guard (NEVER types card numbers; NEED_CARD/NEED_3DS/WEB_NO_ORDER stops),
  M3-OpenRouter reasoning-off. Offline `--check-templates` PASS (service→site,
  guards, resolve_cdp attach branch).
- **Drainer routing** (`control-plane/drainer/drainer.mjs`, deployed to
  `~/.eve-drainer/drainer.mjs`, kickstarted, boots clean): `classifyOrder` now emits
  `service: food|grocery|taxi` + `from/to`; pure `buildOrderArgs` routes by service
  (taxi needs both endpoints or asks); `runOrder` spawns order.py per service +
  passes `ORDER_CDP_URL` through; `formatOrderReply` service-aware. Env validation
  moved into the run-guard so self-checks import cleanly.
- **Self-checks**: new `order-route.test.mjs` PASS; all 5 (`reply order-route
  order-glue rich facts`) green + `node --check` clean.
- **Live classify probe** PASS: taxi→from/to, grocery→address+item, food→item,
  chat→not-order.

## Acceptance status
- #1 taxi live browser run: **PASS** — `ok:true`, taxi.yandex.ru route Мичуринский56→
  Фрунзенская4, Эконом от 348₽ (+ full tariff list), no-login/no-pay guard respected,
  15 steps. `$JOB/tmp/taxi_run.json`.
- #2 grocery/Lavka live run: **ENGINE BUILT+CORRECT, blocked by Lavka anti-bot.** Two
  runs (concurrent then SOLO) both hit Lavka's 403 «с вашего IP одновременно много
  запросов». But plain `curl` → lavka/eda/taxi ALL HTTP 200 → the block is BEHAVIORAL
  (headless fingerprint + rapid auto-clicks), NOT an IP/network block. The engine
  drove lavka.yandex.ru and stopped per the captcha guard (steps:4) — code is correct.
  Real Lavka run needs a non-flagged session = **attach-mode on the operator's RU
  logged-in Chrome** → CONVERGES with #6.
- #3 routing+classifier: **PASS** (self-check + live classify)
- #4 attach plumbing: **PASS** (resolve_cdp dry check; live attach pending 9333)
- #5 self-checks + deploy boot: **PASS**
- #6 real PAID order: **OPERATOR-GATED** — needs operator's persistent Chrome
  (port 9333) relaunched + Yandex login + card; currently DEAD.

## Remaining / blocked (BOTH need the operator's persistent Chrome :9333)
- #2 live Lavka cart total: run `order.py --service grocery --attach` once :9333 is up
  (real RU session won't trip Lavka's behavioral anti-bot).
- #6 paid order: lead drives `--attach --pay` to checkout, operator confirms the charge.
- Drainer runs autonomous = cart/route only (never `--pay`); paid step is a
  separate operator-confirmed run driven by the lead.

## Operator ask
Relaunch your logged-in Chrome with remote debugging on port 9333 (Yandex logged in,
VISA linked), then I prove Lavka via attach AND do one operator-confirmed paid order.
