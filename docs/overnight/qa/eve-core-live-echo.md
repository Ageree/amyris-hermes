# Eve core — LIVE end-to-end proof (M3 + tool use, via OpenRouter)

`eve dev --no-ui` on `http://127.0.0.1:2017`, model = MiniMax-M3 through the lab's
OpenRouter creds (AI-Gateway path needs `eve link` / a valid Vercel token — this
machine's was expired, so the agent.ts OpenRouter fallback was exercised). The full
Eve runtime answered two real turns. Endpoint: `POST /eve/v1/session {message}` →
stream `GET /eve/v1/session/<id>/stream`.

## Turn 1 — plain reply (RU persona + reasoning + streaming)
Input: `Ответь ровно одним словом: привет`
- `reasoning.completed`: "User asks for exactly one word: привет. So I just say привет. No tool calls needed."
- streamed `при` → `привет`
- `message.completed`: **«привет»** (finishReason stop; inputTokens 4190 = instructions.md persona + 4 tool schemas loaded; outputTokens 27)

## Turn 2 — TOOL USE (web_search → Exa → grounded answer)
Input: `Найди в интернете: когда был последний запуск SpaceX? Ответь кратко по-русски с датой.`
- `actions.requested`: tool **web_search**, input `{query:"последний запуск SpaceX 2025 дата", numResults:5}` — the wired Exa tool fired.
- `action.result`: real Exa results (prokosmos.ru, ru.wikipedia.org, lookintothe.space — Dec 2025 launches).
- step 0 finishReason `tool-calls` (inputTokens 4209, outputTokens 83); step 1 finishReason `stop` (inputTokens 7833, **cacheReadTokens 4096** — prompt caching active).
- `message.completed`: **«Последний запуск SpaceX — 10 декабря 2025 года (Falcon 9 с 27 спутниками Starlink с базы Ванденберг). До этого был 8 декабря с площадки 39A в Кеннеди.»**

## Verdict
The rewritten core works **live end-to-end through Eve's own runtime**: receives a
Russian message → reasons → calls a real tool (web_search/Exa) → synthesizes a correct
grounded Russian answer. Not a mock, not a build-only check. Raw streams:
`$JOB/tmp/eve_echo_stream.txt`, `$JOB/tmp/eve_tool_stream.txt`.

Still operator-gated for PROD transport: `eve link` (Vercel OIDC) to route M3 through the
AI Gateway instead of OpenRouter; `remember`/`recall` need Convex `CONVEX_URL`+`WORKER_SECRET`
+ the `memories` mutation to round-trip (untested live here — no Convex env in the worktree).
