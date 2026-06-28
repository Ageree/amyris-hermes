#!/bin/sh
# eve-fleet-entrypoint.sh — one per-tenant container: headless Chrome (for order.py)
# + the Eve brain (node Nitro server) + the scoped drainer/poller, started in order.
# Runs as the PID-child of tini (the image ENTRYPOINT). Mirrors the old fleet's
# fleet-entrypoint.sh (launch the browser, then exec the worker) with the brain
# swapped Hermes -> Eve and an Eve-health gate added before the poller starts.
#
# ponytail: the background Chrome + Eve server are owned by the container, not
# supervised — on `docker stop` tini SIGTERMs the drainer (the exec'd child) and the
# container teardown (SIGKILL) takes Chrome + Eve with it. The container is the unit of
# restart; the controller relaunches the whole thing on crash. Upgrade path = a real
# supervisor (s6/supervisord) only if one process ever needs independent restart.
set -e

EVE_PORT="${EVE_PORT:-4123}"
PROFILE="${HERMES_HOME:-/data/tenants/default}/chrome-profile"

# (a) headless Chrome with CDP for order.py (browser-use attaches via ORDER_CDP_URL).
#     Per-tenant profile under HERMES_HOME (persistent + GCS-mirrored = the user's
#     Yandex login + linked card). A NON-default user-data-dir is required for headless.
mkdir -p "$PROFILE"
CHROME="$(command -v chromium || command -v chromium-browser || echo /usr/bin/chromium)"
"$CHROME" --headless=new --remote-debugging-port=9222 \
    --user-data-dir="$PROFILE" --remote-allow-origins="*" \
    --no-sandbox --disable-gpu --disable-dev-shm-usage \
    --no-first-run --no-default-browser-check \
    >/tmp/chrome.log 2>&1 &
echo "eve-fleet: launched headless Chrome (CDP :9222, profile $PROFILE)"

# (b) the Eve brain — self-contained Nitro server, bound to loopback (only the local
#     drainer reaches it). Model = direct OpenRouter (MINIMAX_* in env) — no Vercel.
PORT="$EVE_PORT" NITRO_PORT="$EVE_PORT" NITRO_HOST=127.0.0.1 \
    node /app/eve/.output/server/index.mjs >/tmp/eve.log 2>&1 &
echo "eve-fleet: launched Eve server (port $EVE_PORT, loopback 127.0.0.1)"

# (c) wait for Eve health (bounded ~30s: 60 * 0.5s). Fail closed if it never comes up
#     so the controller restarts a wedged container instead of the drainer polling a
#     dead brain. -f makes curl exit non-zero on any HTTP >= 400 (e.g. a 404 while
#     Nitro is still booting), so the loop only breaks on a real 200.
HEALTH="http://127.0.0.1:${EVE_PORT}/eve/v1/health"
i=0
until curl -fsS "$HEALTH" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 60 ]; then
        echo "eve-fleet: Eve health ($HEALTH) not ready after ~30s — aborting" >&2
        cat /tmp/eve.log >&2 2>/dev/null || true
        exit 1
    fi
    sleep 0.5
done
echo "eve-fleet: Eve healthy at $HEALTH"

# (d) exec the SCOPED drainer. USER_ID is injected by the controller -> the drainer
#     claims via messages:claimNextForUser (not claimNextAny). EVE_URL + ORDER_CDP_URL
#     point at this container's loopback services; re-export them from EVE_PORT so an
#     EVE_PORT override stays consistent even if the image-ENV default lags.
export EVE_URL="http://127.0.0.1:${EVE_PORT}"
export ORDER_CDP_URL="${ORDER_CDP_URL:-http://127.0.0.1:9222}"
echo "eve-fleet: exec drainer (USER_ID=${USER_ID:-<unset!>} EVE_URL=$EVE_URL ORDER_CDP_URL=$ORDER_CDP_URL)"
exec node /app/drainer/drainer.mjs
