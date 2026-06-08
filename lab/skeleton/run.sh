#!/usr/bin/env bash
# Boot the Phase-1A walking-skeleton webhook bridge (local, single-user).
# See RUNBOOK.md for the full live-test procedure.
set -euo pipefail

export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes-savedlab}"
if [ ! -f "$HERMES_HOME/.env" ]; then
  echo "ERROR: $HERMES_HOME/.env not found." >&2; exit 1
fi
set -a; . "$HERMES_HOME/.env"; set +a

# Required credentials/config (fail loudly with guidance — see RUNBOOK.md).
: "${SENDBLUE_API_KEY_ID:?missing in .env}"
: "${SENDBLUE_API_SECRET_KEY:?missing in .env}"
missing=0
for v in SENDBLUE_FROM_NUMBER ALLOWED_USER_NUMBER WEBHOOK_SECRET; do
  if [ -z "${!v:-}" ]; then echo "ERROR: $v is empty — set it in $HERMES_HOME/.env (see RUNBOOK.md)." >&2; missing=1; fi
done
[ "$missing" -eq 0 ] || exit 1

# Reject obvious placeholders: the two phone numbers must be E.164 (+digits).
for v in SENDBLUE_FROM_NUMBER ALLOWED_USER_NUMBER; do
  case "${!v}" in
    +[0-9]*) : ;;
    *) echo "ERROR: $v must be E.164 like +14155550123 (got: '${!v}')." >&2; exit 1 ;;
  esac
done

SKELETON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SKELETON_DIR/../.venv/bin/python"
[ -x "$VENV_PY" ] || { echo "ERROR: lab venv not found at $VENV_PY (run: cd lab && python3 -m venv .venv && .venv/bin/pip install -r skeleton/requirements.txt)." >&2; exit 1; }

PORT="${PORT:-8787}"
echo "Webhook bridge on http://127.0.0.1:$PORT  (inbound path: /sendblue/inbound/<WEBHOOK_SECRET>)"
echo "Health: curl -s http://127.0.0.1:$PORT/healthz"
exec "$VENV_PY" -m uvicorn asgi:app --app-dir "$SKELETON_DIR" --host 127.0.0.1 --port "$PORT"
