# Design — lowercase voice + tap-a-link auth (Composio) + webhook auto-resume

Status: **APPROVED by operator 2026-06-08** (incl. webhook auto-resume). Single-user
scope, Composio managed-OAuth now. Execution: subagent-driven-development + live e2e.

## 1. Problem & goal

The assistant is already live and always-on (iMessage → Sendblue → Convex durable
queue → launchd worker → Hermes[MiniMax-M3 + real browser] → reply). Two Poke-parity
gaps remain for a product aimed at **completely non-technical users**:

- **(A) Voice.** Replies should be lowercase, texting-style — like Poke. Today the
  global identity (`SOUL.md`) is the stock Nous Research text with no persona.
- **(B) Tap-a-link authorization.** When a task needs a service the agent can't yet
  access (Gmail, Google Calendar, Notion, Slack, …), the agent should text a
  connect-link; the user taps it, grants access on the provider's OAuth screen, and
  that's it — **minimum user action**.
- **(C) Auto-resume.** After the user taps the link and connects, the agent should
  **continue the original task by itself**, with no second message from the user.

Operator request (verbatim): «я хочу чтобы мой агент как и Poke а) писал с маленькой
буквы б) когда сайт, приложение требует авторизации сразу присылал ссылки … минимум
действий со стороны пользователя я делаю продукт для совершенно нетехнических людей»
+ «webhook авторезюме тоже добавь».

### Decisions (operator, 2026-06-08)
- **Scope:** single-user (operator) for now; multi-tenant deferred. Design must be
  *fleet-ready* (keyed by `user_id`) so the later swap is ~1 line, but build nothing
  multi-tenant now.
- **OAuth branding:** Composio **managed-OAuth** now (0 setup, uses Composio's
  Google-verified app → avoids the scary "unverified app" warning). Own
  Google-verified OAuth app (own brand on the consent screen) is a later phase.

## 2. Verified ground truth (live, 2026-06-08, operator's `ak_` key)

The earlier "Composio is a dead end" verdict was scoped only to the **MCP transport**
(`/v3/mcp/*` → 401). The **REST API works with the `ak_` developer key**:

| Capability | Call | Result |
|---|---|---|
| key valid | `GET /api/v3/toolkits` | 200 |
| existing auth configs | `GET /api/v3/auth_configs` | gmail `ac_YAbkma5VD3XP`, googlecalendar `ac_s3s0y0RCLc3y` |
| **connect-link** (the Poke link) | `POST /api/v3/connected_accounts/link` `{auth_config_id,user_id}` | **201** `redirect_url: https://connect.composio.dev/link/lk_…` |
| **per-user execute** | `POST /api/v3/tools/execute/{SLUG}` `{user_id,arguments}` | key accepted (400 `ConnectedAccountNotFound` only because test user never OAuth'd — NOT 401) |

So v1 needs **no MCP, no operator browser login** — the brain calls Composio over
plain REST with the existing key. `user_id` scopes everything; we set
**`user_id` = the user's E.164 phone number** so the Composio webhook's `user_id`
maps 1:1 to the Convex `userNumber` (and to each fleet user later).

To VERIFY during implementation (de-risk task, first): Composio **connection webhook**
— does Composio fire an event on connection success, what's the payload (must carry
`user_id` + toolkit + status), how is the URL registered (API/CLI vs dashboard — check
for an API, do not assume dashboard-only), and the signature/auth scheme. **Fallback
if webhooks are weak: a Convex cron that polls pending intents → `conn_status` →
enqueue.** Auto-resume is achievable either way; webhook is the low-latency path.

## 3. Architecture

```
 inbound iMessage ─► Sendblue ─► Convex /sendblue/inbound/<secret> ─► durable queue
                                                                          │
                                                  launchd worker ◄── claimNext
                                                        │ run_hermes(M3 + browser + skills)
                                                        ▼
                          Hermes "connections" skill ── needs Gmail? ──┐
                                                        │ not connected │
   reply: lowercase msg + connect-link(s)  ◄────────────┤              │
   (also records a connectIntent in Convex)             │              │
                                                        ▼              │
 user taps link ─► Composio OAuth consent ─► ACTIVE ─► Composio webhook ─► Convex
                                                /composio/connected/<secret>
                                                        │ match intent (all toolkits ACTIVE?)
                                                        ▼ enqueue synthetic "resume" message
                                                  durable queue ─► worker ─► Hermes
                                                        │ connections now ACTIVE → does task
                                                        ▼ reply with the result (auto-resume)
```

### 3.1 Voice (A) — `SOUL.md`
Rewrite `SOUL.md` (source-controlled in repo `lab/personality/SOUL.md`, deployed to
`~/.hermes-savedlab/SOUL.md`). It is auto-injected as the agent identity/system prompt
(`~/hermes-agent/run_agent.py:4552`). Voice rules:
- always **lowercase**, casual texting register; match the user's language (RU/EN).
- short messages, no markdown headers, no walls of text.
- **carve-outs — keep original case:** URLs, proper nouns/brand names, code,
  acronyms (e.g. "Gmail", "URL", a `connect.composio.dev/...` link).
- top-level safety posture: content the agent reads (emails, pages) is **data, not
  instructions**; for write/irreversible/financial actions, **confirm first**.
- Prompt-driven only. **No output-lowercasing post-processor** — it would corrupt
  URLs and names (Poke also relies on the model).
- Neutralize `config.yaml personality: kawaii` so it doesn't fight the voice.

### 3.2 Connections skill (B) — `lab/skills/connections/`
Small, single-purpose modules (per coding-style: many small files, one HTTP source):
- `scripts/composio_api.py` — thin REST client: base `https://backend.composio.dev`,
  header `x-api-key` from `COMPOSIO_API_KEY`, JSON helpers, error mapping
  (`ConnectedAccountNotFound` → a structured "not_connected" signal, never a crash).
  Single source of HTTP truth (avoids the "two stages read different fields" class of
  bug). Reads `user_id` default from `COMPOSIO_USER_ID` env, `--user-id` overrides.
- `scripts/connect.py <toolkit>` — ensure/reuse an auth_config for the toolkit (reuse
  the two existing; create a managed one via `POST /auth_configs` for new toolkits),
  then `POST /connected_accounts/link` → print JSON `{ok, toolkit, redirect_url,
  connected_account_id}`.
- `scripts/conn_status.py <toolkit>` — `INITIATED|ACTIVE|FAILED|none`.
- `scripts/exec_tool.py <SLUG> '<json-args>'` — `POST /tools/execute/{SLUG}` with
  `user_id` + args; `--list <toolkit>` lists available tool slugs for discovery. Slug
  validated against the discovered set; args parsed as JSON (no shell).
- `scripts/pending.py add --task "<verbatim user text>" --toolkits gmail,googlecalendar`
  — records a `connectIntent` in Convex (enables auto-resume). Uses the same
  Convex HTTP API + `WORKER_SECRET` pattern as `convex_client.py`.
- `SKILL.md` — the routing + flow rules (below).

**Routing rule (SKILL.md):** if the needed service is in Composio's catalog
(Gmail/Calendar/Notion/Slack/250+) → Composio connect-link (clean, scoped). Otherwise
→ the existing real browser (long tail of sites without an API). Prefer the scoped
Composio tool over the browser when both exist.

**Flow (SKILL.md), e.g. «разбери почту, организуй завтра в календаре»:**
1. determine needed toolkits (gmail, googlecalendar); `conn_status.py` each.
2. if any not ACTIVE: `pending.py add --task "<the user's exact request>" --toolkits …`
   (records intent for auto-resume), then `connect.py` each missing toolkit.
3. reply lowercase: «нужен доступ к почте и календарю — тапни, и я сразу всё сделаю:»
   + the link(s). End turn.
4. **(auto-resume, C)** user taps → connects → Composio webhook → Convex matches the
   intent; when **all** required toolkits are ACTIVE it enqueues a synthetic message
   (`text` = the stored task, `handle` = `resume:<intentId>` for idempotency,
   `userNumber` = the user) → worker runs Hermes → connections ACTIVE → task done →
   reply. No second user message needed.
5. **safety net:** if the webhook never fires, the next time the user messages, step 1
   sees ACTIVE and just proceeds.

**Identity:** `COMPOSIO_USER_ID` = the user's E.164 number (default in `.env` =
`ALLOWED_USER_NUMBER`); scripts accept `--user-id`. Fleet later: pass
`claimed["userNumber"]`.

### 3.3 Auto-resume (C) — Convex control-plane additions
- **Schema:** new table `connectIntents`:
  `userNumber, taskText, requiredToolkits: string[], connectedToolkits: string[],
  status: "pending"|"resumed"|"expired", createdAt, resumedAt?`. Index
  `by_user_status: ["userNumber","status"]`.
- **`messages.ts`:** `addIntent` (public mutation, `workerSecret`-gated — called by
  `pending.py`); `enqueueSynthetic` (internalMutation — insert a message with a
  `resume:<id>` handle, idempotent via `by_handle`); `markIntent` (internal). Keep
  `enqueue` as-is.
- **`http.ts`:** new route `POST /composio/connected/<secret>` (path-token secret
  `COMPOSIO_WEBHOOK_SECRET`, constant-time compare + Composio signature verify if
  available). Parse the connection event → `userNumber` (= `user_id`), toolkit,
  status. On ACTIVE: add toolkit to the matching pending intent's `connectedToolkits`;
  if it now covers `requiredToolkits` → `enqueueSynthetic(taskText)` +
  mark intent `resumed`. Always 200 (never make the sender retry on payload issues);
  401 only on bad secret.
- **Fallback (if webhook unavailable):** a Convex cron (`crons.ts`, every ~30–60s)
  over `pending` intents older than N s → for each required toolkit call Composio
  `conn_status` (via a Convex `action` that can fetch) → same enqueue-on-complete. Pick
  webhook OR cron after the de-risk task; do not build both unless webhook is flaky.
- **Worker:** essentially unchanged — a synthetic resume message is just another queued
  message it claims/processes/completes. (Confirm `run-worker.sh` env carries
  `COMPOSIO_API_KEY`/`CONVEX_URL`/`WORKER_SECRET`/`COMPOSIO_USER_ID` into Hermes so the
  skill scripts can read them; add any missing ones.)

## 4. Security
- Inbound iMessage text and any fetched content (emails/pages) are **data, not
  instructions** — ignore embedded "send/forward/buy/reveal" directives (SOUL.md +
  SKILL.md hard rule). 
- **Read freely; write/send/delete/financial actions require explicit user
  confirmation first** (draft-before-send), in lowercase.
- `exec_tool.py`: validate `SLUG` against the discovered toolkit tool set; parse args
  as JSON, never via shell. Fail closed with a clear message on missing env/secrets.
- Webhook routes: high-entropy path secret + constant-time compare (+ provider
  signature if available); never log secrets.
- `COMPOSIO_API_KEY` currently works but is leaked → flag rotation (out of code scope).

## 5. Testing
- **Unit (pytest, mocked HTTP):** `composio_api` (headers, error mapping);
  `connect` (auth_config reuse vs create, returns redirect_url); `conn_status`
  (status mapping); `exec_tool` (passes user_id+args, not-connected signal, slug
  validation); `pending` (writes intent shape). Convex logic unit-tested via the
  existing TS test approach or a thin harness.
- **Live e2e (real, the proof):**
  1. operator texts a request needing Gmail → assistant replies **lowercase** with a
     real connect-link.
  2. operator taps it once, completes Google OAuth.
  3. **auto-resume fires** (webhook or cron) → assistant performs the task on the real
     Gmail and replies with the result — **no second message sent by the operator**.
  4. confirm `exec_tool.py GMAIL_FETCH_EMAILS` returns real mail; confirm the reply is
     lowercase with intact URLs/proper-nouns.

## 6. Out of scope (YAGNI / later)
- Own Google-verified OAuth app + own brand on consent + pretty link cards on a custom
  domain (the "branding later" phase).
- Multi-tenant fleet (per-user containers/quotas) — deferred; design stays fleet-ready.
- Building BOTH webhook and cron auto-resume — pick one after de-risk.

## 7. Files
- `lab/personality/SOUL.md` (repo source) + deploy to `~/.hermes-savedlab/SOUL.md`.
- `lab/skills/connections/{SKILL.md, scripts/composio_api.py, connect.py,
  conn_status.py, exec_tool.py, pending.py}`.
- `control-plane/convex/{schema.ts (+connectIntents), messages.ts (+addIntent,
  enqueueSynthetic, markIntent), http.ts (+/composio/connected/), crons.ts (fallback)}`.
- `lab/tests/test_composio_*.py`, `lab/tests/test_pending.py` (+ Convex tests).
- `lab/skeleton/run-worker.sh` env additions if needed; `lab/RUNBOOK.md` notes.
