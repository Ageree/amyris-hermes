#!/usr/bin/env bash
# Fleet controller launcher.
# Reads configuration from environment variables (see config.py).
# Pass --once for a single reconcile pass (local harness / smoke-test).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env if present (development only; prod uses systemd EnvironmentFile)
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' "${SCRIPT_DIR}/.env" | xargs)
fi

exec python3 "${SCRIPT_DIR}/controller.py" "$@"
