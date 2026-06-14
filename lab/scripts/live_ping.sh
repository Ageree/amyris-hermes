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
SITE="${CONVEX_SITE:-${CONVEX_URL/.convex.cloud/.convex.site}}"

done_count() {
  curl -s -X POST "$CONVEX_URL/api/query" -H 'content-type: application/json' \
    -d '{"path":"messages:stats","args":{},"format":"json"}' \
    | python3 -c 'import sys,json; print(json.load(sys.stdin).get("value",{}).get("done",0))'
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
