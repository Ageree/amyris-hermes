#!/usr/bin/env bash
# Live operator round-trip ping (operator-run).
#
# Posts a synthetic Sendblue inbound to the LIVE Convex webhook and waits for the
# durable queue's done-count to advance — proving the operator path
# (webhook -> durable queue -> worker -> reply) is alive. Used before/after risky
# migration steps to confirm zero downtime. NOTE: this causes the live assistant
# to send one real "ping ..." iMessage back to the operator (that's the point).
#
# Env (sourced from ~/.hermes-savedlab/.env by default; override with HERMES_ENV):
#   CONVEX_URL  WEBHOOK_SECRET  ALLOWED_USER_NUMBER   (CONVEX_SITE optional)
set -euo pipefail
ENV_FILE="${HERMES_ENV:-$HOME/.hermes-savedlab/.env}"
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi
: "${CONVEX_URL:?need CONVEX_URL}"
: "${WEBHOOK_SECRET:?need WEBHOOK_SECRET}"
: "${ALLOWED_USER_NUMBER:?need ALLOWED_USER_NUMBER}"
: "${WORKER_SECRET:?need WORKER_SECRET}"   # messages:stats is worker-gated
SITE="${CONVEX_SITE:-${CONVEX_URL/.convex.cloud/.convex.site}}"

done_count() {
  # messages:stats requires the workerSecret (hardened); read .value.done, and
  # surface a parse/auth failure as a clear error instead of a python traceback.
  # Flake-tolerant: the .convex.cloud TLS endpoint can intermittently drop the
  # connection (SSLEOFError) -> empty body. On any empty/error response emit
  # NOTHING (the poll loop reads that as "no change yet" and retries) instead of
  # crashing with a JSON traceback. done is a float (v.number) -> cast to int.
  curl -s -X POST "$CONVEX_URL/api/query" -H 'content-type: application/json' \
    -d "{\"path\":\"messages:stats\",\"args\":{\"workerSecret\":\"$WORKER_SECRET\"},\"format\":\"json\"}" \
    | python3 -c 'import sys,json
raw=sys.stdin.read().strip()
if not raw: sys.exit(0)
try: d=json.loads(raw)
except Exception: sys.exit(0)
if d.get("status")=="success": print(int(d.get("value",{}).get("done",0)))' 2>/dev/null
}

NONCE="$(date +%s)-$$"
HANDLE="ping-$NONCE"
before="$(done_count)"
echo "posting ping $HANDLE -> $SITE/sendblue/inbound/****"
curl -s -X POST "$SITE/sendblue/inbound/$WEBHOOK_SECRET" -H 'content-type: application/json' \
  -d "{\"content\":\"ping $NONCE\",\"number\":\"$ALLOWED_USER_NUMBER\",\"message_handle\":\"$HANDLE\"}" >/dev/null
echo "waiting for the worker to deliver (done was $before)..."
for _ in $(seq 1 30); do
  sleep 2
  now="$(done_count)"
  if [ "${now:-0}" -gt "${before:-0}" ]; then
    echo "LIVE_PING_OK (done $before -> $now)"; exit 0
  fi
done
echo "LIVE_PING_TIMEOUT (done stayed $before) — is the worker running?"; exit 1
