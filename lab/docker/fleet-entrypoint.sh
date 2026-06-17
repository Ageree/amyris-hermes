#!/bin/sh
# fleet-entrypoint.sh — launch a headless Chrome with CDP for browser-harness
# (Lane B), then exec the worker. Run as PID-child of tini (the image ENTRYPOINT).
#
# The browser is per-container (one tenant), so the CDP endpoint is local and the
# user-data-dir lives under HERMES_HOME (persistent + GCS-mirrored = per-user
# logins). Kill-switch: BROWSER_HARNESS_ENABLED=0 skips the browser entirely and
# the built-in Hermes browser stays as the fallback.
#
# Headless noise (SSL handshake failed -100 / DEPRECATED_ENDPOINT) is benign —
# CDP still works. ponytail: single shared Chrome per container; remote/cloud
# would point BU_CDP_WS at an external browser and skip this launch.
set -e

if [ "${BROWSER_HARNESS_ENABLED:-1}" != "0" ] && [ -x /usr/local/bin/browser-harness ]; then
    CHROME="$(command -v chromium || command -v chromium-browser || echo /usr/bin/chromium)"
    if [ -x "$CHROME" ]; then
        PROFILE="${HERMES_HOME:-/data/tenants/default}/chrome-profile"
        mkdir -p "$PROFILE"
        # NON-default user-data-dir is required (a default profile breaks headless).
        "$CHROME" --headless=new --remote-debugging-port=9222 \
            --user-data-dir="$PROFILE" "--remote-allow-origins=*" \
            --no-sandbox --disable-gpu --disable-dev-shm-usage \
            --no-first-run --no-default-browser-check \
            >/tmp/chrome.log 2>&1 &
        echo "fleet-entrypoint: launched headless Chrome (CDP :9222, profile $PROFILE)"
    else
        echo "fleet-entrypoint: no chromium found — skipping browser launch" >&2
    fi
fi

exec python3 worker.py
