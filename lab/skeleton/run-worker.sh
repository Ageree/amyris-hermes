#!/usr/bin/env bash
# Brain-side worker for the durable Convex queue (P1C).
#
# Unlike the old run.sh (FastAPI bridge needing a public tunnel), this process
# is PURELY OUTBOUND: it polls the always-on Convex queue, runs Hermes (+real
# browser) on each message, replies via Sendblue, and marks the message done.
# Nothing has to reach this machine — so no tunnel, no inbound port, no
# cloudflared/loca.lt. The Mac (or a cloud VM) can sit behind NAT.
#
# Secrets come from ~/.hermes-savedlab/.env (chmod 600, NOT in the repo):
#   CONVEX_URL, WORKER_SECRET, SENDBLUE_API_KEY_ID, SENDBLUE_API_SECRET_KEY,
#   SENDBLUE_FROM_NUMBER, ALLOWED_USER_NUMBER, MINIMAX_API_KEY (Hermes reads its own).
set -euo pipefail

set -a; . "$HOME/.hermes-savedlab/.env"; set +a
export HERMES_HOME="$HOME/.hermes-savedlab"
export HERMES_DIR="${HERMES_DIR:-$HOME/hermes-agent}"
export HERMES_PYTHON_BIN="${HERMES_PYTHON_BIN:-$HOME/hermes-agent/venv/bin/python}"
export POLL_INTERVAL="${POLL_INTERVAL:-2.0}"
export HERMES_TIMEOUT="${HERMES_TIMEOUT:-220}"

: "${CONVEX_URL:?set CONVEX_URL in ~/.hermes-savedlab/.env}"
: "${WORKER_SECRET:?set WORKER_SECRET in ~/.hermes-savedlab/.env}"
: "${SENDBLUE_API_KEY_ID:?set SENDBLUE_API_KEY_ID in ~/.hermes-savedlab/.env}"
: "${ALLOWED_USER_NUMBER:?set ALLOWED_USER_NUMBER in ~/.hermes-savedlab/.env}"

# Run from the skeleton dir so worker.py's bare imports resolve; use the LAB venv
# (the worker only subprocesses the Hermes venv — it must not pollute it).
cd "$(dirname "$0")"
exec ../.venv/bin/python worker.py
