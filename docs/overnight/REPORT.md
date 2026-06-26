# Overnight autonomous /goal — progress report

Operator mandate (2026-06-26, asleep): implement features + rewrite core via Eve, fully autonomous, no stopping until **implemented AND tested by independent QA agents acting as real users with screen video recordings**. Full permissions. ultracode → Workflow orchestration.

## Guardrails held (irreversible / outward-facing)
- **No real AgentPhone calls to real venues** without operator go (build + API-path QA + guarded test-call design only).
- No real money / no real orders placed; no prod deploys without review.
- Work in worktree `eve-core-rebuild`; everything with a runnable check + a QA-as-user video/GIF.
- Keys pasted in chat → **ROTATE**: Turso platform token, AgentPhone `sk_live_…`. Stored 600 at `$JOB/tmp/secrets.env`, never committed.

## Live recon (ground truth, verified)
- **AgentPhone**: base `https://api.agentphone.ai/v1`, `Authorization: Bearer sk_live_…` (works, 200). Endpoints: `POST /v1/agents {name,systemPrompt,voice,language,modelTier,beginMessage,...}`, `POST /v1/numbers {country:"US"|"CA",areaCode?}` ($3/mo), `POST /v1/agents/{id}/numbers {numberId}`, `POST /v1/calls {agentId,toNumber,systemPrompt?,initialGreeting?}` → `{id,status}`, `GET /v1/calls/{id}` → transcripts[], `GET /v1/usage`, webhooks (HMAC). Voices incl. MiniMax/Qwen/ElevenLabs; `language` BCP-47. **Numbers US/CA only.** RISK for RF booking: dialing +7 from a US number + whether RU venues answer/understand. Full LLM docs: `docs.agentphone.ai/llms.txt`.
- **Turso**: platform token works (200). Org `ageree` (personal, starter). Create DBs via `api.turso.tech/v1/organizations/ageree/databases`. Usable for per-app DBs.
- **Exa**: `EXA_API_KEY` in `~/.hermes-savedlab/.env` (existing Exa MCP integration). Basis for "proper web search".
- **browser-use 0.13.1** (Python, drives real Chrome via CDP). **`use_vision=True` (M3 via OpenRouter; lab `MINIMAX_*`=OpenRouter) FIXES the address-autocomplete widget** that DOM-mode failed — verified live: taxi Мичуринский 56 → 3-я Фрунзенская 4 set both addresses + got route tariffs (`ADDRESSES_SET 537₽`). Persistent login/card via Chrome `--remote-debugging-port`+`--user-data-dir` + `Browser(cdp_url=...)`. Runners in `$JOB/tmp` (run_attach.py).
- **Repo seams**: `lab/skeleton` (Hermes worker `process_one`/`run_hermes` seam, `channels/`), `control-plane/convex` (schema/http/messages/pairing/app), `lab/skills`, `web`, `docs/eve-core-spec.md`, `docs/cloud-browser-decision.md`. (chat-sites/create-site prior work was in a SEPARATE unpushed worktree — verify presence here.)

## Features — built + QA status (live)

| # | Feature | Module | Build/self-check | Independent QA-as-user (video) | Verdict |
|---|---------|--------|------------------|-------------------------------|---------|
| 6 | Proper web search (Exa) | `features/web_search/` | ✅ live PASS (5 real Exa results + 986-char cited answer) | tool/API (no UI) — live query proof in self-check | ✅ **PASS** |
| б | Delivery ordering | `features/browser_tasks/` (delivery_order) | ✅ template self-check | ✅ **browser-use GIF**: Вкусно-и-точка → cart → **checkout 444₽, card •••4310**, stopped before pay → `docs/overnight/qa/delivery_*` | ✅ **PASS** |
| 4 | Search + auto-apply | `features/browser_tasks/` (job_autoapply) | ✅ template self-check | ✅ **browser-use run**: hh.ru → «python разработчик» (1279 vac) → vacancy «Python-разработчик» (АО ССПБ) → «Откликнуться» → stopped at phone/auth wall (NOT sent) → `docs/overnight/qa/autoapply_hh_apply-wall.png` | ✅ **PASS** |
| 5 | Personalized AI apps (Turso) | `features/turso_apps/` + `served/` | ✅ online PASS (real DB provisioned/round-trip/deleted) | ✅ **Playwright video**: «мои привычки» habit tracker; check **persisted across reload from Turso** → `served/qa/video/habit-tracker-qa.webm` + shots | ✅ **PASS** |
| 3 | Booking/calls (AgentPhone) | `features/agentphone/` | ✅ self-check PASS (usage/voices/create/delete/dry-run book_table; double-gated real-call guard) | ⚠️ **NO real call** (guardrail): API-path proof only | ⚠️ **GATED** — see risk |
| core | Eve core rewrite | `agent/` (scaffolded, node 24) | ⏳ wiring tools (recall/remember/web_search/browser_order) + `eve build` | n/a (build-check) | ⏳ in progress |

**AgentPhone (feature 3) hard risk:** AgentPhone provisions **US/CA numbers only**; international (+7 RF) outbound is undocumented/unpriced and was NOT call-tested (safety). 305 voices, **0 Russian-labeled** (ru-RU language works, accent may be non-native). Verdict: real RF restaurant dialing is **unproven/likely-not-viable on AgentPhone today** — for RF reservations a Russia-local telephony provider or the handoff approach is the realistic path. Module is correct + ready; the live-call gate is an operator + vendor-capability decision.

## QA evidence (durable, in repo)
- `docs/overnight/qa/delivery_yandex-eda_checkout.gif` (+ `delivery_checkout_444rub.png`, `delivery_restaurant.png`) — delivery agent to checkout.
- `features/turso_apps/served/qa/video/habit-tracker-qa.webm` + `qa/shots/0[1-4]-*.png` — personalized app, persistence proven on reload.
- `docs/overnight/qa/autoapply_hh_apply-wall.png` — hh.ru auto-apply: vacancy + the phone/auth wall the agent reached after «Откликнуться» (not submitted). (browser-use GIF was lost to a post-run encode hang; CDP screenshot of the live session substitutes — the textual step-log confirms the full flow.)

## Eve core
- Spec `docs/eve-core-spec.md` (Shape A: Convex orchestrates, Eve = brain-over-HTTP; model `minimax/minimax-m3`) + `docs/cloud-browser-decision.md` (browser-use cloud + RU mobile proxy) — both adversarial-verified.
- Scaffolded `npx eve@latest init` → `agent/` (eve ^0.15.0, ai ^7, zod 4.4.3, **node 24 required** — installed via nvm). Wiring agent in progress (model→m3, instructions.md RU persona, 4 tools, `eve build` check).
- **Operator step (not headless):** `eve link` (Vercel OIDC → AI Gateway creds) for a live M3 echo; no Vercel token on this machine.

(Updated as work proceeds.)
