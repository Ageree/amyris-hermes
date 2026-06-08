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

See `../lab/skeleton/worker.py` + `run-worker.sh`. Start it with:

```bash
../lab/skeleton/run-worker.sh        # polls forever; Ctrl-C to stop
```

It needs `CONVEX_URL` + `WORKER_SECRET` (and the Sendblue creds) in
`~/.hermes-savedlab/.env`.

## Going live (operator, one-time, ~2 min)

1. Paste this into Sendblue dashboard → Settings → Webhooks:
   `https://zany-tapir-501.convex.site/sendblue/inbound/<WEBHOOK_SECRET>`
2. Start the worker (`run-worker.sh`).
3. iMessage the Sendblue number (`+16466208124`) any browser task.

Verified live e2e 2026-06-08 (see `../lab/REPORT.md` → "Phase-1C").
