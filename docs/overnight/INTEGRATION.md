# Как подключить ночные модули в ядро (Eve + Convex)

Каждый модуль самодостаточен и протестирован (`features/<name>/`). Ниже — куда он встаёт в архитектуре Shape A из `docs/eve-core-spec.md` (Convex оркеструет, Eve = мозг-по-HTTP).

## Feature 6 — web search (`features/web_search/`)
- **Что:** Exa REST (`/search` + `/answer`), stdlib-only Python. Агент-вход `tool(query, num_results, want_answer)` → dict; `TOOL_SCHEMA` готов к регистрации.
- **В Eve:** портирован как TS-тул `agent/agent/tools/web_search.ts` (serverless-correct `fetch` к `api.exa.ai`, ключ из `process.env.EXA_API_KEY`). Python-версия остаётся для локального/воркер-пути.
- **Замена:** может заменить exa MCP stdio в Hermes (in-process, без subprocess/env-allowlist).
- **Риск:** `EXA_API_KEY` в `~/.hermes-savedlab/.env` — FREE test-ключ, ROTATE перед нагрузкой. `/answer` ~10–20с → не на латентном reply-пути.

## Feature 5 — персональные ИИ-приложения (`features/turso_apps/` + `served/`)
- **Что:** провижининг per-app Turso-БД (provisioner) + генератор (`generate_app(spec) -> {manifest, db_token}`) + libSQL HTTP-клиент (`libsql_http.py`, Hrana v2 pipeline). `served/` = реальный пример (habit tracker: server.py + index.html), QA-видео доказало персист через Turso.
- **В Convex (как сервить, заземлено на `control-plane/convex/http.ts`):**
  1. **Шов сервинга** = `httpRouter` (как `/telegram/inbound`, `/sendblue/inbound/`). Добавить `http.route({ pathPrefix:"/app/", handler })`, slug из `url.pathname`. URL: `https://<deployment>.convex.site/app/<slug>`.
  2. **Таблица `apps`**: `{userId, slug, name, dbHostname, dbName, group, tables(JSON), dbTokenRef, createdAt}` + индексы `by_slug`/`by_user`. **db_token НЕ хранить в строке** — только `dbTokenRef` (имя секрета), как `agentInstances.workerSecretRef`; читать из `process.env` в request-time (как `WEBHOOK_SECRET`).
  3. **Доступ к данным** = ~40 строк TS-порт `libsql_http.py` (`fetch` к `https://<dbHostname>/v2/pipeline`, `Authorization: Bearer`). Convex httpAction умеет `fetch` → новых зависимостей нет.
  4. **Триггер провижининга** — на Python/agent-стороне (где browser-use+hermes), как connect-intent: агент зовёт `generate_app`, пишет manifest через `internal.apps.register`, токен — в секрет-стор / `convex env set APP_DB_TOKEN_<slug>`.
  5. **Auth на запись** = const-time `safeEqual` против env-секрета (как webhook). Публичное чтение — открыто.
- **Остаётся:** TS-glue (apps-таблица + `/app/` route + pipeline-fetch порт + token env) — описано, НЕ реализовано (Feature 5 scope = Python provisioner+generator+manifest).
- **Риск:** Turso platform-токен org-wide (создаёт/удаляет любую БД) → high-value, только env. Пустая группа `default` остаётся (infra провижинера, бесплатна на starter).

## Feature б + 4 — браузерные задачи (`features/browser_tasks/`)
- **Что:** один `runner.py` + шаблоны (`delivery_order`, `job_autoapply`), `use_vision=True` (vision правит автокомплит Яндекса где DOM-режим падает), `generate_gif` = запись экрана. Структурная безопасность: каждый шаблон кончается `SAFE_GUARD` (СТОП перед оплатой/отправкой/логином/SMS/капчей); пройти можно только флагом `--allow-irreversible` (для operator-авторизованных прогонов).
- **В Eve:** это локальная Python-реализация тула `browser_order` (контур в `agent/agent/tools/browser_order.ts`). По спеке §8 в проде драйвер переезжает на **browser-use cloud CDP + RU-прокси** (меняется только `BU_CDP_URL`); шаблоны/гайды переиспользуются.
- **QA-доказательства:** delivery → чекаут 444₽ (карта •••4310, стоп перед оплатой); auto-apply → hh.ru вакансия → «Откликнуться» → стоп на телефон/auth-стене. См. `docs/overnight/qa/`.
- **Риск:** живой автоотклик/оплата = login + `--allow-irreversible` (никогда в QA). hh.ru one-click — вендорный риск, SAFE_GUARD держит.

## Feature 3 — звонки/бронь (`features/agentphone/`)
- **Что:** AgentPhone REST-клиент (stdlib urllib, browser-UA против Cloudflare). `book_table(...)` (double-gated real-call: `dry_run=False` + `confirm_real_call=True` + `agent_id`). voiceMode=hosted → встроенный LLM ведёт звонок по русскому systemPrompt (без webhook-сервера).
- **В Eve:** тул `call_place`/`book_table` рядом с `browser_order`. Persona-промпт (`_RU_SYSTEM_PROMPT`) ревьюится до реального дозвона.
- **ГЕЙТ (не закрыт):** AgentPhone выдаёт **только US/CA номера**; международный (+7) исходящий — недокументирован/непротестирован (safety). 0 русских голосов (ru-RU язык работает, акцент возможно неродной). → реальный дозвон в РФ-заведения на AgentPhone сегодня **не доказан**; для РФ-броней реалистичнее РФ-локальный телефонный провайдер или handoff. Модуль готов; живой звонок = решение оператора + возможностей вендора.

## Eve core (`agent/`)
- Scaffold `npx eve@latest init` (eve ^0.15.0, ai ^7, zod 4.4.3, **node 24**). Модель → `minimax/minimax-m3`. Тулы: `web_search`, `remember`, `recall` (Convex), `browser_order` (контур-стаб). Проверка = `eve build`/`tsc`.
- **Операторские шаги (не headless):** `eve link` (Vercel OIDC → AI Gateway creds) для живого M3-echo; Convex `memories.upsert` мутация для живого remember/recall round-trip.
