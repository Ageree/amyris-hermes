# Eve-core migration — status & cutover runbook

Brain swap **Python-Hermes → Eve** (Shape A: Convex drains the queue into the deployed
Eve agent). Convex (queue/memory/webhooks/pairing/auth) and the Telegram channel are
unchanged. See `docs/eve-core-spec.md` for the full design.

## Status (2026-06-26)

| Stage | What | State |
|---|---|---|
| **M0** | Eve agent deployed, answering on `minimax/minimax-m3` via Vercel AI Gateway | ✅ **LIVE, proven** — `https://amyris-eve-core.vercel.app`, httpBasic ingress auth |
| **M1** | Convex drainer `agent.drainOne` (claim → Eve → Telegram → complete) + history-injected memory | ✅ **BUILT**, core live-checked against prod Eve; **dormant** behind `EVE_DRAINER_ENABLED` |
| **M2** | Conversation memory (last N turns injected by the drainer) | ✅ done (parity with legacy worker) |
| **M2 facts** | Durable cross-window facts (`remember`/`recall` + `memories` table) | ⏸ **deferred** — see *Deferred* below |
| **M4** | Cutover (flip env + stop Python worker) | ⏳ **operator-gated** (needs prod Convex deploy + go) |

Proven live: Eve answers on M3 through the AI Gateway; durable-session memory works;
the drainer's real code creates a session, injects history, parses the NDJSON stream,
and extracts the correct reply (`scripts/eve.check.ts` → "бирюзовый" from injected history).

## What changed (this worktree)

- `control-plane/convex/lib/eve.ts` — pure brain client: `callEve` (create session +
  inject history + parse NDJSON reply) and `sendTelegram` (Bot API rich → plain fallback).
- `control-plane/convex/agent.ts` — `internalAction drainOne` (`"use node"`): claims the
  oldest queued row, fetches recent history, calls Eve, sends the Telegram reply, marks
  the row done, reschedules to drain the backlog. Telegram-only (fails other channels loudly).
- `control-plane/convex/http.ts` — Telegram inbound schedules `drainOne` **only when
  `EVE_DRAINER_ENABLED=1`** (kill-switch; dormant by default → legacy worker still serves).
- `agent/agent/instructions.md` — memory is automatic (injected); dropped remember/recall promises.
- `agent/agent/_deferred-tools/` — `remember.ts`/`recall.ts` moved out of `tools/` (durable-facts fast-follow).
- `scripts/eve.check.ts` — runnable check: `EVE_INGRESS_SECRET=… node --experimental-strip-types scripts/eve.check.ts`.

## Cutover runbook (operator)

Additive + reversible. The Eve brain runs only when both steps below are done; until then
the legacy Python worker serves traffic unchanged.

1. **Set Convex prod env** (control-plane deployment, e.g. `zany-tapir-501`):
   - `EVE_URL=https://amyris-eve-core.vercel.app`
   - `EVE_INGRESS_SECRET=<same value already in Vercel prod env>` — copy from Vercel
     (`cd agent && vercel env pull` shows it, or the dashboard). Must match the agent's ingress secret.
   - Confirm `TELEGRAM_BOT_TOKEN` and `WORKER_SECRET` are already set (they are — live bot @e1isabot).
2. **Deploy control-plane Convex** — `cd control-plane && npx convex deploy`. Additive: a
   new `agent` module + a guarded line in the Telegram webhook. (Codegen regenerates
   `_generated/api` to include `agent.drainOne` — the only current TS errors are that stale type.)
3. **Flip on** — set Convex prod env `EVE_DRAINER_ENABLED=1`.
4. **Stop the Python worker** so it stops claiming (the shared bridge / launchd / GCP fleet).
   The atomic claim makes coexistence safe (at-most-once), but leaving both on splits traffic.
5. **Verify** — text @e1isabot from a paired account → Eve answers (lowercase RU persona, M3).
   Check Convex `messages` rows go `queued → processing → done`.

**Rollback (instant):** unset `EVE_DRAINER_ENABLED` and restart the Python worker. No data
migration, no schema change — fully reversible.

## Channel scope

New core is **Telegram-only** (spec Q4). iMessage (Sendblue) rows reaching the drainer are
**failed loudly**, not delivered — keep the Hermes/Sendblue path for iMessage until an
iMessage send path is added to the drainer, or move the operator to Telegram.

## Deferred — durable facts (fast-follow)

`remember`/`recall` need to key facts by the **tenant userId**, but the generic eve channel
authenticates as one service principal and exposes no per-request tenant id in tool ctx.
Upgrade path (`agent/agent/_deferred-tools/README.md`): a custom eve channel that POSTs
`{message, userId}` and stores `userId` via `defineState` for tools to read, plus a
`memories` Convex table (`upsert`/`list`, worker-secret gated). Not needed for migration
parity — the legacy worker had no durable-facts table either.

## Keys to rotate (pasted in chat over the project)

Turso token, AgentPhone `sk_live_…`, Uber client secret `GoM1Jk…`, Exa key, MiniMax `sk-cp-…`,
Vercel AI Gateway `vck_…`, `EVE_INGRESS_SECRET` (if it ever transits chat).
