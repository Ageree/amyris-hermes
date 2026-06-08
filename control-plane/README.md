# Control plane — durable Convex queue (P1C)

Always-on Convex backend that decouples Sendblue from the brain. Sendblue posts
inbound iMessages to a **stable** `*.convex.site` URL (no tunnel, no public port
on the Mac). Messages are stored durably, then the brain (Hermes + real browser)
**polls** for work. If the brain is offline, messages wait as `queued` and are
processed when it comes back — nothing is lost.

```
iMessage ─► Sendblue ─► POST https://<dep>.convex.site/sendblue/inbound/<WEBHOOK_SECRET>
                              │  (auth: secret path token + ALLOWED_USER_NUMBER allowlist)
                              ▼
                      Convex durable queue  (messages: queued→processing→done/error)
                              ▲
        worker (lab/skeleton/worker.py) polls claimNext ─► run_hermes(+browser) ─► Sendblue reply ─► complete/fail
```

This replaces the throwaway FastAPI bridge (`lab/skeleton/app.py` + cloudflared/
loca.lt tunnel) proven in Phase-1A.

## Deployment (operator's own Convex account)

- Team `savelii-solov-iov`, project `saved-content-assistant`.
- Dev deployment: `dev:zany-tapir-501` → `https://zany-tapir-501.convex.cloud`
  (HTTP actions at `https://zany-tapir-501.convex.site`).
- Functions are deployed; env vars are set on the deployment:
  `WEBHOOK_SECRET`, `ALLOWED_USER_NUMBER`, `WORKER_SECRET`.

Redeploy after editing `convex/*.ts`:

```bash
cd control-plane && npx convex dev      # watch-mode push (codegen + deploy)
# or one-shot:  npx convex deploy
```

Set/rotate deployment env vars:

```bash
npx convex env set WEBHOOK_SECRET "<token>"
npx convex env set WORKER_SECRET  "<token>"
npx convex env set ALLOWED_USER_NUMBER "+79217818876"
```

## Functions (`convex/`)

- `http.ts` — `POST /sendblue/inbound/<token>`: constant-time token check
  (wrong → 401), allowlist on `ALLOWED_USER_NUMBER`, then `enqueue`. Never 5xx on
  payload problems (Sendblue retries 5xx); only auth is a 4xx.
- `messages.ts`
  - `enqueue` (internal) — idempotent on Sendblue `message_handle`.
  - `claimNext(workerSecret)` — atomically claim the oldest `queued` message.
  - `complete(workerSecret, id, reply)` / `fail(workerSecret, id, error)`.
  - `stats()` — counts by status (ops view).
- `schema.ts` — `messages` table; indexes `by_handle`, `by_status`.

The worker-facing functions are public but gated by a `workerSecret` **argument**
(not Convex auth), so the brain talks to them over the plain HTTP API with no
admin key. The HTTP webhook uses its own path-token secret.

## The brain (worker)

See `../lab/skeleton/worker.py`. Two ways to run it:

- **Foreground (dev):** `../lab/skeleton/run-worker.sh` (polls forever; Ctrl-C to stop).
- **Permanent (launchd daemon) — recommended:** `../lab/skeleton/deploy-worker.sh`
  then load the LaunchAgent (see below). Survives logout/reboot + auto-respawns on crash.

It needs `CONVEX_URL` + `WORKER_SECRET` (and the Sendblue creds) in
`~/.hermes-savedlab/.env`.

### Permanent worker via launchd (the TCC catch)

A LaunchAgent pointed at the repo copy **fails** — macOS TCC denies a launchd
daemon from reading file *contents* under `~/Documents` (exit 126 /
"Operation not permitted"); the interactive shell only works because it inherits
a TCC grant. **Fix: run the worker from OUTSIDE `~/Documents`.**
`deploy-worker.sh` copies the 4 worker modules + a self-contained venv to
`~/.hermes-savedlab/worker/` (a dotfolder, not TCC-protected) and writes its
`run.sh`. The repo stays source-of-truth — re-run `deploy-worker.sh` after editing
any worker module, then `launchctl kickstart -k gui/$(id -u)/com.savedcontent.worker`.

LaunchAgent at `~/Library/LaunchAgents/com.savedcontent.worker.plist`
(RunAtLoad + KeepAlive; `PATH` includes `/opt/homebrew/bin` so `agent-browser`
resolves; logs to `~/.hermes-savedlab/logs/`). Load:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.savedcontent.worker.plist
launchctl enable gui/$(id -u)/com.savedcontent.worker
launchctl kickstart -k gui/$(id -u)/com.savedcontent.worker
launchctl list | grep com.savedcontent.worker   # col1=PID (live), col2=last exit
```

### Persistent logins (agent-browser native profile)

`AGENT_BROWSER_PROFILE=~/.hermes-savedlab/browser-profile` in `~/.hermes-savedlab/.env`
makes the browser persist cookies/logins across runs (chosen over Camofox: no
install, no config.yaml change, agent-browser stays the default backend, fully
reversible). **One-time per site**, the operator logs in once in a visible window
(`agent-browser close` first — the daemon ignores `--profile` if already up):

```bash
AGENT_BROWSER_PROFILE=~/.hermes-savedlab/browser-profile /opt/homebrew/bin/agent-browser close
AGENT_BROWSER_PROFILE=~/.hermes-savedlab/browser-profile /opt/homebrew/bin/agent-browser --headed open https://SITE/login
#   ...log in by hand (incl 2FA)...
/opt/homebrew/bin/agent-browser close      # `close` is the real save/restart
```
Afterwards the headless worker reuses that session every run. One profile = one
worker at a time (satisfied: exactly one launchd worker).

## Going live — DONE (2026-06-08)

1. ~~Paste the webhook into the Sendblue dashboard~~ → **set via `@sendblue/cli`**
   (`webhooks add … --type receive`); confirmed with `sendblue webhooks list`.
2. ~~Start the worker~~ → **running as the launchd daemon** above.
3. iMessage `+16466208124` any browser task → it works.

Verified live e2e 2026-06-08 (see `../lab/REPORT.md`): real inbound iMessage
("10 Pinterest pins for grisch") round-tripped through Sendblue → Convex queue →
worker → Hermes(M3+browser) → iPhone; launchd KeepAlive respawn + queue e2e
re-verified after relocation.
