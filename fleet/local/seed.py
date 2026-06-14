"""seed.py — enqueue test messages for alice + bob; wait for both replies.

Stdlib only.

This service:
  1. Enqueues one message for u_alice and one for u_bob via mock_outbound's
     /api/enqueue endpoint.
  2. Polls until both are done (all_done check via /api/status, or a fixed
     timeout).
  3. Triggers the /shutdown assertion on mock_outbound.
  4. Exits 0 if both replies were correctly routed, else non-zero.

Used by docker-compose with --exit-code-from seed.

Also import-clean and callable from unit tests (seed.run_seed(store=...))
without touching the network.
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

# ---------------------------------------------------------------------------
# Seeding logic — decoupled from HTTP so unit tests can inject a MockStore
# ---------------------------------------------------------------------------

ALICE_USER_ID = "u_alice"
ALICE_REPLY_TARGET = "+1alice555"
ALICE_TEXT = "Hello from alice — please reply"

BOB_USER_ID = "u_bob"
BOB_REPLY_TARGET = "+1bob999"
BOB_TEXT = "Hello from bob — please reply"

WORKER_SECRET = os.environ.get("WORKER_SECRET", "test-secret")


def run_seed_in_process(store: Any, timeout: float = 30.0,
                        worker_secret: Optional[str] = None) -> bool:
    """Drive the seed scenario directly against a MockStore (no HTTP).

    Used by unit tests: injects messages, polls the store's all_done(),
    runs the cross-contamination assertion.

    `worker_secret` defaults to the store's own secret (read via store._worker_secret)
    so callers don't have to pass it explicitly — the store and the seed always agree.

    Returns True if the scenario passed cleanly within `timeout` seconds.
    """
    # Use the store's own secret if not overridden so tests that create a
    # store with a custom secret don't have to repeat it here.
    secret = worker_secret if worker_secret is not None else store._worker_secret

    # Simulate what the workers would do: claim + complete each message.
    # In the compose harness the workers do this themselves; here we drive it
    # deterministically to test the store's routing logic.
    store.enqueue(ALICE_USER_ID, ALICE_TEXT, ALICE_REPLY_TARGET)
    store.enqueue(BOB_USER_ID, BOB_TEXT, BOB_REPLY_TARGET)

    # Worker-alice claims and completes her message.
    row_a = store.claim_next_for_user(secret, ALICE_USER_ID)
    if row_a is None:
        log.error("alice claim returned None")
        return False
    store.complete(secret, row_a["id"], "Hi alice!", claiming_user_id=ALICE_USER_ID)

    # Worker-bob claims and completes his message.
    row_b = store.claim_next_for_user(secret, BOB_USER_ID)
    if row_b is None:
        log.error("bob claim returned None")
        return False
    store.complete(secret, row_b["id"], "Hi bob!", claiming_user_id=BOB_USER_ID)

    passed, messages = store.assert_no_cross_contamination()
    for m in messages:
        log.info(m)
    return passed


# ---------------------------------------------------------------------------
# HTTP client helpers (compose / live mode)
# ---------------------------------------------------------------------------

def _post_json(url: str, payload: Dict[str, Any], timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    """POST JSON to url; return parsed response or None on error."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        log.warning("POST %s failed: %s", url, exc)
        return None


def _get(url: str, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """GET url; return parsed JSON or None on error."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def run_seed_via_http(base_url: str, poll_timeout: float = 60.0,
                      poll_interval: float = 1.0) -> bool:
    """Drive the seed scenario via HTTP against the mock_outbound server.

    Returns True if both replies were correctly routed within poll_timeout.
    """
    log.info("enqueuing alice message -> %s", base_url)
    resp_a = _post_json(f"{base_url}/api/enqueue", {
        "userId": ALICE_USER_ID,
        "text": ALICE_TEXT,
        "replyTarget": ALICE_REPLY_TARGET,
        "channel": "imessage",
    })
    if not resp_a or "id" not in resp_a:
        log.error("failed to enqueue alice message: %s", resp_a)
        return False
    log.info("alice message id=%s", resp_a["id"])

    log.info("enqueuing bob message -> %s", base_url)
    resp_b = _post_json(f"{base_url}/api/enqueue", {
        "userId": BOB_USER_ID,
        "text": BOB_TEXT,
        "replyTarget": BOB_REPLY_TARGET,
        "channel": "imessage",
    })
    if not resp_b or "id" not in resp_b:
        log.error("failed to enqueue bob message: %s", resp_b)
        return False
    log.info("bob message id=%s", resp_b["id"])

    # Poll until workers have processed both messages (or timeout).
    deadline = time.monotonic() + poll_timeout
    while time.monotonic() < deadline:
        status = _get(f"{base_url}/health")
        if status and status.get("ok"):
            # Ask the store if all messages are done via a lightweight check.
            done_resp = _post_json(f"{base_url}/api/all_done", {
                "userIds": [ALICE_USER_ID, BOB_USER_ID],
            })
            if done_resp and done_resp.get("done"):
                log.info("all messages done; triggering shutdown assertion")
                break
        time.sleep(poll_interval)
    else:
        log.warning("poll timeout reached; triggering shutdown assertion anyway")

    # Trigger the shutdown assertion.
    result = _post_json(f"{base_url}/shutdown", {})
    if result is None:
        log.error("shutdown request failed")
        return False

    passed = result.get("passed", False)
    for msg in result.get("messages", []):
        log.info(msg)
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

    # Wait for mock_outbound to become healthy before seeding.
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
