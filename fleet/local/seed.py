"""seed.py — enqueue messages for alice + bob; wait for both replies; assert routing.

Stdlib only.

This service:
  1. Waits for mock_outbound to be healthy.
  2. Enqueues one message for u_alice and one for u_bob via the Convex-shaped
     POST /api/mutation messages:enqueue endpoint.
  3. Polls GET /status until BOTH rows are done (the real workers claim+complete
     them) or SEED_TIMEOUT elapses.
  4. Triggers the /shutdown assertion on mock_outbound.
  5. Exits 0 only if both replies were correctly routed AND both tenants replied,
     else non-zero.  Drives docker-compose --exit-code-from seed.

Messages are URL-free so the worker's fast-lane URL prefilter doesn't skip the
fast lane (which would force a defer to the absent Hermes).

Also import-clean and callable from unit tests (run_seed_in_process) without HTTP.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

log = logging.getLogger("seed")

# URL-free messages (so the fast-lane prefilter doesn't skip to Hermes).
ALICE_USER_ID = "u_alice"
ALICE_REPLY_TARGET = "+1alice555"
ALICE_TEXT = "hi from alice"

BOB_USER_ID = "u_bob"
BOB_REPLY_TARGET = "+1bob999"
BOB_TEXT = "hi from bob"


# ---------------------------------------------------------------------------
# In-process driver (unit tests; no HTTP, no docker)
# ---------------------------------------------------------------------------

def run_seed_in_process(store: Any, worker_secret: Optional[str] = None) -> bool:
    """Drive the seed scenario directly against a MockStore (no HTTP).

    Simulates what the two scoped workers do: each claims ONLY its own row and
    completes it.  Then runs the cross-contamination assertion.

    `worker_secret` defaults to the store's own secret so callers don't repeat it.
    Returns True if the scenario passed cleanly.
    """
    secret = worker_secret if worker_secret is not None else store._worker_secret

    store.enqueue(ALICE_USER_ID, ALICE_TEXT, ALICE_REPLY_TARGET)
    store.enqueue(BOB_USER_ID, BOB_TEXT, BOB_REPLY_TARGET)

    # Worker-alice (scoped to u_alice) claims + completes her row.
    row_a = store.claim_next_for_user(secret, ALICE_USER_ID)
    if row_a is None:
        log.error("alice claim returned None")
        return False
    store.complete(secret, row_a["id"], "ok, handled.")

    # Worker-bob (scoped to u_bob) claims + completes his row.
    row_b = store.claim_next_for_user(secret, BOB_USER_ID)
    if row_b is None:
        log.error("bob claim returned None")
        return False
    store.complete(secret, row_b["id"], "ok, handled.")

    passed, messages = store.assert_no_cross_contamination()
    for m in messages:
        log.info(m)
    return passed


# ---------------------------------------------------------------------------
# HTTP client helpers (compose / live mode)
# ---------------------------------------------------------------------------

def _post_json(url: str, payload: Dict[str, Any], timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    """POST JSON; return parsed response or None on error."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        log.warning("POST %s failed: %s", url, exc)
        return None


def _get(url: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """GET; return parsed JSON or None on error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def _enqueue(base_url: str, user_id: str, text: str, reply_target: str) -> Optional[str]:
    """Enqueue a row via the Convex-shaped mutation endpoint. Returns the id."""
    resp = _post_json(f"{base_url}/api/mutation", {
        "path": "messages:enqueue",
        "args": {
            "userId": user_id,
            "text": text,
            "replyTarget": reply_target,
            "channel": "imessage",
        },
        "format": "json",
    })
    if not resp or resp.get("status") != "success":
        log.error("enqueue %s failed: %s", user_id, resp)
        return None
    value = resp.get("value") or {}
    return value.get("id")


def run_seed_via_http(base_url: str, poll_timeout: float = 60.0,
                      poll_interval: float = 1.0) -> bool:
    """Drive the seed scenario via HTTP against mock_outbound.

    Returns True only if BOTH rows were processed and routed correctly.
    """
    id_a = _enqueue(base_url, ALICE_USER_ID, ALICE_TEXT, ALICE_REPLY_TARGET)
    id_b = _enqueue(base_url, BOB_USER_ID, BOB_TEXT, BOB_REPLY_TARGET)
    if not id_a or not id_b:
        log.error("enqueue failed (alice=%s bob=%s); aborting", id_a, id_b)
        return False
    log.info("enqueued alice=%s bob=%s; polling for completion", id_a, id_b)

    # Poll /status until both rows are done (workers do the real claim+complete).
    deadline = time.monotonic() + poll_timeout
    both_done = False
    while time.monotonic() < deadline:
        snap = _get(f"{base_url}/status")
        if snap and snap.get("done"):
            log.info("both rows done: %s", snap.get("rows"))
            both_done = True
            break
        time.sleep(poll_interval)
    if not both_done:
        log.error("poll timeout: rows not done in %.0fs", poll_timeout)
        # Still trigger the assertion so the failure is explicit (it will FAIL on
        # missing replies rather than vacuously passing).

    # Trigger the shutdown assertion.
    result = _post_json(f"{base_url}/shutdown", {})
    if result is None:
        log.error("shutdown request failed")
        return False
    passed = bool(result.get("passed"))
    for msg in result.get("messages", []):
        log.info("assertion-line: %s", msg)
    log.info("seed result: %s", "PASS" if passed else "FAIL")
    return passed


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = os.environ.get("MOCK_HOST", "mock_outbound")
    port = int(os.environ.get("MOCK_PORT", "8800"))
    base_url = f"http://{host}:{port}"
    timeout = float(os.environ.get("SEED_TIMEOUT", "60"))

    # Wait for mock_outbound to be healthy before seeding.
    log.info("waiting for mock_outbound at %s ...", base_url)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        health = _get(f"{base_url}/health")
        if health and health.get("ok"):
            log.info("mock_outbound healthy")
            break
        time.sleep(1.0)
    else:
        log.error("mock_outbound did not become healthy in time")
        sys.exit(1)

    passed = run_seed_via_http(base_url, poll_timeout=timeout)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
