# M7 schema-tighten + legacy removal — DEFERRED (operator-gated)

Status: **deferred on purpose.** The M7 e2e suite, CI gate, and all additive work
are DONE and verified on dev. The remaining M7 steps are *destructive* and depend
on the M6 operator cutover (itself operator-gated). Applying them now would break
the live operator and violate the zero-downtime invariant.

## What is deferred
1. `schema.ts` — tighten `messages.userId`, `messages.channel`, `messages.replyTarget`
   and `connectIntents.userId` from `v.optional(...)` to **required**.
2. `messages.ts` — remove the legacy global `claimNext` (keep only `claimNextForUser`).
3. `http.ts` — remove the `ALLOWED_USER_NUMBER` operator short-circuit / legacy
   enqueue path (operator rows then carry `userId` like every tenant).

## Why it cannot run yet (the hard dependency)
The live operator (`+79217818876`) runs on the Mac **launchd worker**, which polls
the global `messages:claimNext`. By design (`http.ts` ~line 72) the inbound webhook
enqueues the operator's rows with `userId === undefined` so that legacy worker can
claim them. Therefore, RIGHT NOW, dev contains queued/recent operator rows with no
`userId`. Consequences if we tightened today:
- `npx convex dev --once` would **reject the push** (existing rows fail the stricter
  schema), and
- removing `claimNext` would **stop the operator's worker from draining** its mail
  — a live outage.

Both break "operator stays live throughout (zero downtime)" (goal.md) and the
"additive-then-tighten only after backfill verified" rule.

## The safe sequence (run with the operator present)
1. **Backfill audit (dev).** Confirm zero message rows are missing `userId`/`channel`/
   `replyTarget` and zero `connectIntents` missing `userId`. (A one-off Convex query
   over the additive columns; the operator's recent rows are the ones to watch.)
2. **Cut the operator worker over to scoped mode (M6 #8).** Set `USER_ID=<operatorUserId>`
   (+ `WORKER_MODE=scoped`) in the launchd daemon's env and restart it. It now polls
   `claimNextForUser(operatorUserId)` instead of `claimNext`. Run a live ping before
   AND after (`lab/scripts/live_ping.sh`) — exactly one reply each time.
3. **Flip the webhook off the legacy path.** Have the inbound webhook resolve the
   operator's `userId` from his verified `channelBindings` row (same path as every
   tenant) so new operator rows carry `userId`. Re-verify a live ping.
4. **Tighten on dev.** Apply the schema change + remove `claimNext` + remove the
   `ALLOWED_USER_NUMBER` short-circuit; `npx convex dev --once` must push clean
   (proves 0 invalid rows). Re-run the full lab + convex_e2e suites.
5. **Prod is a separate, explicit operator decision.** NEVER run `npx convex deploy`
   autonomously — prod is `adept-dragon-928`. The M7 acceptance's `npx convex deploy`
   check is the operator's to run once they choose to promote.

## Readiness check (safe, read-only)
- `grep -n 'claimNext\b' control-plane lab` — currently shows BOTH `claimNext` and
  `claimNextForUser`; after step 4 it must show only `claimNextForUser`.
- The fleet/worker no longer needs `claimNext`: the scoped path
  (`claimNextForUser`) is the sole claim route once the operator is cut over.

Until steps 1–4 are done with the operator, the codebase intentionally KEEPS the
legacy `claimNext` + `ALLOWED_USER_NUMBER` path so the operator never goes dark.
