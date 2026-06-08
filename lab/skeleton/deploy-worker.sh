#!/usr/bin/env bash
# Deploy the brain-side worker to a launchd-runnable location OUTSIDE ~/Documents.
#
# WHY: macOS TCC denies a launchd daemon from reading file *contents* under
# ~/Documents (privacy-protected) — a LaunchAgent pointed at the repo copy dies
# with exit 126 / "Operation not permitted". The interactive shell works only
# because it inherits a TCC grant. So for a real always-on daemon we deploy a
# self-contained copy of the worker (+ its own venv) into ~/.hermes-savedlab/worker
# (a dotfolder in HOME, NOT a TCC-protected location) and point launchd there.
#
# The repo stays the SOURCE OF TRUTH: re-run this script after editing any worker
# module to redeploy. Idempotent.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"           # lab/skeleton (repo)
DEST="$HOME/.hermes-savedlab/worker"
MODULES=(worker.py convex_client.py sendblue_client.py hermes_bridge.py fast_lane.py bubbles.py typing_indicator.py)

echo "deploy: $SRC -> $DEST"
mkdir -p "$DEST"
for m in "${MODULES[@]}"; do
  cp "$SRC/$m" "$DEST/$m"
done

# SOUL.md — the fast lane reads it for the assistant's voice. Copied beside the
# worker so _load_soul() finds it with no HERMES_HOME lookup.
cp "$SRC/../personality/SOUL.md" "$DEST/SOUL.md"

# Composio client (worker imports it for intent polling) + the connections skill
# scripts (so they're available to the deployed worker's Hermes via the skill dir).
CONN_SRC="$(cd "$SRC/../skills/connections/scripts" && pwd)" || { echo "deploy: skills/connections/scripts not found" >&2; exit 1; }
cp "$CONN_SRC/composio_api.py" "$DEST/composio_api.py"

# Self-contained venv (the repo lab/.venv is under ~/Documents -> unreadable by
# launchd). Created with the system python; only needs `requests`.
if [ ! -x "$DEST/venv/bin/python" ]; then
  echo "deploy: creating venv at $DEST/venv"
  /usr/bin/python3 -m venv "$DEST/venv"
fi
"$DEST/venv/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
"$DEST/venv/bin/python" -m pip install --quiet requests

# Runner: sources the live .env (CONVEX_URL/WORKER_SECRET/SENDBLUE_*/ALLOWED_USER_NUMBER/
# AGENT_BROWSER_PROFILE), exports the Hermes paths, runs the worker from this dir.
cat > "$DEST/run.sh" <<'RUN'
#!/usr/bin/env bash
set -euo pipefail
set -a; . "$HOME/.hermes-savedlab/.env"; set +a
export HERMES_HOME="$HOME/.hermes-savedlab"
export HERMES_DIR="${HERMES_DIR:-$HOME/hermes-agent}"
export HERMES_PYTHON_BIN="${HERMES_PYTHON_BIN:-$HOME/hermes-agent/venv/bin/python}"
export POLL_INTERVAL="${POLL_INTERVAL:-0.5}"
export IDLE_POLL_INTERVAL="${IDLE_POLL_INTERVAL:-3.0}"
export HERMES_TIMEOUT="${HERMES_TIMEOUT:-220}"
export COMPOSIO_USER_ID="${COMPOSIO_USER_ID:-$ALLOWED_USER_NUMBER}"
: "${CONVEX_URL:?set CONVEX_URL in ~/.hermes-savedlab/.env}"
: "${WORKER_SECRET:?set WORKER_SECRET in ~/.hermes-savedlab/.env}"
: "${SENDBLUE_API_KEY_ID:?set SENDBLUE_API_KEY_ID in ~/.hermes-savedlab/.env}"
: "${ALLOWED_USER_NUMBER:?set ALLOWED_USER_NUMBER in ~/.hermes-savedlab/.env}"
cd "$(dirname "$0")"
exec ./venv/bin/python worker.py
RUN
chmod +x "$DEST/run.sh"

echo "deploy: done."
echo "  modules: ${MODULES[*]}"
echo "  venv:    $DEST/venv ($("$DEST/venv/bin/python" --version 2>&1))"
echo "  runner:  $DEST/run.sh"
