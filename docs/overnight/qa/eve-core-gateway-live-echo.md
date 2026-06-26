# Eve core — LIVE proof through the **Vercel AI Gateway** (production transport)

Closes gate #2 via the prod transport (not the OpenRouter fallback). Operator
logged into Vercel CLI and created an AI Gateway API key
(`vck_…`, set as `AI_GATEWAY_API_KEY` in `agent/.env.local`, gitignored — **rotate**).

Setup: project linked `nikto256-6851s-projects/amyris-eve-core`; `eve dev --no-ui`
started with `MINIMAX_*` UNSET, so `agent.ts` takes the **gateway-string branch**
(`model = "minimax/minimax-m3"`). The AI-SDK gateway provider auto-reads
`AI_GATEWAY_API_KEY` — **zero code change** vs the OpenRouter run.

## Ground-truth before the run
- `GET ai-gateway.vercel.sh/v1/models` → 294 models incl. `minimax/minimax-m3`.
- Raw `POST /v1/chat/completions` with the key → `"Привет"` (key valid).
- (Earlier, the pulled **OIDC** token 401'd on inference — the operator-created API key fixed it.)

## Turn 1 — plain RU echo through the gateway
Input: `Ответь ровно одним словом: привет` → **«привет»**. No 401, no `MODEL_CALL_FAILED`.

## Turn 2 — multi-step tool use (web_search → Exa) through the gateway
Input: `Найди в интернете: когда был последний запуск SpaceX? Ответь кратко по-русски с датой.`
- `actions.requested`: **web_search** `{query:"последний запуск SpaceX дата 2025"}` → Exa result (8059 chars).
- agent self-corrected for freshness: «Поищу посвежее — последний пуск прямо сейчас.»
- 2nd **web_search** `{query:"SpaceX latest launch today"}` → Exa result (11972 chars).
- `message.completed`: **«последний запуск spacex — 24 июня 2026 года, миссия starlink 17-45: falcon 9 с 24 спутниками starlink стартовала с базы ванденберг (калифорния) в 03:30 utc. ступень b1081 слетала в 25-й раз и села на платформу „of course i still love you“.»**

## Verdict
The rewritten core runs **live end-to-end through Eve's runtime over the Vercel AI
Gateway**: Russian message → reasoning → multi-step real tool calls (web_search/Exa)
→ grounded answer, in the lowercase-RU persona. Production transport, operator's key,
no fallback. Raw streams: `$JOB/tmp/gw_t1.txt`, `gw_t2.txt` (key-less tool, agent
correctly refused to hallucinate), `gw_t2b.txt` (with EXA_API_KEY).
