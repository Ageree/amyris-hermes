# Acceptance criteria

Each row is testable. "Autonomous" = lead verifies without operator/real money.
"Operator-gated" = needs the operator's relaunched logged-in Chrome + per-order
payment confirmation (safety) — verified WITH the operator, not in a blind loop.

Engine note: the three services are ONE unified file `~/.eve-orders/order.py`
(`--service {food|grocery|taxi}`) — fewer near-duplicate files, one place for the
attach/pay/reasoning-off logic. service→site mapping lives in its per-service templates.

| # | Criterion | How to verify | Type |
|---|-----------|---------------|------|
| 1 | `order.py --service taxi` does a real browser-use run on taxi.yandex.ru, sets pickup+destination, returns JSON with a fare/route | run `…/.venv/bin/python ~/.eve-orders/order.py --service taxi --from "<A>" --to "<B>"`; stdout JSON has the route + a fare | Autonomous |
| 2 | `order.py --service grocery` does a real browser-use run on lavka.yandex.ru, sets address + adds ≥1 item, returns JSON with a cart total | run it; stdout JSON has a cart total | Autonomous |
| 3 | drainer `buildOrderArgs` routes by `order.service`: food→eda, grocery→lavka, taxi→taxi; `classifyOrder` service enum includes `taxi`; order.py templates target the right site | self-check `order-route.test.mjs` + `order.py --check-templates` PASS + live `classifyOrder("вызови такси…")` → service=taxi | Autonomous |
| 4 | attach mode: env `ORDER_CDP_URL` → `Browser(cdp_url=…)` (persistent logged-in profile) instead of a fresh profile; falls back to fresh if unset | `resolve_cdp` dry self-check in `--check-templates`; live attach when 9333 is up | Autonomous (plumbing) |
| 5 | all drainer self-checks green (`reply`,`order-route`,`order-glue`,`rich`,`facts`) + `node --check` clean; deployed copy at `~/.eve-drainer/drainer.mjs` boots clean | run all `*.test.mjs` + `node --check` + kickstart + read boot log | Autonomous |
| 6 | ONE real PAID order completes end-to-end through the operator's logged-in persistent Chrome (any service), card charged, with the operator's explicit per-order confirmation | lead drives the attached `--attach --pay` run to checkout, operator confirms the charge, verify order placed | Operator-gated |

## Verification commands
- `cd <worktree> && for t in reply order-route order-glue rich facts; do node control-plane/drainer/$t.test.mjs; done`
- `node --check control-plane/drainer/drainer.mjs`
- `~/.eve-orders/.venv/bin/python ~/.eve-orders/order.py --check-templates`
- `PLAYWRIGHT_BROWSERS_PATH=… ~/.eve-orders/.venv/bin/python ~/.eve-orders/order.py --service taxi --from "Мичуринский 56" --to "3-я Фрунзенская 4"`
- `PLAYWRIGHT_BROWSERS_PATH=… ~/.eve-orders/.venv/bin/python ~/.eve-orders/order.py --service grocery --address "Тверская 7" --item "молоко"`
- live `classifyOrder` probe for taxi/grocery routing

## Out of scope (later phase)
- cloud-multitenant browser (browser-use cloud + RU-mobile proxy)
- payment layer #3 (prepaid balance + ЮKassa recurring + ИП/юрлицо KYC)
- unattended autonomous real-money spending (each real charge stays per-order confirmed)
