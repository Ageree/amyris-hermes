# Phase 0 Exit Report — Saved-Content Lab

**Run:** 2026-06-08 (autonomous overnight session; operator asleep, full autonomy granted)
**Environment:** Hermes Agent v0.11.0, isolated `HERMES_HOME=~/.hermes-savedlab`, **MiniMax-M3** (frontier multimodal, 1M context) via `api.minimax.io/v1` (operator's funded key), saved-content skill v0.1.

> **Correction (2026-06-08):** an earlier pass in this report wrongly claimed "M3 does not exist" and downgraded the model to M2.7. **MiniMax-M3 is real and is the frontier multimodal model** — confirmed by direct API test (HTTP 200, `"model":"MiniMax-M3"`, returns reasoning tokens; a bogus model name returns HTTP 400 "unknown model"). The core save→card→store loop was **re-validated end-to-end on M3** on 2026-06-08; M3's internal `<think>` reasoning does not disrupt the skill flow. M3 is the chosen model going forward (multimodal video-in is exactly what reel/TikTok understanding needs).

> Scope note: the operator's 20 real bookmarks were not available during the run,
> so the golden set is **synthetic public URLs** I selected. The full save→card→store
> loop was validated end-to-end on real content; per-source resolution was probed
> across all source types. Real SC-001 pass/fail still needs the operator's actual saves.

## What was validated end-to-end (real M3, not mocks)

| Feature | Spec | Result |
|---|---|---|
| Save → resolve → understand → knowledge card → store | US1 / FR-001..006 | ✅ PG article: resolve.py (Jina, 1.2s) → essence+4 steps → `library.py add` → card. Card quality on-vision (RU texting «Сохранил 👌…» + steps + 1 question). |
| Spaced resurface cadence (due/engage/archive) | US2 / FR-010,012 | ✅ live on the real item: `due` empty before next_due; returns+bumps ignores 0→1 after; `engage` advances interval 0→1 (1d→3d), resets ignores. |
| Proactive digest + earn-every-ping | US2 / FR-011,013 | ✅ empty due → agent replied exactly `[SILENT]`; one due item → ONE bundled digest naming it + one concrete next step. |
| Honest degraded failure | FR-005 | ✅ blocked sources return `ok:false`+error; skill instructs a degraded card. |

## Measured constants

- **Process RAM (peak RSS):** **290 MB** per Hermes instance (transient CLI; a persistent
  gateway will be somewhat higher, est. 350–500 MB).
- **Base context per turn:** system prompt + tools + skill = **~5,737 tokens**. A text
  save turn ≈ **11–16k input + ~1k output tokens** (article capped at 20k chars ≈ 5k tok).
- **Latency:** save ≈ 8–21 s/query on M2.7; the M3 re-validation save ran ~66 s end-to-end (resolve + M3 reasoning + card + first-save cron). Within the 90 s SLA (SC-001); watch M3 reasoning-token latency on heavier inputs.

## Cost (SC-005) — estimated, not metered

No metered console access this run (see "Issues"). Estimate at MiniMax-M3 promo (~$0.30/M in, $1.20/M out; list $0.60/$2.40, cached-in $0.06/M):
- **Text save: ~$0.006/item.** Daily digest: ~$0.002.
- **Video save (multimodal): higher** — video tokens dominate; est. $0.02–0.08/item depending on length.
- **Per active user/mo** (≈60 saves + 30 digests + chat): **~$2–4** for text-heavy; pushes toward the
  **$4.5 SC-005 ceiling** only if video-heavy. **PASS for text/article/X-heavy use; WATCH video volume.**

## Fleet density (SC-008)

At 290–500 MB/instance, a 32 GB host fits **~50–60 users** with 30% safety headroom —
**beats the SC-008 target of 30/32 GB.** (Caveat: separate containers don't share Python/lib
pages copy-on-write the way forked processes do; the persistent gateway footprint should be
re-measured in the Phase-1 container.)

## Per-source resolution (the #1 Phase-1 input)

| Source | Stock result | Fix |
|---|---|---|
| Article (Jina r.jina.ai) | ✅ reliable, no auth | — |
| X / Twitter (fxtwitter) | ✅ reliable, no auth | — (incl. mobile.x.com after the Task-5/6 fixes) |
| YouTube | ❌ "no impersonate target" | ✅ FIXED: resolve.py `--impersonate chrome` + curl_cffi (proven). Bake into Phase-1 image. |
| TikTok | ❌ same impersonation issue | ✅ same fix |
| **Instagram** | ❌ **login wall** (yt-dlp can't) | ⚠️ **UNSOLVED — needs ScrapeCreators/Apify or cookie auth. IG = 99% of operator's saves → THE Phase-1 priority.** |

## Skill/code changes made during dogfood (the lab's whole point)

1. `fix(lab): SKILL.md saves before replying` — **critical**: agent composed the card but
   skipped `library.py add` (treated the card as the final reply, ended the turn). Reordered
   save-before-reply + hard rule. Re-ran → item persisted. *Unit tests could never catch this.*
2. `fix(lab): use full ${HERMES_SKILL_DIR}/scripts path in engagement commands`.
3. `fix(lab): classify mobile.x.com as x` + `_fxtwitter rewrites mobile.x.com`.
4. `feat(lab): yt-dlp impersonation with graceful fallback`.
5. `docs: MiniMax-M3 → M2.7` (made during the run, **later reverted** — M3 is real and frontier; see Correction note up top).

## Known issues / operator actions

- **MiniMax keys (updated 2026-06-08):** the key you originally pasted now works and is funded (**$24 balance**, HTTP 200 against M3) — the M3 re-validation ran on it. Your *other* key in `~/.hermes/.env` is currently rate-capped (HTTP 429 "usage limit exceeded"). Designate one funded, metered key for the fleet. **Both keys are in the chat transcript — rotate them.**
- **Telegram live e2e pending your one action:** a bot can't DM you first. DM the lab bot
  (`@`-the bot for token `8649699230:…`) once "привет", then the channel works. (Validated via CLI instead.)
- **`library.py` defaults its DB to `~/.hermes/saved-content/` ignoring `HERMES_HOME`** — a latent
  fleet-isolation bug. Must become `$HERMES_HOME/saved-content/` in Phase 1 (per-container isolation).
- IG resolution (above) — design the Phase-1 resolver chain around a paid IG resolver from day one.

## VERDICT: **GO for Phase 1**

The core product loop (save → understand → card → spaced resurfacing → digest with earned silence)
works end-to-end on M3 and produces genuinely useful, on-tone output. Unit economics and RAM
density are within targets for text/article/X content. **Solve first in Phase 1, in order:**
1. **Instagram resolution** (ScrapeCreators or Apify or cookie auth) — gates 99% of real usage.
2. `library.py` `$HERMES_HOME` DB isolation (fleet correctness).
3. Bake yt-dlp + curl_cffi + `--impersonate` into the container image.
4. Re-measure persistent-gateway RAM + get a metered MiniMax key for true $/item.
5. Telegram channel live test (operator pairing), then Sendblue for the product number.

---

## Phase-1A walking skeleton — live e2e (2026-06-08)

The full inbound→outbound loop was proven over a **public URL** (not just localhost):
`Sendblue webhook payload → loca.lt tunnel → FastAPI bridge → Hermes (MiniMax-M3 + real browser) → Sendblue reply → operator iPhone`.

- **Method:** a synthetic Sendblue inbound payload (`content="Open example.com … reply with its H1"`, `number=+79217818876`, valid `message_handle`) POSTed to the public webhook URL with the correct secret path token. Exercises every leg except Sendblue's own webhook *dispatch* (which needs the one-time dashboard paste).
- **Round-trip latency:** **29.6 s** end-to-end (HTTP POST → Hermes browser run → Sendblue send accepted → 200). Single measurement; M3 + a real `browser_navigate` to example.com.
- **Auth gates verified through the tunnel:** wrong token → `401`; empty body + right token → `{"ignored":true}`; valid payload → `{"ok":true}`.
- **Outbound confirmed server-side:** bridge log shows the request from the loca.lt edge IP (`88.216.60.178`) returning `200` with **no** `hermes failed` and **no** `sendblue reply failed` — and since `send_message` raises on any non-2xx, that silence means Sendblue accepted the reply.
- **Infra gotcha caught:** a second server (`bun scripts/telegram-relay.ts`) holds IPv6 `*:8787`; `localhost` resolves to `::1` first, so the tunnel must be pinned with `localtunnel --local-host 127.0.0.1` to reach the Python bridge (IPv4-only). Fingerprint the app through the tunnel (401 on a bad token) before trusting any tunnel URL.

**M3 token cost per turn:** still PENDING a metered capture (the bridge strips `<think>` and does not surface usage). Carry over from Phase-0 action #4.

**Remaining to close the loop for real (operator, ~2 min, can be done from iPhone):**
1. Paste the webhook URL into Sendblue dashboard → Settings → Webhooks.
2. iMessage the Sendblue number (+16466208124) any browser task.
Both are dashboard/phone actions; everything code-side is done and proven.

---

## Phase-1C — durable Convex queue, live e2e (2026-06-08)

The ephemeral P1A path (laptop + loca.lt tunnel + FastAPI) was replaced by an
**always-on, tunnel-free** architecture and proven end-to-end on the operator's
own Convex account:

`iMessage → Sendblue → stable https://<dep>.convex.site webhook → durable queue → worker polls → Hermes (M3 + real browser) → Sendblue reply → iPhone`

- **Why it matters:** no public port on the Mac, no tunnel. The brain is pure
  outbound (polls `claimNext`). Messages are durable — if the brain is offline
  they wait as `queued` and process on restart. This is a single-user assistant
  the operator can actually run 24/7.
- **Deployment:** `dev:zany-tapir-501`; functions deployed; env vars set
  (`WEBHOOK_SECRET`, `ALLOWED_USER_NUMBER`, `WORKER_SECRET`). See
  `../control-plane/README.md`.
- **Webhook gates verified live (real Convex HTTP action):** valid payload →
  `{"ok":true}` (enqueued); wrong path token → `401`; non-allowlisted number →
  `{"ignored":true}` (NOT enqueued — confirmed: queue held exactly 1 row).
- **Full loop, real everything:** enqueued via the live webhook, then ran the
  worker once against live Convex + live Hermes + **real Sendblue**. The message
  walked `queued → processing → done`; stored `reply = "Example Domain"`
  (clean — see the bug below); a real iMessage was delivered to the operator's
  iPhone (+79217818876). **Claim→complete ≈ 21 s; total process_one ≈ 23 s.**
- **Bug caught by this e2e (units couldn't):** Hermes leaks an operational notice
  to stdout even in `--quiet` mode —
  `⚠️  Normalized model 'minimax/MiniMax-M3' to 'MiniMax-M3' for minimax.` — which
  would prefix every user reply. Fixed in `hermes_bridge.py` (`_NOTICE` strips
  leading `⚠️` lines); regression test added. The live `reply` field confirms the
  fix in the real path.

**New code (TDD, all green — 73 lab tests):**
- `control-plane/convex/{schema,http,messages}.ts` — durable queue + webhook.
- `lab/skeleton/convex_client.py` — thin Convex HTTP API client (6 tests).
- `lab/skeleton/worker.py` — poll loop: claim → Hermes → reply → complete/fail
  (11 tests). Reply target is always the config operator number, never payload.
- `lab/skeleton/run-worker.sh` — turnkey runner (no tunnel).

**Remaining to go live (operator, ~2 min, unchanged from P1A but now a STABLE URL):**
1. Paste `https://zany-tapir-501.convex.site/sendblue/inbound/<WEBHOOK_SECRET>`
   into Sendblue → Settings → Webhooks.
2. Start the worker: `lab/skeleton/run-worker.sh`.
3. iMessage `+16466208124` any browser task.

**Still pending (carried over):** metered M3 $/turn capture; rotate the leaked
MiniMax + Sendblue keys.

## Connect-flow + lowercase voice + auto-resume (2026-06-08)

Three features layered onto the live single-user assistant, built via
subagent-driven-development (fresh implementer + spec-reviewer + code-quality
reviewer per batch). Spec: `docs/superpowers/specs/2026-06-08-connect-flow-and-voice-design.md`;
plan: `docs/superpowers/plans/2026-06-08-connect-flow-and-voice.md`.

- **(A) lowercase voice** — Poke-style. Driven by `lab/personality/SOUL.md`
  (prompt, not post-processing), with carve-outs that keep original case for
  URLs, product/brand names (Gmail, Notion), code, and acronyms; plus
  content-is-data and confirm-before-write/delete/spend rules.
- **(B) tap-a-link OAuth via Composio** — when a task needs an account the user
  hasn't connected, the agent replies (lowercase) with a Composio connect-link;
  the user taps, consents on the provider's own screen, done. Managed-OAuth, so
  no per-provider app setup for v1.
- **(C) webhook → poll auto-resume** — Composio has **no** connect/became-active
  webhook (only `connected_account.expired`; `callback_url` is ignored — verified
  live), so resume is worker-side polling: the connect intent is recorded in
  Convex *before* replying; the worker polls connection status and, once the
  required toolkits are ACTIVE, enqueues a synthetic `resume:<id>` message so the
  agent finishes the original task itself — no second message from the user.

**Build status: complete, independently reviewed, deployed. 93 lab tests green.**
- New REST client + scripts: `lab/skills/connections/scripts/{composio_api,connect,conn_status,exec_tool,pending}.py` + `SKILL.md`.
- Control plane: `connectIntents` table + `intents.ts` (`addIntent` / `listPending` /
  `resolveIntent` / `expireIntent`, all `WORKER_SECRET`-gated) — deployed to
  `dev:zany-tapir-501` (`_generated/api.d.ts` regenerated).
- Worker: `process_intents()` poll added to `worker.py` (runs at iter 1 then every
  5 iters; never raises; expires intents older than `intent_ttl=3600s`); deploy
  scripts ship `composio_api.py` + export `COMPOSIO_USER_ID`.

**Proven live (real Composio + real Convex, standalone):**
- Voice: full real path (synthetic inbound → Convex webhook → worker → Hermes
  with new SOUL.md → reply) returned **all-lowercase**:
  `«привет! всё ок, работаю. у тебя как? чем помочь?»` — stored `done`.
- `conn_status.py gmail` → `{"ok":true,"toolkit":"gmail","status":"none"}`.
- `connect.py gmail` → real link `https://connect.composio.dev/link/lk_KZ97F4wxRwN6`.
- `pending.py add` → intent recorded in Convex; `listPending` confirmed 1 gmail
  intent for `+79217818876`; wrong `WORKER_SECRET` rejected; stray test intent
  expired afterward (cleanup).

### FULL e2e UNBLOCKED + PROVEN — funded MiniMax Token Plan key (2026-06-08)

The earlier blocker (both LLM keys out of balance) was cleared: the operator
supplied a **MiniMax Token Plan key** (`sk-cp-` prefix). Per MiniMax docs the
OpenAI-compatible endpoint Hermes already uses (`api.minimax.io/v1`, Bearer auth,
model `MiniMax-M3`) supports Token Plan keys — confirmed with a direct probe
(HTTP 200). Swapped `MINIMAX_API_KEY` in `~/.hermes-savedlab/.env` (chmod 600),
restarted the launchd worker.

**Proven live, real everything (funded key):**
- **Hermes stack:** bridge `run_hermes("respond with exactly: pong")` → `pong`,
  7.8 s, clean.
- **Connect-flow (real agent, RU lowercase):** gmail request → reply
  `«нужен доступ к gmail — тапни и я сразу всё проверю: https://connect.composio.dev/link/lk_imz5St8wDMKt»`,
  delivered via the full webhook → durable queue → launchd worker → Sendblue path
  (Convex row `queued→processing→done`).
- **AUTO-RESUME end-to-end (no operator action needed — gmail was already
  connected during testing, `connected_account ca_lLE2I3WK0E7w` ACTIVE):**
  `process_intents` polled Composio, saw gmail ACTIVE, `resolveIntent` marked the
  intent `resumed` and enqueued `resume:j97ex3f6…`; the worker processed it and
  the agent **fetched real Gmail** via Composio `GMAIL_FETCH_EMAILS`, summarising
  in lowercase RU (it even surfaced the Google "Composio got access" security
  alert — proof the OAuth is real). The whole chain fired with zero human input.

**Bug caught by this real e2e (units couldn't) → FIXED.** The first auto-resume
reply leaked Hermes' tool-permission scaffolding — a `⚠️ DANGEROUS COMMAND`
header, the echoed (multi-line) command, the `[o]nce/[s]ession/[d]eny` choices,
and `✗ Denied` — glued in front of the real answer (the gate correctly denied a
risky shell pipe; the agent recovered via `exec_tool.py`, but the prompt text
reached the user). Fixed in `hermes_bridge.py` (`_APPROVAL` strips the whole
block before `_NOTICE`); +2 regression tests; **95 lab tests green**; commit
`eafa4fb`. Re-verified live: a fresh gmail-count request returned a clean reply
(`«~42 непрочитанных треда…»`) with no scaffolding. Security unchanged — the deny
still happens; this only cleans the reply text.

**Remaining operator actions:**
1. Rotate the leaked keys in `~/.hermes-savedlab/.env` — now **5**: MiniMax
   (Token Plan `sk-cp-` key was pasted in chat), 2× Sendblue, Composio, and the
   old MiniMax key.
2. Metered M3 $/turn capture (carried over).
