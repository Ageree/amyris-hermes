<!--
Authored 2026-06-15 by a multi-agent workflow (recon → 5 facet planners → synthesis),
all ground-truth verified against the repo at commit bccab79. For the NEXT work session.
-->

# Production rollout plan — Hermes Fleet (next session)

"Prod" for this launch means: the public free tier opens on the **currently-live Convex dev deployment `zany-tapir-501`** (treated as production-of-record — it already holds the operator's data, JWT keys, webhook wiring, and worker poll), the **`web/` Next.js app hosted on Vercel** at its production alias, **Password-only Convex Auth**, and **iMessage + Telegram** channels both live. The recommended overall path is: **promote-dev (not a fresh prod cutover)** + **a single shared-claim "bridge" worker (not the GCP container fleet)** + **Password-only auth** + **`*.vercel.app` domain**. This ships a real multi-tenant inbound assistant in ~1 focused session of glue work, defers the GCP fleet and the destructive M7 schema tighten as non-blocking follow-ups, and keeps every committed end-state path (fleet, scoped cutover, fresh prod) intact and reversible. Paid billing stays stubbed; free tier is 100% live.

## Decisions to make first (operator)

These gate everything below. Each has a one-line recommendation.

1. **D1 — What is "production": promote dev `zany-tapir-501`, or stand up fresh prod `adept-dragon-928`?** → **Recommend PROMOTE dev.** It is the live, webhook-wired, data-bearing system; fresh prod re-creates every binding/webhook/JWT key for zero benefit at a free-tier launch. The only liabilities (`ALLOW_TEST_SEED=1`, localhost `SITE_URL`) are two one-line fixes.
2. **D2 — Execution model: per-user GCP container fleet (LOCKED-#1) now, or a single shared "bridge" worker now?** → **Recommend BRIDGE now** (one always-on worker claiming across all tenants via a new additive `claimNextAny`). Diverges from LOCKED-#1, so **needs explicit operator sign-off.** The fleet has never touched real GCP, its image is literally unbuildable today (`your-org` placeholder), and it buys nothing at 0–5 users. Bridge ≈ 30–60 LOC + ~1 day, LOW risk; fleet ≈ 1–2 days just to run one tenant, MEDIUM risk, with two hard gaps still open. Fleet stays the committed end-state.
3. **D3 — Which auth methods at launch?** → **Recommend Password-only.** Self-contained, needs zero new secrets, already proven by the Playwright e2e. Google (`AUTH_GOOGLE_ID/SECRET`) and Resend-OTP (`AUTH_RESEND_KEY`) are unset; each throws only its own flow, so their absence is safe. Google/Resend are clean follow-ups.
4. **D4 — Domain: `*.vercel.app` or a custom domain?** → **Recommend `*.vercel.app` for launch** (free, instant, zero DNS). A custom domain changes Convex `SITE_URL`, so pick it before Phase 2/Step "SITE_URL" to avoid setting it twice. Custom domain is a clean non-blocking swap later.
5. **D5 — Rotate the 7 pending keys before or after launch?** → **Recommend rotate-now** (Telegram token is force-rotated this session anyway; the other 6 are documented as already-exposed, and a public signup invites traffic that exercises every key). MiniMax×2, Sendblue×2, Composio, Exa. If the operator prefers, the 6 non-Telegram keys can rotate immediately after launch — but the leaked-in-chat ones are a real exposure.

## Inputs needed from the operator

- **New Telegram bot token** (rotated, for `@hermessanchez_bot` id `8649699230`). Place it at `~/.hermes-savedlab/telegram_token` (`chmod 600`) — never paste it into chat. Same token must land in `~/.hermes-savedlab/.env` as `TELEGRAM_BOT_TOKEN=…` for outbound replies.
- **Sign-off on D1–D5** (especially D2 — bridge vs fleet diverges from a LOCKED decision).
- **Vercel account access** to import `Ageree/amyris-hermes` and set env vars (or the operator runs the dashboard steps; the agent can drive the CLI if logged in).
- **Domain choice** (D4) — `*.vercel.app` default, or the custom domain + DNS access if chosen.
- **Rotated values for the 6 non-Telegram keys** (D5) if rotating now: new MiniMax×2, Sendblue×2 (`sb-api-key-id`/`sb-api-secret-key`), Composio, Exa.
- **GCP confirmation only if D2 = fleet:** the real Hermes git URL + clone auth (to replace `your-org` placeholder), and approval to spend on `hermes-saved-content-lab` infra. Not needed for the bridge path.
- **`npx convex deploy` is operator-gated** — the agent never runs it autonomously (it targets the empty prod `adept-dragon-928`).

## Phased execution

Ordered so the user-facing launch (Convex hygiene → site → channels) completes even if the fleet is staged later. All work on branches, not `main` directly (repo git rules). `<DEP>` = `zany-tapir-501` unless prod is formally promoted (out of scope for launch).

### P1 — Convex launch-deployment hygiene (BLOCKER; gates everything)

Decides which `.convex.cloud`/`.convex.site` URL the Vercel build and both webhooks point at. Convex env vars are **per-deployment — none auto-migrate.** On the promote-dev path there is **no `convex deploy` to run**; "promotion" is operational. Use Convex MCP `envSet`/`envRemove`/`envList` or `npx convex env …`.

1. Confirm CLI binding: `cd /Users/saveliy/Documents/Amyris/control-plane && npx convex env list`. Expect dev `zany-tapir-501`.
2. **Scrub the test seam (the one real liability):** `npx convex env remove ALLOW_TEST_SEED`. This is the operative control that makes `testing.ts`'s 11 forge-capable mutations (`testSetEntitlement` = total billing bypass; `testIssue/RedeemPairing` = forge channel bindings) inert. `cleanupTenants` is hard-scoped to `tt-*@test.invalid` so it cannot nuke real tenants, but entitlement/pairing forgery is the live hole.
3. **Audit-and-fix the env matrix** on `<DEP>` (most already set on promote-dev):
   - `ALLOW_TEST_SEED` → **absent** (step 2). BLOCKER.
   - `SITE_URL` → set to the final Vercel origin **after** the domain is known (P2). Mismatch loops auth to `/signin`. BLOCKER (deferred to P2).
   - `WORKER_SECRET`, `WEBHOOK_SECRET`, `JWT_PRIVATE_KEY`, `JWKS`, `EXA_API_KEY`, `ALLOWED_USER_NUMBER` → keep (already set).
   - `TELEGRAM_WEBHOOK_SECRET` → **absent today** → set in P3 (Telegram 401s everything until then).
   - `AUTH_GOOGLE_ID/SECRET`, `AUTH_RESEND_KEY`(+`AUTH_EMAIL_FROM`) → leave unset (D3 Password-only). FOLLOW.
   - `CONVEX_SITE_URL` → **never set** (Convex auto-injects the `.convex.site` issuer).
4. Push the current `bccab79` schema/functions cleanly (no schema change): `npx convex dev --once`.

**Verify:** `npx convex env list` shows `ALLOW_TEST_SEED` absent and `WORKER_SECRET`/`WEBHOOK_SECRET`/`JWT_PRIVATE_KEY`/`JWKS` present; `npx convex run testing:seedTwoTenants '{}'` MUST error `test seeding disabled` (if it succeeds, the flag leaked — abort and re-remove). Sendblue path-token live: POST `https://<DEP>.convex.site/sendblue/inbound/wrong` → 401.

> **M7 destructive tighten is NOT in launch scope.** Flipping `messages.userId/channel/replyTarget` + `connectIntents.userId` to required and removing `claimNext` + the `ALLOWED_USER_NUMBER` short-circuit is DEFERRED (`docs/superpowers/plans/2026-06-14-M7-tighten-and-cutover-DEFERRED.md`). On promote-dev it CANNOT run — the operator's live legacy rows (`userId===undefined`) reject the schema push, and removing `claimNext` darks his worker. It is gated on the scoped-worker cutover (P4 Step B4 / P6). The optional/required state is invisible to end users.

### P2 — Web app → Vercel (BLOCKER; depends on P1 for the Convex URL, feeds P1's SITE_URL)

Ships `web/` (Next.js 15 App Router) to Vercel pointing at `<DEP>`. The web app needs **no server-side secrets** — all auth secrets live on Convex. No `CONVEX_DEPLOY_KEY` (codegen never runs: `_generated/api.js` is committed and is just `export const api = anyApi` from the `convex` dep).

**Pre-flight (local):**
1. `cd /Users/saveliy/Documents/Amyris/web && git rev-parse HEAD` (expect `bccab79…`), `npm ci`, `npx tsc --noEmit` (0 errors), `npm run build` (exit 0). The build lists routes `/`, `/signin`, `/connect`, `/dashboard`, `middleware`. If it fails on `Cannot find module '../control-plane/convex/_generated/api'`, confirm those files are committed (`git ls-files control-plane/convex/_generated/` — verified present at `bccab79`).
2. **Add `web/vercel.json`** (none today) to encode build config in-repo:
   ```json
   { "$schema": "https://openapi.vercel.sh/vercel.json", "framework": "nextjs", "buildCommand": "next build", "installCommand": "npm install" }
   ```
3. **Pin Node** in `web/package.json`: `"engines": { "node": "22.x" }`. Commit both on a branch.

**The `@cp/api` cross-dir gotcha — DECISION 4A:** `web/tsconfig.json` maps `@cp/api → ../control-plane/convex/_generated/api`, a sibling dir outside `web/`. `next.config.mjs` already sets `outputFileTracingRoot` to the repo root, so the only requirement is that the committed sibling files are in the build context. **In Vercel: Root Directory = `web` AND enable "Include source files outside of the Root Directory in the Build Step"** — the single most important toggle. (Fallback if flaky: vendor `_generated/` into `web/cp-generated/` and repoint the alias. REJECTED: running `convex codegen` in the build — unnecessary, would need a deploy key for no benefit.)

**Vercel project setup:**
4. Dashboard → Add New → Project → import `Ageree/amyris-hermes`. Root Directory = `web`; Framework = Next.js (auto); Build = `next build`; Install = `npm install`; **enable the outside-root toggle**; Production Branch = `main`.
5. Set env vars (all `NEXT_PUBLIC_*`, **build-inlined → must exist before first deploy; changing one requires a redeploy**), Production scope:
   | Key | Value |
   |---|---|
   | `NEXT_PUBLIC_CONVEX_URL` | `https://zany-tapir-501.convex.cloud` |
   | `NEXT_PUBLIC_TELEGRAM_BOT_USERNAME` | `hermessanchez_bot` (no `@`) |
   | `NEXT_PUBLIC_IMESSAGE_NUMBER` | `+16466208124` |
6. **First deploy:** `cd web && npx vercel --prod`. Note the origin (e.g. `https://amyris-hermes.vercel.app`).
7. **Point Convex `SITE_URL` at the Vercel origin (closes P1's deferred BLOCKER):** `cd ../control-plane && npx convex env set SITE_URL "https://<project>.vercel.app"`. Convex Auth issues/validates the JWT cookie against `SITE_URL`; mismatch loops protected routes to `/signin`. (Do NOT touch auto-injected `CONVEX_SITE_URL`.)

**Verify:** Build log shows "Using Node.js 22.x", outside-root enabled, `✓ Compiled successfully`, the route list, and NO `Cannot find module '../control-plane/...'`. Then `curl` the alias: `/` → 200, `/signin` → 200, `/dashboard` (unauthed) → redirects to `/signin`. Full auth round-trip on the production alias (the real launch gate): signup email+password (≥8 chars) → lands on `/dashboard` (no loop), reload stays authed, `/dashboard` shows live tier/usage/connections, sign-out → `/dashboard` redirects to `/signin`. A loop back to `/signin` means `SITE_URL` ≠ origin — re-check step 7.

> Preview deployments get unique URLs ≠ `SITE_URL`, so **preview auth is known-broken** (expected). Test auth only on the production alias; do not gate launch on preview auth.

### P3 — Channels go-live: Telegram + iMessage (BLOCKER; depends on P1+P2)

Both inbound webhooks are always-on at `https://<DEP>.convex.site` (`control-plane/convex/http.ts`). Sanity first: POST `/telegram/inbound` → 401 (pre-secret, fails closed), POST `/sendblue/inbound/wrong` → 401.

**A. Telegram (NEW rotated token).** Read the token from `~/.hermes-savedlab/telegram_token`; commands print only HTTP status, never the token.
1. **Validate the token is the right bot:** `curl -s "https://api.telegram.org/bot$(cat ~/.hermes-savedlab/telegram_token)/getMe"` → must print `8649699230 hermessanchez_bot`. If `id` differs or `ok:false` → STOP.
2. **Generate + set the webhook header secret** (separate from the bot token): `TG_WH_SECRET="$(openssl rand -hex 32)"; npx convex env set TELEGRAM_WEBHOOK_SECRET "$TG_WH_SECRET"`. This is the unblock — `http.ts` 401s all Telegram traffic until it exists.
3. **Write the rotated bot token to the worker env for OUTBOUND replies** (DECISION A): `TELEGRAM_BOT_TOKEN=…` in `~/.hermes-savedlab/.env`, then restart the worker. Without this, inbound is received but replies never SEND.
4. **Register the webhook:** `setWebhook` with `url=https://<DEP>.convex.site/telegram/inbound`, `secret_token=$TG_WH_SECRET`, `allowed_updates:["message"]`, `drop_pending_updates:true`.
5. **Confirm:** `getWebhookInfo` → `url` matches, `pending==0`, `last_error_message` empty/absent. A `401 Unauthorized` in `last_error_message` means the Convex secret ≠ the `setWebhook` secret — re-run steps 2/4 with the same value.

**Verify (Telegram):** From a real NON-operator phone, `/start <token>` (mint via the `/connect` wizard, or `npx convex run pairing:issue '{"workerSecret":"…","userId":"…","channel":"telegram"}'`) → binding flips verified (reactive in `/dashboard`); send `привет` → a `messages` row (`channel:"telegram"`, `replyTarget:"<chatId>"`, the test user's `userId`) advances `queued→processing→done` and a lowercase reply lands in the same chat (~2–10s). Re-sending the same `update_id` does NOT double-enqueue (dedup on `handle`).

**B. iMessage / Sendblue (shared number +16466208124).** On promote-dev, Sendblue already points at `https://zany-tapir-501.convex.site/sendblue/inbound/<WEBHOOK_SECRET>` — **NO repoint needed; skip to verify.** (Repoint only if prod was promoted and `<DEP>` changed: confirm `WEBHOOK_SECRET` on `<DEP>`, then `npx @sendblue/cli@latest webhooks add "https://<DEP>.convex.site/sendblue/inbound/<WH>" --type receive`, remove any stale entry — in lockstep with the worker pointing at the same deployment or inbound goes dark.) The operator (`+79217818876`) stays on the LEGACY `ALLOWED_USER_NUMBER` short-circuit (`http.ts:77`) → rows with `userId===undefined` claimed by global `claimNext`. **Do NOT touch the short-circuit this session** (that is the deferred M7 cutover, P6).

**Verify (iMessage):** `HERMES_ENV=~/.hermes-savedlab/.env bash lab/scripts/live_ping.sh` → `LIVE_PING_OK` and exactly one `ping …` iMessage on the operator's iPhone. Run BEFORE and AFTER any channel change as the zero-downtime gate. Probe the live Sendblue URL the way Sendblue will (server UA, JSON): correct token + empty body → 200 `{ignored:true}`; wrong token → 401.

**Cross-talk / isolation (do before calling channels "live"):** (1) operator iMessage + a separate bound Telegram user send simultaneously → each reply goes only to its own address, two rows with different `userId`/`channel`/`replyTarget`. (2) Unbound phone (both channels) → 200 `{ignored:true}`, no enqueue, no reply, no budget spend. (3) Tenant's reply does not reference operator history (`_fetch_history` scoped by `userId`, invariant A1). (4) A redeemed pairing token can't be reused (single-use, 15-min TTL, cross-user-rejected).

### P4 — Execution model: the bridge (BLOCKER if D2=bridge; depends on P1)

Runs against `<DEP>`. Branch `feat/claim-next-any-bridge`. TDD throughout.

1. **B1 — Add `claimNextAny` to `control-plane/convex/messages.ts`** (additive; do NOT touch `claimNext` or `claimNextForUser`). Claims the oldest `queued` row across all tenants via the existing `by_status` index (`["status","receivedAt"]`):
   ```ts
   const row = await ctx.db.query("messages")
     .withIndex("by_status", q => q.eq("status", "queued"))
     .order("asc").first();
   ```
   Same `assertWorker(workerSecret)` gate, same atomic patch-to-`processing`, same `claimReturns` shape as `claimNextForUser`, minus the userId filter and the per-tenant `agentInstances` bump.
   **Verify:** a `convex_e2e` test enqueues rows for two `userId`s and asserts oldest-first across tenants, sets `processing`, and a second claim does not re-return a claimed row (at-most-once). `npx convex dev --once` pushes clean; function visible in the dashboard.
2. **B2 — Add `WORKER_MODE=shared` to `lab/skeleton/worker.py`** (`process_one`, ~L698). Third branch alongside the existing `scoped` (→`claimNextForUser`, needs `USER_ID`) and `legacy` (→`claimNext`, userId undefined, ~L327 default). `shared` → `claimNextAny` (no userId). Everything downstream is already tenant-correct (per-row `replyTarget`, `userId`-scoped history, per-`user_id` quota, iMessage+Telegram registry) — ~10 LOC + a flag.
   **Verify:** unit-test the dispatch branch; run the network-free lab subset green. Real two-tenant e2e against `<DEP>`: enqueue one iMessage-bound + one Telegram-bound row for two users, start the worker in `shared`, confirm each reply lands on its own `replyTarget`, neither leaks to the operator; watch the per-msg log (`lane=… userId=… dt=Ss`).
3. **B3 — Run ONE always-on worker.** DECISION: operator's existing launchd Mac (free, proven; `com.savedcontent.worker` in `~/.hermes-savedlab/worker/` — relocated there because launchd can't read `~/Documents`, TCC exit 126) for a dogfood start, OR a small always-on cloud VM (`e2-small`, ~$13/mo) for a real public launch where strangers message at any hour and the Mac sleeps. **Recommend the cloud VM for a true public launch; Mac is fine for a few dogfood days.** Set `WORKER_MODE=shared`, redeploy/restart.
   **Verify:** `launchctl list | grep com.savedcontent.worker` (col1=live PID) or `systemctl status hermes-bridge-worker`; worker log shows `WORKER_MODE=shared` at boot; a real inbound from a second identity gets a reply within ~30s.

> **Honest downside:** single process → one slow Hermes turn head-of-line-blocks other tenants (mitigated by the ~2s fast lane; invisible at 0–5 users; it is the trigger to migrate to the fleet). Messages stay durably `queued` while no worker runs (at-most-once claim holds), so a brief gap loses nothing.

### P5 — Security + test gate (BLOCKER; final gate before opening signups)

Most items fold into earlier phases; this phase is the consolidated checklist + the test matrix below.
1. `ALLOW_TEST_SEED` absent (P1) — re-confirm `npx convex env list | grep -c ALLOW_TEST_SEED` → 0; `testing:seedTwoTenants` throws.
2. **Rotate the 7 keys** (D5, recommend now). Brain-side keys in `~/.hermes-savedlab/.env` (MiniMax×2, Sendblue×2, Composio, Telegram token) — rotate at each vendor, write via a script that prints only length+prefix, preserve `chmod 600`, restart the worker. `EXA_API_KEY` lives on Convex AND the lab `.env` — update both. **Verify:** `git log -p --all -S '<old-key-prefix>'` returns nothing per key (if a key IS in history, the value is permanently public — rotation is mandatory, not optional); grep deployed Vercel JS for each prefix → zero hits (only the 3 `NEXT_PUBLIC_*` values); one live message per channel post-rotation works.
3. **No secret in client bundle/logs (A7):** only the 3 `NEXT_PUBLIC_*` vars in client JS (the app imports only static `_generated/api.js`, never `auth.ts`/runtime). Worker + Convex logs during a live message contain no key/body. The `⚠️ DANGEROUS COMMAND` approval-prompt leak is already fixed (`hermes_bridge _APPROVAL` strip) — re-confirm clean.
4. **Webhook auth live (A4/T9):** Sendblue wrong-token → 401; correct-token + unknown sender → 200 `{ignored:true}` no enqueue; Telegram no/wrong header → 401.
5. **`WORKER_SECRET`:** ≥32 bytes (current 48-hex ~192 bits ✓); exists only in Convex env + worker `.env`; `assertWorker` rejects a bogus secret.
6. **FOLLOW (non-gating):** strip `testing.ts` from the prod bundle; per-tenant secrets; per-sender failed-pair rate-limiting (tokens are high-entropy, low brute-force risk at launch volume); Sentry on the web/edge (public DSN, safe in bundle); Google/Resend auth providers.

## Pre-launch test matrix

Run against the launch deployment (`zany-tapir-501`) and the **production Vercel alias** (never a preview — preview origin ≠ `SITE_URL` breaks the auth cookie). Sequencing: P1 hygiene + key rotation + `SITE_URL` land before T1–T4; T2 needs the new token + `TELEGRAM_WEBHOOK_SECRET` + `setWebhook`; T5's seeding runs once `ALLOW_TEST_SEED` is decided.

| Test | How | Pass criterion |
|---|---|---|
| **T1 — Web auth e2e** | Drive the production alias: landing → `/signin` signup (email + ≥8-char password) → tier (pro → billing-stub copy) → Telegram → real QR/deep-link → reactive bind flip → `/dashboard`. | Full flow, NO signin→dashboard loop (proves `SITE_URL`); binding flips live; `/dashboard` shows tier/usage/connections. **BLOCKER** |
| **T2 — Telegram roundtrip** | New token brain-side + `TELEGRAM_WEBHOOK_SECRET` set + `setWebhook(secret_token=…)`; `/start <token>` from a real account, then a normal message. | `/start` flips binding verified; message enqueues (`channel="telegram"`), worker claims, reply arrives in the same chat. **BLOCKER** |
| **T3 — iMessage roundtrip** | Sendblue receive-webhook confirmed on `<DEP>`; pair via `pair <code>`, text `+16466208124`. | Inbound enqueues, worker claims, reply to the same thread; greet ~2s fast lane. **BLOCKER** |
| **T4 — Two-tenant isolation** | Two REAL accounts (operator + a fresh signup), each paired to its own channel; send near-simultaneously. | Each reply to its OWN `replyTarget` (zero cross-talk); each `_fetch_history` returns only that user's messages (A1); per-user follow-up context resolves. **BLOCKER** |
| **T5 — Quota enforcement** | Free default cap (100/30d) or a low test quota on a throwaway tenant; drive past the cap. | At cap, further messages refused/parked with the correct user-facing message; usage scoped per `userId`; last-unit claim atomic (no over-count). **BLOCKER** |
| **T6 — Cold-start** | First message when no worker recently served that path. | Served (durable enqueue holds even if best-effort cold-start fails); reply arrives; webhook never returns 5xx (would trigger provider retry). **BLOCKER** |
| **T7 — Billing-stub copy** | On `/connect` + `/dashboard`, inspect paid tiers (pro $19/1000, max $49/5000 per 30d). | Paid tiers show "launching soon", user stays on free (never charged, no payment UI), provider-adapter seam not bypassed. **BLOCKER** |
| **T8 — Smoke / load** | Burst 10–20 messages across 2–3 tenants at the single worker. | All eventually `complete` (none stuck past the 15-min `reapStaleProcessing`); at-most-once (no duplicate replies); trivial turns ~2s; document the head-of-line tail. **Smoke BLOCKER; sustained load FOLLOW** |
| **T9 — Webhook auth (security)** | The three `curl` checks vs the live URL. | Sendblue wrong-token → 401; correct + unknown sender → 200 ignored, no enqueue; Telegram no/wrong header → 401. **BLOCKER** |
| **T10 — Bundle/log secret scan** | Grep deployed JS + live logs. | JS contains only the 3 `NEXT_PUBLIC_*` values; logs contain no key/secret/body. **BLOCKER** |

## Rollback & safety

- **Bad Vercel deploy/build:** Deployments → Promote the last-known-good to Production (instant alias re-point), or `npx vercel rollback <url>`. Web app is stateless; all state is in Convex — no data risk.
- **Auth broke after a `SITE_URL` change (e.g. domain swap):** `npx convex env set SITE_URL "<previous-origin>"`. Convex env takes effect on the next function call (no web redeploy unless a `NEXT_PUBLIC_*` value also changed — those are build-inlined and need a Vercel redeploy).
- **Wrong `NEXT_PUBLIC_CONVEX_URL`:** fix the env var, then `npx vercel --prod` (build-inlined — an env edit alone does not take effect).
- **`claimNextAny`/bridge:** purely additive; roll back by unsetting `WORKER_MODE=shared` (revert to `scoped`/`legacy`) and the worker reverts. `claimNext` stays alive as the operator's escape hatch. Optionally delete the function on next push. Zero impact on the live legacy path.
- **Telegram webhook:** `deleteWebhook` (or re-`setWebhook`); `drop_pending_updates:true` on re-register discards stale updates.
- **Sendblue repoint (only if done):** re-add the previous receive URL via `@sendblue/cli`; live-ping before/after.
- **Operator cutover (P6/B4):** re-enable the `ALLOWED_USER_NUMBER` short-circuit (revert the `http.ts` edit, `npx convex dev --once`); operator's rows return to `userId===undefined`; keep his legacy `claimNext` worker until the shared path is confirmed.

**Must NEVER happen:**
- `ALLOW_TEST_SEED=1` on the launch deployment (re-enables billing-bypass/forgery seeders). Re-check before every deploy.
- `npx convex deploy` run autonomously — it targets the empty prod `adept-dragon-928` and requires re-creating every env var + JWT key first. Operator-only.
- Running the M7 destructive schema tighten as part of launch — the push is rejected by existing legacy rows and the operator goes dark. Stays deferred; `claimNext` stays alive.
- Pasting any rotated token/secret into chat or committing it; bot token via file/`chmod 600` only.

## Out of scope / later

- **P6 — Operator worker cutover to scoped/shared + M7 destructive tighten** (run WITH the operator present, zero-downtime): backfill audit (0 rows missing `userId`/`channel`/`replyTarget`, 0 `connectIntents` missing `userId`), verify the operator has a verified iMessage `channelBinding`, then disable the `ALLOWED_USER_NUMBER` short-circuit so he routes via bindings; finally flip `messages.userId/channel/replyTarget` + `connectIntents.userId` to required and remove legacy `claimNext`. DEFERRED (`docs/superpowers/plans/2026-06-14-M7-tighten-and-cutover-DEFERRED.md`).
- **GCP per-user container fleet (LOCKED-#1 end-state, F1–F5):** fix the unbuildable image (`Dockerfile.fleet:101` `your-org` placeholder → real Hermes URL + clone auth), `scripts/fleet/provision-host.sh --apply` + manual gaps (disk mount, Artifact Registry Docker auth, controller systemd unit — not in repo), Cloud Build push, launch one tenant, then close the two launch-blocking review gaps: **fabricated host metrics → OOM risk** (build a per-host `/metrics` agent) and **no periodic state mirror → crash loses logins** (timer-based GCS mirror). Then flip each user to `WORKER_MODE=scoped` and retire the shared worker + `claimNextAny`. ~1–2 days minimum just to run one tenant. Documented in `docs/superpowers/plans/2026-06-15-review-findings-and-deferrals.md`.
- **Fresh prod `adept-dragon-928` promotion** (separate gated decision; recreates all env + JWT keys + `SITE_URL`, re-points both webhooks, re-pairs operator; best paired with the M7 tighten from row #0).
- **Real paid billing** (Paddle/Stripe behind the existing provider-adapter seam) — pro/max stay "launching soon" at launch.
- **Custom domain** (D4 follow-up — `*.vercel.app` ships fine; swap is a `SITE_URL` re-point + auth re-verify).
- **Google + Resend-OTP auth providers** (set the respective Convex env vars; Google callback on `.convex.site`, not Vercel).
- **Hardening:** strip `testing.ts` from the prod bundle, per-tenant secrets, per-sender failed-pair rate-limiting, Sentry, fleet horizontal scale (remote `DockerDriver`/SSH — single-host only today), versioned GCS bucket (replace `rsync --delete`), containers-as-non-root, quota-race test, sustained load testing.
