# Спека ядра: Eve-мозг + Telegram + память на Convex (sub-project #1)

**Дата:** 2026-06-26 · **Статус:** ЧЕРНОВИК НА АПРУВ (гейт: код только после одобрения) · **Тип:** МИГРАЦИЯ (не greenfield)

> **Контекст (зафиксирован, не переоткрываем):** продукт = Poke-для-РФ, мультитенант SaaS. Onboarding: сайт → кнопка → телефон → чат. Меняем **мозг** Python-Hermes → **Eve** (Vercel agent framework); **оставляем** Convex (память/БД/очередь/вебхуки/pairing/auth) и Telegram (канал). В РФ нет consumer-API заказов → браузер-автоматизация (`browser_order`) = главный инструмент. Оплату **можно нажимать** (полная автономия до конца, без HITL на каждый заказ; авторизация — предоплаченный баланс/рекуррент один раз вперёд + spend-cap). Платёжный слой (#3) — только контур, не строим.

---

## 0. Scope этого sub-project

**ВНУТРИ ядра (#1):**
- Eve-приложение (`agent/` dir) как мозг: `defineAgent` + `instructions.md` (персона) + `tools/*.ts`.
- Канал Telegram поверх Bot API (inbound webhook + outbound rich-сообщения).
- Память на Convex: tools `remember()`/`recall()` + авто-подгрузка профиля и последних N сообщений каждый ход.
- Контур `browser_order` (интерфейс тула + session/profile-плумбинг под выбранный облачный браузер) — **без** конкретных Yandex-флоу.
- Контур платёжного guardrail (`spendPolicy`/`balance` поле в Convex, которое тул проверяет) — **без** ЮKassa.

**СНАРУЖИ (отдельные sub-projects, здесь только заложить швы):**
- #2 RF-интеграции (конкретные Yandex-флоу: такси/доставка/еда/лавка как tools).
- #3 Платёжный слой (ЮKassa предоплата+рекуррент, заказы на ИП).
- #4 Гипер-персональные мини-аппы (Eve `sandbox/*` microVM).
- #5 Ребрендинг + редизайн.

---

## 1. Карта миграции: что остаётся / что меняется / что уходит

| Компонент | Сейчас | Решение |
|-----------|--------|---------|
| **Convex schema/queue/вебхуки/pairing/auth** | `control-plane/convex/*` (см. §3) | ✅ **ОСТАЁТСЯ как есть** (channel-agnostic, проверено, держит идемпотентность/мультитенантность/binding). |
| **Память** | `messages:recentForUser` (Convex) | ✅ **ОСТАЁТСЯ** + добавляем таблицу `memories` для фактов. |
| **Telegram** | Bot `@e1isabot` (id 8920610830), вебхук `/telegram/inbound`, `sendRichMessage` | ✅ **ОСТАЁТСЯ** (Bot API). Канал переезжает с Python на Convex/Eve-границу. |
| **Мозг** | Python Hermes (`hermes chat --quiet --query=`) через `hermes_bridge.py` | 🔁 **ЗАМЕНА → Eve** (`defineAgent`, AI Gateway, durable session). |
| **Воркер-петля** | `lab/skeleton/worker.py process_one(run_fn)` поллит очередь, сабпроцессит Hermes | 🔁 **ЗАМЕНА → Convex action `agent:processMessage`** (drainer, без отдельного Python-процесса). |
| **Канальный слой** | `lab/skeleton/channels/*` (Python, Photon/Sendblue/Telegram) | 🔁 Telegram-out → Convex action (`fetch` Bot API). iMessage/Photon/Sendblue — заморожены (не в ядре РФ). |
| **GCP per-user fleet** | `fleet/controller/*` + `agentInstances` (контейнер на юзера, локальный Chrome) | 🗑️ **RETIRE для мозга** (Eve serverless = нет контейнера на юзера). `agentInstances` либо удалить, либо перепрофилировать под lifecycle облачных browser-сессий. |
| **Браузер** | `browser-use`/`browser-harness` (Python, локальный Chrome `BU_CDP_URL=127.0.0.1:9222`) | 🔁 **В облако:** browser-use **cloud** CDP-эндпоинт + per-user `profile_id` + BYO RU-прокси (см. §8). Драйвер переиспользуем — меняем только URL. |

**Шов (blast radius = одна функция):** сегодня `worker.py:process_one(run_fn=run_hermes)`, контракт `run_fn(text, *, history, ...) -> str` (`lab/skeleton/hermes_bridge.py:92`). В миграции этот вызов `run_hermes(...)` заменяется на HTTP-вызов Eve. Всё, что выше шва (claim/reply-routing/идемпотентность/мультитенантность), — agent-agnostic и не трогается.

---

## 2. Архитектура

### 2.1 Рекомендуемая (Shape A — Convex оркеструет, Eve = мозг-по-HTTP)

```
Telegram → Convex http.ts /telegram/inbound  (БЕЗ ИЗМЕНЕНИЙ)
              │  dedup tg:<update_id>:<msg_id> · /start <token> pairing · resolveUserByAddress
              ▼
          Convex messages-queue  (durable, идемпотентная — БЕЗ ИЗМЕНЕНИЙ)
              │  enqueue{userId, channel, replyTarget, text}  → scheduler.runAfter(0, agent:processMessage)
              ▼
          Convex action  agent:processMessage   (НОВОЕ — заменяет worker.py поллинг)
              │  claim → POST {EVE_URL}/eve/v1/session {sessionId: userId, input: text}
              ▼
          Eve app  (НОВЫЙ мозг, serverless на Vercel)
              │  defineAgent(minimax/minimax-m3) + instructions.md + tools(recall/remember/browser_order/…)
              │  durable session keyed by userId; tools бьют в Convex (память) и browser-use cloud (заказы)
              ▼  reply (string/rich)
          Convex action  → fetch Telegram sendRichMessage(replyTarget) → messages:complete
```

**Почему так:** (1) Telegram-вебхук обязан отвечать 200 быстро, а ход агента с `browser_order` = минуты → **очередь обязательна** для развязки (она уже есть и проверена). (2) Идемпотентность на ретраи Telegram (`by_channel_handle`) уже работает. (3) Мультитенантность = одно Eve-деплоймент, durable session = `userId`; **контейнер на юзера не нужен** → GCP-флот уходит, Python-воркер уходит, остаётся serverless. (4) Минимальный blast radius: меняем ровно вызов мозга.

### 2.2 Альтернатива (Shape B — Eve-native ingress)

Telegram-вебхук → кастомный **Eve `channels/telegram`** напрямую; Eve владеет сессией и сам шлёт ответ через свой outbound-канал; Convex — только store памяти/binding/dedup через tools. Идиоматичнее для Eve, меньше хопов, **но** переписывает идемпотентность/очередь/мультитенант-роутинг, которые Convex уже делает надёжно. → **Рекомендую A**; вернуться к B, если хоп через Convex добавит заметную задержку.

### 2.3 Что отложено как оптимизация (не в ядре)
- **Fast-lane** (трёхполосный роутер `fast_lane.py`: дешёвый M3 без тулов / medium / defer): сейчас экономит латентность/стоимость на тривиальных ходах. В Eve полный agent-loop дороже для «привет». **Не строим в ядре**; порт из `worker.py` как fast-follow, если латентность/цена потребуют (дешёвый пре-классификатор gemini-2.5-flash-lite → тривиальное отвечает сам, тул-ходы → Eve).

---

## 3. Точки интеграции Convex (заземление — не меняем)

- **Вебхук Telegram:** `control-plane/convex/http.ts` `/telegram/inbound`. Auth `X-Telegram-Bot-Api-Secret-Token` (const-time vs `TELEGRAM_WEBHOOK_SECRET`). dedup-ключ `tg:<update_id>:<message_id>`. `/start <token>` → `internal.pairing.redeemTelegram`. `resolveUserByAddress({channel:"telegram", address:String(chatId)})` → `enqueue{userId, channel, replyTarget, userNumber}`.
- **Очередь:** `messages.ts` — `enqueueImpl` (идемпотентна на `(channel, handle)` через `by_channel_handle`), `claimNextForUser`/`claimNextAny`, `complete{id, reply}` / `fail{id, error}` (патчат только из `processing`), cron requeue stale `processing` (>15 мин). **Память:** `recentForUser({userId, limit}) -> [{text, reply, receivedAt}]` (status==done, без синтетических handle).
- **Pairing:** `pairing.ts` `issuePairingTokenImpl(userId, channel) -> {token, code, expiresAt}` (token=16B base64url, TTL 15 мин), `redeemTelegramImpl(token, address)`. Web: `app/channels.createPairingToken({channel}) -> {token, code, deepLink}`, deep-link `https://t.me/<bot>?start=<token>`; `myChannels` реактивно флипает «pair → done» при записи binding.
- **Тенант-резолвер:** `channelBindings` `(channel,address) -> userId`, индекс `by_address`. **Инвариант A1:** ключ тенанта = `Id<"users">`; chat_id — только адрес.
- **Auth:** `app/*` гейтятся `requireUser` (`getAuthUserId`, Convex Auth JWT); `messages.*`/`pairing.*` — аргументом `WORKER_SECRET` (инвариант A4, не смешивать). **Eve-action использует `WORKER_SECRET`-путь** (это «воркер»), не JWT.

**Новое в Convex для ядра:** (а) `agent.ts` action `processMessage` (drainer→Eve→reply). (б) таблица `memories` (§6). (в) поле `spendPolicy`/`balance` (§9). Миграция additive-then-tighten, object-form fns с валидаторами, чтения только по индексам.

---

## 4. Структура Eve-приложения

```
agent/
  agent.ts          # defineAgent({ model: 'minimax/minimax-m3' })  — модель через AI Gateway (OIDC, без ключей)
  instructions.md   # системный промпт/персона: lowercase RU-голос (порт lab/personality/SOUL.md), правила тула, безопасность
  tools/
    recall.ts       # defineTool + Zod — достать факты/контекст юзера из Convex
    remember.ts     # defineTool + Zod — сохранить факт о юзере в Convex
    browser_order.ts# defineTool + Zod — заказ через облачный браузер (контур, §8)
  connections/      # OAuth через Vercel Connect (позже — Gmail/etc.; в ядре пусто)
  (channels/)       # в Shape A не нужен (Telegram I/O на Convex-границе); в Shape B — channels/telegram
package.json        # scaffold: npx eve@latest init
```

- `defineAgent({model})` — строковый id резолвится через AI Gateway автоматически. Кастомный base_url (OpenAI-compatible) поддержан через model-объект AI SDK, **но не нужен** (M3 нативно).
- `tools/*.ts` — один тул на файл, имя файла = имя тула, `defineTool` + Zod-схема входа. Точные сигнатуры Eve-API подтвердить на `npx eve@latest init` (ниже — намерение, не дословный API).
- **Durable session** на Vercel Workflows: переживает cold start/redeploy/pause; `sessionId = userId` даёт in-session continuity на ход.

---

## 5. Канал Telegram (Bot API, HTTP)

**Inbound** — уже есть (Convex `/telegram/inbound`, §3), не трогаем.

**Outbound** (в Shape A) — Convex action шлёт ответ Eve в Telegram через Bot API `fetch`:
- Богатый путь: `POST /sendRichMessage {chat_id, rich_message:{markdown}, reply_markup?}` (Bot API 10.1 — заголовки/таблицы/списки/цитаты рендерятся; точный wire — в `lean-agent-rebuild` памяти). Kill-switch `TELEGRAM_RICH_ENABLED`.
- Airtight-fallback: при ошибке rich → классический `sendMessage` с HTML (никогда не теряем ответ).
- Деграды (фото/файл/голос/реакция/опрос) — порт логики из `channels/telegram_channel.py` по мере надобности; в ядре достаточно text+rich.

> Это и есть «кастомный HTTP-канал под Bot API»: inbound = Convex-вебхук (переиспользуем pairing+dedup), outbound = Convex-action поверх Bot API. В Shape B тот же канал жил бы в Eve `channels/telegram`. Где именно — **открытый вопрос Q1**.

---

## 6. Память на Convex

**Модель:** Eve = краткосрочная continuity (durable session); **Convex = долгосрочная память**.

- **`messages`** (есть) — история диалога. Авто-recall: `processMessage` тянет `recentForUser({userId, limit:N})` и кладёт в инпут хода (порт «history-lane» Hermes). N — конфиг (старт 10).
- **`memories`** (НОВАЯ таблица) — атомарные факты о юзере: `{userId, kind ("profile"|"fact"|"preference"), key, value, source, createdAt, updatedAt}`, индексы `by_user`, `by_user_key`. Изоляция строго по `userId` (A1).
- **Eve tools:**
  - `recall({query?, kind?})` → факты/контекст из `memories` (+ опц. семантический поиск позже). Авто-вызов в начале хода ИЛИ авто-инъекция профиля в инпут — выбрать на реализации (рек: авто-инъекция профиля + `recall` по запросу).
  - `remember({kind, key, value})` → upsert в `memories` (через Convex `WORKER_SECRET`-fn).
- Tools бьют в Convex по HTTP (Eve TS → Convex action/mutation). Ключ `WORKER_SECRET` держится в env Eve-деплоймента, никогда не в коде/чате.

**Контур-минимум для ядра:** авто-подгрузка профиля + последние N сообщений каждый ход; `remember`/`recall` как явные tools. Векторный/семантический recall — fast-follow.

---

## 7. Модель (AI Gateway)

- **DEFAULT: `minimax/minimax-m3`** — нативно на Vercel AI Gateway, **$0.30/M in · $1.20/M out** (Fireworks-роут; first-party MiniMax $0.60/$2.40, Gateway сам балансирует). 1M ctx, multimodal, tool use, сильный русский. **Та же модель, что у текущего флота → нулевая миграция.** Keyless через OIDC, `defineAgent({model:'minimax/minimax-m3'})`. OpenRouter **не нужен**.
- **FALLBACK: `google/gemini-2.5-flash`** ($0.30/$2.50) — другой провайдер (устойчивость к простою MiniMax/Fireworks), быстрый, отличный русский, надёжный tool calling. Завести через model-fallback AI SDK: M3 primary → Gemini auto-takeover.
- **Cost-floor-альтернатива fallback:** `deepseek/deepseek-v3.2` ($0.28/$0.42 — самый дешёвый output на Gateway).
- Источник: `GET https://ai-gateway.vercel.sh/v1/models` (294 модели, вся линейка MiniMax присутствует), проверено живьём 2026-06-25.

---

## 8. `browser_order` — контур (движок из `docs/cloud-browser-decision.md`)

**Движок:** **`browser-use cloud`** (CDP) — хостед-версия уже интегрированного `browser-use`/`browser-harness`; **резерв** Browserbase → Kernel (тем же CDP-кодом). **Прокси:** пул **RU-мобильных модемов** (`mobileproxy.space`), sticky на время заказа; overflow — SOAX/IPRoyal. **Анти-детект = прокси + реалистичный fingerprint + человеческий темп + sticky**, не сам браузер.

**Тул-интерфейс (Zod, контур):**
```
browser_order({
  service: enum,        // какой Yandex-сервис (флоу — в sub-project #2)
  intent: string,       // что заказать (NL)
  max_amount?: number,  // потолок на заказ (сверяется со spendPolicy, §9)
})  ->  { status: "done"|"needs_handoff"|"blocked", summary, handoff_url? }
```

**Поведение (заложить в ядро, флоу — в #2):**
1. Открыть/приаттачить **per-user облачную сессию**: `profile_id` юзера (хранится в Convex) + sticky RU-прокси из пула. Логин Yandex персистится в профиле между заказами.
2. Драйвить флоу (переиспользуем `browser-harness`-драйвер — меняем только `BU_CDP_URL` на облачный CDP).
3. **Довести до конца, включая нажатие «Оплатить»** (оператор подтвердил), если в пределах `spendPolicy`. Отдельного HITL на заказ нет.
4. **Handoff через `live_url`:** когда всплывает SMS-код/3DS/капча, которую агент не должен/не может пройти сам → вернуть `handoff_url` (живой просмотр той же сессии), юзер сам подтверждает в Telegram-карточке. (Минимум действий для нетех-юзера — как Poke.)
5. **Guardrails:** проверка `spendPolicy` перед оплатой; **спайки только на throwaway-аккаунтах, никогда на личном**; изоляция per-user сессий.

**Честно про риск (не скрывать в спеке):** это путь B (полная автономия) — самый мощный, но самый хрупкий: ToS/ban-риск Yandex, фрагильность UI, удержание карт-сессий юзеров. Де-риск: (а) RU-мобильный прокси + fingerprint + темп; (б) **спайк ОДНОГО флоу первым** (Yandex Eda уже проверен до checkout — `rf-assistant-pivot`); (в) spend-cap; (г) live_url-handoff на всё, что агент не пройдёт. Облачный браузер это **включает**, но не устраняет риск.

**Before-lock (из decision-доки):** уточнить у browser-use cloud изоляцию/шифрование карт-профилей + ставку BYO-egress; живьём прогнать RU-модем → Yandex login → частота SmartCaptcha (throwaway).

---

## 9. Платёжный контур (#3 — только заложить)

- **Convex поле `spendPolicy`/`balance` на юзера:** `{balanceKopecks, perOrderCapKopecks, monthlyCapKopecks, monthSpentKopecks}`. `browser_order` сверяется **перед** нажатием оплаты; превышение → `blocked` (или handoff на пополнение).
- **`spendEvents`** (append-only): логировать каждую оплату (сумма/заказ/время) для аудита и месячного потолка.
- **Авторизация «без подтверждения»** = юзер один раз настраивает баланс/рекуррент (ЮKassa) вперёд; дальше агент тратит из авторизованного потолка без HITL на заказ. Spend-cap — единственный guardrail на реальные деньги.
- **НЕ строим в ядре:** ЮKassa-интеграцию, пополнение, рекуррент, расчёты на ИП. Только поле + проверка в туле (шов).

---

## 10. План миграции (фазы — заложить, не выполнять до апрува)

Каждая фаза = **kill-switch + parallel-run** со старым Hermes (старый shared-воркер остаётся fallback'ом до cutover).

| Фаза | Содержание | Runnable-проверка |
|------|-----------|-------------------|
| **M0** | `npx eve@latest init` → `defineAgent(minimax-m3)` → деплой на Vercel + AI Gateway OIDC. | `curl POST /eve/v1/session` → echo-ответ от M3. |
| **M1** | Telegram: Convex action `processMessage` (drainer → Eve → `sendRichMessage` → complete). Заменяет поллинг `worker.py`. За kill-switch. | Синтетический enqueue в Telegram-очередь → ответ Eve долетает, Convex-строка `done`. |
| **M2** | Память: таблица `memories` + tools `recall`/`remember` + авто-recall last-N + `instructions.md` (порт SOUL.md, lowercase RU). | `remember(X)` → `recall` возвращает X (Convex round-trip). |
| **M3** | `browser_order` спайк: browser-use cloud + RU-прокси + ОДИН Yandex-флоу (throwaway, до checkout вкл. оплату). | Airtight CDP-проба (как 🐴 example.com), затем Yandex throwaway до экрана/факта оплаты. |
| **M4** | Cutover (оператор первым) → retire Python-воркер + GCP-флот. | Реальное сообщение оператора → ответ из Eve, старый воркер не задействован. |

---

## 11. Открытые вопросы (нужно твоё подтверждение — рекомендации проставлены)

- **Q1 — Ingress-форма:** **Shape A** (Convex оркеструет, Eve = мозг-по-HTTP, Telegram I/O на Convex-границе) ⟵ **рек** (минимальный риск, максимум reuse, очередь обязательна для развязки вебхука) vs Shape B (Eve-native: вебхук → Eve `channels/telegram`, Convex только память).
- **Q2 — Retire GCP-флота + Python-воркера для мозга?** ⟵ **рек ДА** (Eve serverless = контейнер на юзера не нужен). `agentInstances` — удалить или перепрофилировать под lifecycle облачных browser-сессий?
- **Q3 — Браузерный движок:** `browser-use cloud` + пул RU-мобильных прокси (`mobileproxy.space`) ⟵ **рек** (из `docs/cloud-browser-decision.md`); резерв Browserbase.
- **Q4 — Канал ядра = только Telegram** (iMessage отложен)? ⟵ по промпту ДА.
- **Q5 — Язык мозга:** Eve = TS/Vercel; browser-use cloud зовём по API/CDP (язык-агностично). Локальный Python `browser-harness` — retire или оставить как локальный pro-tier?

---

## 12. Тест-план (минимум — по одной runnable-проверке на нетривиальный кусок)

- AI Gateway: `GET /v1/models` содержит `minimax/minimax-m3` (есть) + echo-ход.
- Drainer: синтетический enqueue → Eve-ответ → `messages` строка `done` (не `error`).
- Память: `remember`/`recall` round-trip + изоляция по `userId` (чужой userId не видит факт).
- `browser_order`: airtight CDP-проба (сессия реально открыта облачным движком — проверять out-of-band, не по тексту ответа), затем Yandex throwaway.
- Идемпотентность: повторный `tg:<update_id>:<msg_id>` не создаёт второй ход.

---

**Дальше:** после твоего апрува спеки → `writing-plans` (детальный план реализации) → scaffold (`npx eve@latest init` + Telegram + remember/recall). До апрува — код не пишу.
