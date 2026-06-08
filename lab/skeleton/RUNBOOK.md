# Phase-1A Walking Skeleton — Live Test Runbook

The end-to-end loop: **your iMessage → Sendblue webhook → local Hermes (MiniMax-M3 + real browser) → reply back to your iPhone.** Everything code-side is built, hardened, and unit-tested (55 green); the local Hermes+browser spine is already validated live. What's left is operator-only.

## Status of prerequisites (auto-verified 2026-06-08)
- ✅ MiniMax-M3 routing fixed — flag-less Hermes resolves M3; browser-in-loop returned `Example Domain`.
- ✅ Lab venv has deps (FastAPI/uvicorn/httpx). Skeleton + Phase-0 tests green.
- ✅ `WEBHOOK_SECRET` generated and written to `~/.hermes-savedlab/.env`.

## You need to do 3 things (≈5 min, at your Mac + iPhone)

### 1. Fill two phone numbers in `~/.hermes-savedlab/.env`
Open it and set (E.164 format, e.g. `+14155550123`):
```
SENDBLUE_FROM_NUMBER=    # the shared Sendblue number (the "from")
ALLOWED_USER_NUMBER=     # YOUR iPhone's iMessage handle (the only number we reply to)
```
`WEBHOOK_SECRET` is already set. (Optionally first run the outbound smoke to confirm the number works:
`set -a; . ~/.hermes-savedlab/.env; set +a && python lab/skeleton/scripts/smoke_send.py "$ALLOWED_USER_NUMBER" "$SENDBLUE_FROM_NUMBER"` — you should get an iMessage.)

### 2. Start the bridge + a public tunnel
```bash
cd <repo>/lab/skeleton
./run.sh                      # boots on 127.0.0.1:8787, validates env, refuses placeholders
# in a second terminal:
brew install cloudflared 2>/dev/null; cloudflared tunnel --url http://127.0.0.1:8787
```
`cloudflared` prints `https://<random>.trycloudflare.com`. Your webhook URL is:
```
https://<random>.trycloudflare.com/sendblue/inbound/<WEBHOOK_SECRET>
```
(the `<WEBHOOK_SECRET>` value is the one in `.env` — the secret path token authenticates every request).

### 3. Register the webhook + send a test
- Paste that full URL into the **Sendblue dashboard → Settings → Webhooks** (webhook config is dashboard-only).
- From your iPhone, iMessage the Sendblue number: **"Open example.com and tell me its H1."**
- Expected: within a few seconds you get a reply containing **"Example Domain"** — proving iMessage ↔ M3 ↔ real browser ↔ iMessage.

## Security notes (already implemented)
- The endpoint is `/sendblue/inbound/{token}`; a wrong/absent token → 401 (no Hermes run, no reply).
- We only ever reply to `ALLOWED_USER_NUMBER`, never to the inbound payload's number (no open relay).
- Empty `message_handle` is rejected; dedup is bounded; the Hermes subprocess is non-blocking, capped at `MAX_CONCURRENCY` (default 1), 60 s timeout.

## After it works
Record round-trip latency + M3 token cost for the turn in `lab/REPORT.md` (Task 8 gate). Then we move to P1B (Camofox "log-in-once" Lane A + browser-first saved-content).
