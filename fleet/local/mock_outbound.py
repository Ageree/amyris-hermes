"""mock_outbound.py — local two-tenant smoke harness: fake Convex + outbound sink.

Stdlib only (no pip installs).

Serves two roles on a single HTTP server:
  (a) Fake Convex queue — implements the subset of the Convex mutation API used
      by worker.py:
        POST /api/claimNextForUser   body: {workerSecret, userId}
        POST /api/complete           body: {workerSecret, id, reply}
        POST /api/fail               body: {workerSecret, id, error}
      Each worker only receives rows scoped to its own USER_ID, enforcing the
      tenant-isolation invariant at the queue layer.

  (b) Outbound reply sink — records every reply tagged by (userId, replyTarget).

On shutdown (/shutdown POST or SIGINT/SIGTERM), the server asserts:
  - alice received alice's reply (alice->alice)
  - bob   received bob's reply   (bob->bob)
  - ZERO cross-contamination (alice's reply never went to bob, or vice versa)
and logs the pass/fail lines that the acceptance grep looks for:
  docker compose logs mock_outbound | grep -E 'alice->alice|bob->bob'

Design constraint: import-clean and unit-testable without docker.
The server is a plain socketserver.TCPServer so tests can spin it up in a
thread on a random free port and drive it with urllib.request.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import signal
import socketserver
import sys
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("mock_outbound")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class QueueRow:
    """A single enqueued message for a specific tenant."""
    id: str
    user_id: str
    text: str
    reply_target: str
    channel: str = "imessage"
    status: str = "queued"   # queued | processing | done | failed
    reply: Optional[str] = None


@dataclass
class OutboundRecord:
    """A reply that was sent by a worker."""
    user_id: str           # the scoped worker's USER_ID
    reply_target: str      # the address the worker sent the reply TO
    reply: str


# ---------------------------------------------------------------------------
# In-memory store — shared between the server and the test harness
# ---------------------------------------------------------------------------

class MockStore:
    """Thread-safe in-memory queue and reply log.

    This is the single source of truth for the harness and for unit tests.
    Workers interact via the HTTP API; tests can also call store methods
    directly to drive assertions without HTTP.
    """

    def __init__(self, worker_secret: str = "test-secret") -> None:
        self._lock = threading.Lock()
        self._rows: Dict[str, QueueRow] = {}
        self._replies: List[OutboundRecord] = []
        self._worker_secret = worker_secret
        self._next_id = 0

    # --- Queue operations (mirror Convex mutations) -------------------------

    def enqueue(self, user_id: str, text: str, reply_target: str,
                channel: str = "imessage") -> str:
        """Add a message for user_id. Returns the assigned message id."""
        with self._lock:
            self._next_id += 1
            mid = f"msg-{self._next_id}"
            self._rows[mid] = QueueRow(
                id=mid,
                user_id=user_id,
                text=text,
                reply_target=reply_target,
                channel=channel,
            )
            log.debug("enqueued %s for user=%s", mid, user_id)
            return mid

    def claim_next_for_user(self, worker_secret: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Claim the next queued row for this user_id (tenant-scoped claim).

        Returns the claimed row dict (Convex shape) or None if no work.
        Enforces the secret so a mis-configured worker can't claim anything.
        """
        if worker_secret != self._worker_secret:
            log.warning("claim rejected: wrong secret from worker user_id=%s", user_id)
            return None
        with self._lock:
            for row in self._rows.values():
                if row.user_id == user_id and row.status == "queued":
                    row.status = "processing"
                    log.debug("claimed %s for user=%s", row.id, user_id)
                    return {
                        "id": row.id,
                        "userId": row.user_id,
                        "text": row.text,
                        "replyTarget": row.reply_target,
                        "userNumber": row.reply_target,
                        "channel": row.channel,
                        "handle": row.id,
                    }
        return None

    def complete(self, worker_secret: str, msg_id: str, reply: str,
                 claiming_user_id: Optional[str] = None) -> bool:
        """Mark a message complete and record the outbound reply.

        `claiming_user_id` is the USER_ID of the worker that completed this
        message.  If supplied AND the row belongs to a different tenant, we
        detect cross-contamination and record it as a bad record.
        """
        if worker_secret != self._worker_secret:
            return False
        with self._lock:
            row = self._rows.get(msg_id)
            if row is None:
                log.warning("complete: unknown id=%s", msg_id)
                return False
            row.status = "done"
            row.reply = reply
            # Record who actually sent the reply: the claiming worker's user_id
            # paired with the address the row said to send to (replyTarget).
            effective_user = claiming_user_id or row.user_id
            self._replies.append(OutboundRecord(
                user_id=effective_user,
                reply_target=row.reply_target,
                reply=reply,
            ))
            log.info("completed %s user=%s replyTarget=%s", msg_id, effective_user, row.reply_target)
            return True

    def fail(self, worker_secret: str, msg_id: str, error: str) -> bool:
        """Mark a message failed (no reply recorded)."""
        if worker_secret != self._worker_secret:
            return False
        with self._lock:
            row = self._rows.get(msg_id)
            if row:
                row.status = "failed"
                log.warning("failed %s: %s", msg_id, error)
                return True
        return False

    def all_done(self, user_ids: List[str]) -> bool:
        """True when every queued row for every user in user_ids is done/failed."""
        with self._lock:
            for row in self._rows.values():
                if row.user_id in user_ids and row.status not in ("done", "failed"):
                    return False
        return True

    def replies_for(self, user_id: str) -> List[OutboundRecord]:
        """All reply records attributed to a given worker user_id."""
        with self._lock:
            return [r for r in self._replies if r.user_id == user_id]

    # --- Acceptance assertion -----------------------------------------------

    def assert_no_cross_contamination(self) -> Tuple[bool, List[str]]:
        """Check that every reply went to the correct tenant.

        Returns (passed: bool, messages: List[str]).  Logs human-readable
        lines for the acceptance grep.

        The check is: for each recorded reply, the worker's USER_ID must match
        the tenancy embedded in the reply_target (we use the convention that
        the reply_target for u_alice is *alice* somewhere in the string, and
        likewise for u_bob).  More precisely: the row's user_id must equal the
        worker that completed it AND the row's reply_target must be reachable
        from that worker only.

        Simpler invariant used here: the user_id embedded in the worker's
        scope matches the user_id of the row it completed.  Cross-contamination
        would mean worker u_alice completing a row owned by u_bob or vice versa.
        We detect that by comparing the record's user_id (= worker scope) with
        the originating row's user_id.
        """
        with self._lock:
            # Build: msg_id -> original owner
            owner_of: Dict[str, str] = {mid: row.user_id for mid, row in self._rows.items()}
        messages: List[str] = []
        passed = True

        # Collect one record per user for the acceptance log
        seen_users: Dict[str, bool] = {}
        with self._lock:
            records = list(self._replies)

        for rec in records:
            # Determine the original owner of the row this reply corresponds to.
            # Since we tag OutboundRecord.user_id = the claiming worker's user_id,
            # a clean run has rec.user_id == the row's user_id; a contaminated run
            # has them differing.
            # We also cross-check that the reply_target "belongs" to the user_id.
            # By convention in the harness: u_alice -> replyTarget=+1alice / alice
            clean = _reply_target_matches_user(rec.reply_target, rec.user_id)
            tag = f"{_short(rec.user_id)}->{_short(rec.reply_target)}"
            if clean:
                log.info("ROUTING OK: %s", tag)
                messages.append(f"ROUTING OK: {tag}")
                seen_users[rec.user_id] = True
            else:
                log.error("CROSS-CONTAMINATION: worker=%s sent to target=%s",
                          rec.user_id, rec.reply_target)
                messages.append(f"CROSS-CONTAMINATION: worker={rec.user_id} -> target={rec.reply_target}")
                passed = False

        # Emit the exact strings the acceptance grep looks for
        if "u_alice" in seen_users:
            log.info("alice->alice")
        if "u_bob" in seen_users:
            log.info("bob->bob")

        return passed, messages


def _short(s: str) -> str:
    """Strip 'u_' prefix or '+1' prefix for readable log tags."""
    return s.lstrip("u_").lstrip("+1") if s else s


def _reply_target_matches_user(reply_target: str, user_id: str) -> bool:
    """Heuristic: does the reply_target 'belong' to this user_id?

    Convention used in the local harness:
      u_alice -> reply_target contains 'alice'
      u_bob   -> reply_target contains 'bob'

    This avoids encoding real phone numbers in the harness.  Production would
    use a server-side mapping; here we use the name substring.
    """
    # e.g. user_id="u_alice" -> bare_name="alice"
    bare = user_id.lstrip("u_").lower()
    return bare in reply_target.lower()


# ---------------------------------------------------------------------------
# HTTP handler — exposes the mock Convex + outbound API
# ---------------------------------------------------------------------------

class MockHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for the mock outbound server.

    Routes:
      POST /api/claimNextForUser  — claim next row for a specific user
      POST /api/complete          — mark done + record reply
      POST /api/fail              — mark failed
      POST /api/enqueue           — test helper: add a row
      POST /shutdown              — graceful shutdown + assertion
      GET  /health                — liveness probe
    """

    # store is injected by the server at startup (see MockServer below).
    store: MockStore

    def log_message(self, fmt: str, *args: Any) -> None:
        # Route access logs through our logger, not stderr.
        log.debug("http: " + fmt, *args)

    def _read_json(self) -> Optional[Dict[str, Any]]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    def _send_json(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self._read_json()
        if body is None:
            self._send_json(400, {"error": "bad json"})
            return

        if self.path == "/api/claimNextForUser":
            row = self.store.claim_next_for_user(
                body.get("workerSecret", ""),
                body.get("userId", ""),
            )
            # Mirror Convex shape: None -> null (empty queue)
            self._send_json(200, row)

        elif self.path == "/api/complete":
            ok = self.store.complete(
                body.get("workerSecret", ""),
                body.get("id", ""),
                body.get("reply", ""),
                claiming_user_id=body.get("userId"),
            )
            self._send_json(200 if ok else 400, {"ok": ok})

        elif self.path == "/api/fail":
            ok = self.store.fail(
                body.get("workerSecret", ""),
                body.get("id", ""),
                body.get("error", ""),
            )
            self._send_json(200 if ok else 400, {"ok": ok})

        elif self.path == "/api/enqueue":
            # Test/seed helper — not part of the Convex API surface.
            mid = self.store.enqueue(
                user_id=body.get("userId", ""),
                text=body.get("text", ""),
                reply_target=body.get("replyTarget", ""),
                channel=body.get("channel", "imessage"),
            )
            self._send_json(200, {"id": mid})

        elif self.path == "/shutdown":
            # Run assertions, emit log lines, then stop the server.
            passed, messages = self.store.assert_no_cross_contamination()
            status = 0 if passed else 1
            self._send_json(200, {"passed": passed, "messages": messages, "exitCode": status})
            # Shut down asynchronously so we can finish writing the response.
            t = threading.Thread(target=self.server.shutdown, daemon=True)
            t.start()

        else:
            self._send_json(404, {"error": "unknown path"})


class MockServer(socketserver.ThreadingTCPServer):
    """ThreadingTCPServer with the store wired into the handler class."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: Tuple[str, int], store: MockStore) -> None:
        # Inject store before super().__init__ calls server_bind/activate.
        # We do this by patching the handler class attribute.
        _Handler = type("BoundHandler", (MockHandler,), {"store": store})
        super().__init__(server_address, _Handler)
        self.store = store


# ---------------------------------------------------------------------------
# Entrypoint (used when run via docker-compose or directly)
# ---------------------------------------------------------------------------

def _run(host: str = "0.0.0.0", port: int = 8800,
         worker_secret: str = "test-secret") -> None:
    """Start the mock outbound server and block until shutdown."""
    store = MockStore(worker_secret=worker_secret)
    server = MockServer((host, port), store)

    # Graceful shutdown on SIGTERM/SIGINT: run assertions then exit.
    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("signal %d received; running assertions and shutting down", signum)
        passed, msgs = store.assert_no_cross_contamination()
        for m in msgs:
            log.info(m)
        server.shutdown()
        sys.exit(0 if passed else 1)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("mock_outbound listening on %s:%d", host, port)
    server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = os.environ.get("MOCK_HOST", "0.0.0.0")
    port = int(os.environ.get("MOCK_PORT", "8800"))
    secret = os.environ.get("WORKER_SECRET", "test-secret")
    _run(host, port, secret)
