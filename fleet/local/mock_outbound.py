"""mock_outbound.py — local two-tenant smoke harness: fake Convex + fake model + sink.

Stdlib only (no pip installs).

This server stands in for THREE real services so the harness is fully offline and
self-contained, exercising the REAL worker (lab/skeleton/worker.py) unmodified:

  (1) Fake Convex HTTP API — the worker's ConvexClient (lab/skeleton/convex_client.py)
      POSTs to:
        POST {base}/api/mutation   body {"path","args","format":"json"}
        POST {base}/api/query      body {"path","args","format":"json"}
      and expects HTTP 200 with a success envelope:
        {"status":"success","value": <result>}   (errors: {"status":"error","errorMessage":...})
      We dispatch by the `path` field to the Convex functions the worker calls:
        messages:claimNextForUser  -> the next queued row for THAT userId (or null),
                                      marked "processing" (claimed once).
                                      ISOLATION UNDER TEST: only ever hand u_alice's
                                      row to a caller passing userId="u_alice".
        messages:complete          -> record the reply against the row; LOG the
                                      routing line `<rowUser>-><addrUser>`
                                      (e.g. alice->alice; a cross-route logs alice->bob
                                      and FAILS the assertion).
        messages:fail              -> record a failure (shouldn't happen on a healthy run).
        fleet:heartbeat            -> {"desired":"running"}
        messages:recentForUser     -> []  (no history in the mock)
        messages:enqueue           -> seed helper: add a row, return its id
        any other path             -> null (success envelope) so nothing 404s.

  (2) Fake MiniMax/OpenAI chat API — the worker's fast lane (lab/skeleton/fast_lane.py)
      POSTs to {base_url}/chat/completions (base_url ends in /v1, so the full path is
      /v1/chat/completions) with `Authorization: Bearer <key>`. We return a plain,
      URL-free, refusal-free, marker-free helpful reply so fast_reply RETURNS the text
      (does NOT defer) and the worker proceeds to messages:complete. This is how the
      offline worker generates a deterministic reply without Hermes.

  (3) Outbound reply sink — every messages:complete records an OutboundRecord tagged by
      (row owner userId, reply target). The acceptance grep reads the routing log lines.

Design constraint: import-clean and unit-testable WITHOUT docker. The server is a plain
ThreadingTCPServer so tests spin it up on a random free port and drive it with urllib.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socketserver
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("mock_outbound")

# A canned, deterministic fast-lane reply.  MUST be:
#   - plain helpful text (so fast_reply returns it, not None)
#   - NO url (or the worker's _URL_RE prefilter skips the fast lane)
#   - NO refusal phrasing (_REFUSAL would force a defer)
#   - NO [[DEFER]]/[[THINK]] markers (the router sentinels force a defer)
FAST_LANE_REPLY = "ok, handled."


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
    """A reply that was recorded against a row.

    `row_user_id` is the tenant who OWNS the row (the originating user).
    `reply_target` is the address the row says to reply to.
    A clean run has reply_target belonging to row_user_id (alice's row -> alice's
    address).  A cross-routed bug has them mismatched.
    """
    row_user_id: str
    reply_target: str
    reply: str


# ---------------------------------------------------------------------------
# In-memory store — the single source of truth for the harness and unit tests
# ---------------------------------------------------------------------------

class MockStore:
    """Thread-safe in-memory queue + reply log + routing validator.

    Workers interact via the Convex-shaped HTTP API; tests can also call store
    methods directly to drive assertions without HTTP.
    """

    def __init__(self, worker_secret: str = "test-secret") -> None:
        self._lock = threading.Lock()
        self._rows: Dict[str, QueueRow] = {}
        self._replies: List[OutboundRecord] = []
        self._worker_secret = worker_secret
        self._next_id = 0

    # --- Queue operations (mirror the Convex functions) ---------------------

    def enqueue(self, user_id: str, text: str, reply_target: str,
                channel: str = "imessage") -> str:
        """Add a message for user_id. Returns the assigned message id."""
        with self._lock:
            self._next_id += 1
            mid = f"msg-{self._next_id}"
            self._rows[mid] = QueueRow(
                id=mid, user_id=user_id, text=text,
                reply_target=reply_target, channel=channel,
            )
            log.info("enqueued %s for user=%s", mid, user_id)
            return mid

    def claim_next_for_user(self, worker_secret: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Claim the next queued row for THIS user_id (tenant-scoped claim).

        Returns the claimed row dict in the shape the worker expects (see
        claimReturns in control-plane/convex/messages.ts) or None if no work.
        Enforces the secret and the userId scope — this is the isolation guarantee
        under test: a caller for u_alice can NEVER receive u_bob's row.
        """
        if worker_secret != self._worker_secret:
            log.warning("claim rejected: wrong secret (user_id=%s)", user_id)
            return None
        with self._lock:
            for row in self._rows.values():
                if row.user_id == user_id and row.status == "queued":
                    row.status = "processing"
                    log.info("claimed %s for user=%s", row.id, user_id)
                    return {
                        "id": row.id,
                        "handle": row.id,
                        "userId": row.user_id,
                        "channel": row.channel,
                        "replyTarget": row.reply_target,
                        "userNumber": row.reply_target,
                        "text": row.text,
                        "mediaUrl": None,
                    }
        return None

    def complete(self, worker_secret: str, msg_id: str, reply: str) -> bool:
        """Mark a row done and record the reply + the routing log line.

        The routing line is `<rowUser>-><addrUser>` derived from the ROW's owner
        and the ROW's reply target — both come from the stored row, never from
        the caller — so a worker that completed the wrong tenant's row is caught.
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
            self._replies.append(OutboundRecord(
                row_user_id=row.user_id,
                reply_target=row.reply_target,
                reply=reply,
            ))
        # Emit the routing line OUTSIDE the lock.  This is what the acceptance
        # grep reads: alice->alice / bob->bob on a clean run.
        row_tag = _short(row.user_id)
        addr_tag = _short_target(row.reply_target)
        log.info("ROUTE %s->%s (msg=%s reply=%r)", row_tag, addr_tag, msg_id, reply[:60])
        return True

    def fail(self, worker_secret: str, msg_id: str, error: str) -> bool:
        """Mark a row failed (should not happen on a healthy run)."""
        if worker_secret != self._worker_secret:
            return False
        with self._lock:
            row = self._rows.get(msg_id)
            if row:
                row.status = "failed"
                log.warning("FAILED %s: %s", msg_id, error)
                return True
        return False

    def recent_for_user(self, *_args: Any, **_kwargs: Any) -> List[Any]:
        """No conversation history in the mock."""
        return []

    def heartbeat(self, *_args: Any, **_kwargs: Any) -> Dict[str, str]:
        """Fleet controller heartbeat — always 'running' in the mock."""
        return {"desired": "running"}

    # --- Status / completion checks -----------------------------------------

    def all_done(self, user_ids: List[str]) -> bool:
        """True when every row for every user in user_ids is done/failed.

        Returns False if NOTHING is enqueued yet (so seed keeps polling until the
        rows exist and are processed, rather than treating an empty queue as done).
        """
        with self._lock:
            relevant = [r for r in self._rows.values() if r.user_id in user_ids]
            if not relevant:
                return False
            return all(r.status in ("done", "failed") for r in relevant)

    def replies_for(self, user_id: str) -> List[OutboundRecord]:
        """All reply records whose ROW belongs to a given tenant."""
        with self._lock:
            return [r for r in self._replies if r.row_user_id == user_id]

    def status_snapshot(self, user_ids: List[str]) -> Dict[str, Any]:
        """Compact status used by seed's GET /status poll."""
        with self._lock:
            rows = [
                {"id": r.id, "userId": r.user_id, "status": r.status}
                for r in self._rows.values() if r.user_id in user_ids
            ]
        return {
            "rows": rows,
            "done": self.all_done(user_ids),
            "replyCount": len(self._replies),
        }

    # --- Acceptance assertion -----------------------------------------------

    def assert_no_cross_contamination(self) -> Tuple[bool, List[str]]:
        """Validate that every recorded reply was routed to the correct tenant.

        For each OutboundRecord the ROW's owner and the ROW's reply target must
        agree (alice's row -> alice's address).  A mismatch is cross-contamination.

        Returns (passed, messages) and logs:
          - `<user>-><user>` on each correct route (acceptance grep target)
          - `CROSS-CONTAMINATION ...` on each bad route
        Also fails if EITHER tenant produced zero replies (guards against a
        vacuous pass over an empty reply set).
        """
        with self._lock:
            records = list(self._replies)

        messages: List[str] = []
        passed = True
        seen: Dict[str, int] = {"u_alice": 0, "u_bob": 0}

        for rec in records:
            clean = _reply_target_matches_user(rec.reply_target, rec.row_user_id)
            row_tag = _short(rec.row_user_id)
            addr_tag = _short_target(rec.reply_target)
            line = f"{row_tag}->{addr_tag}"
            if clean:
                log.info(line)            # e.g. "alice->alice"
                messages.append(line)
                seen[rec.row_user_id] = seen.get(rec.row_user_id, 0) + 1
            else:
                bad = f"CROSS-CONTAMINATION row={rec.row_user_id} target={rec.reply_target}"
                log.error(bad)
                messages.append(bad)
                passed = False

        # Guard against a vacuous pass: BOTH tenants must have replied.
        if seen.get("u_alice", 0) == 0:
            log.error("NO REPLY recorded for u_alice (vacuous run)")
            messages.append("MISSING REPLY: u_alice")
            passed = False
        if seen.get("u_bob", 0) == 0:
            log.error("NO REPLY recorded for u_bob (vacuous run)")
            messages.append("MISSING REPLY: u_bob")
            passed = False

        log.info("assertion %s (alice=%d bob=%d cross=%s)",
                 "PASS" if passed else "FAIL",
                 seen.get("u_alice", 0), seen.get("u_bob", 0),
                 sum(1 for m in messages if m.startswith("CROSS")))
        return passed, messages


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------

def _short(user_id: str) -> str:
    """u_alice -> alice; u_bob -> bob."""
    return user_id[2:] if user_id.startswith("u_") else user_id


def _short_target(reply_target: str) -> str:
    """Map a reply target to a tenant tag for the routing line.

    Convention: alice's address contains 'alice', bob's contains 'bob'.  Falls
    back to the raw target if neither matches (so a wrong route is still visible).
    """
    low = (reply_target or "").lower()
    if "alice" in low:
        return "alice"
    if "bob" in low:
        return "bob"
    return reply_target


def _reply_target_matches_user(reply_target: str, user_id: str) -> bool:
    """Does the reply target 'belong' to this user_id?

    Convention used in the harness (avoids real phone numbers):
      u_alice -> reply target contains 'alice'
      u_bob   -> reply target contains 'bob'
    """
    bare = _short(user_id).lower()
    return bool(bare) and bare in (reply_target or "").lower()


# ---------------------------------------------------------------------------
# Convex function dispatch — by the `path` field of /api/mutation|query
# ---------------------------------------------------------------------------

def dispatch_convex(store: MockStore, path: str, args: Dict[str, Any]) -> Any:
    """Route a Convex function call to the store. Returns the raw `value`.

    Unknown paths return None (a valid success value) so the worker never 404s
    on a function the harness doesn't model.
    """
    secret = args.get("workerSecret", "")
    if path == "messages:claimNextForUser":
        return store.claim_next_for_user(secret, args.get("userId", ""))
    if path == "messages:complete":
        ok = store.complete(secret, args.get("id", ""), args.get("reply", ""))
        # Convex complete returns null; surface a bad-secret as an error envelope.
        if not ok:
            raise _ConvexError("complete rejected (bad secret or unknown id)")
        return None
    if path == "messages:fail":
        store.fail(secret, args.get("id", ""), args.get("error", ""))
        return None
    if path == "fleet:heartbeat":
        return store.heartbeat()
    if path == "messages:recentForUser":
        return store.recent_for_user()
    if path == "messages:enqueue":
        # Seed helper (not a real Convex fn; harmless extra path).
        mid = store.enqueue(
            user_id=args.get("userId", ""),
            text=args.get("text", ""),
            reply_target=args.get("replyTarget", ""),
            channel=args.get("channel", "imessage"),
        )
        return {"id": mid}
    # Anything else (intents:listPending, quota fns, etc.) -> null success.
    log.debug("convex unknown path=%s -> null", path)
    return None


class _ConvexError(Exception):
    """Maps to a Convex {"status":"error"} envelope."""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class MockHandler(BaseHTTPRequestHandler):
    """HTTP handler exposing the fake Convex + chat + status endpoints.

    POST /api/mutation         Convex mutation (dispatch by body.path)
    POST /api/query            Convex query    (dispatch by body.path)
    POST /v1/chat/completions  fake MiniMax/OpenAI chat -> deterministic reply
    POST /api/enqueue          seed helper (convenience; also via /api/mutation)
    POST /shutdown             run the assertion, emit lines, stop the server
    GET  /health               liveness
    GET  /status               compact queue status for seed's poll
    """

    store: MockStore  # injected per-server (see MockServer)

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug("http: " + fmt, *args)

    # --- low-level helpers ---------------------------------------------------

    def _read_json(self) -> Optional[Dict[str, Any]]:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return None

    def _send_json(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    @staticmethod
    def _ok(value: Any) -> Dict[str, Any]:
        """Convex success envelope."""
        return {"status": "success", "value": value}

    @staticmethod
    def _err(message: str) -> Dict[str, Any]:
        """Convex error envelope (HTTP 200, status=error — like real Convex)."""
        return {"status": "error", "errorMessage": message}

    # --- routes --------------------------------------------------------------

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"ok": True})
        elif self.path.startswith("/status"):
            # Default to the two harness tenants.
            snap = self.store.status_snapshot(["u_alice", "u_bob"])
            self._send_json(200, snap)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self._read_json()
        if body is None:
            self._send_json(400, {"error": "bad json"})
            return

        try:
            if self.path in ("/api/mutation", "/api/query"):
                self._handle_convex(body)
            elif self.path == "/v1/chat/completions":
                self._handle_chat(body)
            elif self.path == "/api/enqueue":
                mid = self.store.enqueue(
                    user_id=body.get("userId", ""),
                    text=body.get("text", ""),
                    reply_target=body.get("replyTarget", ""),
                    channel=body.get("channel", "imessage"),
                )
                self._send_json(200, {"id": mid})
            elif self.path == "/shutdown":
                self._handle_shutdown()
            else:
                self._send_json(404, {"error": "unknown path"})
        except Exception:  # never let a handler crash take down the loop
            log.exception("handler error for %s", self.path)
            self._send_json(500, {"error": "internal"})

    def _handle_convex(self, body: Dict[str, Any]) -> None:
        """Dispatch a Convex mutation/query and wrap in the success/error envelope."""
        path = body.get("path", "")
        args = body.get("args", {}) or {}
        try:
            value = dispatch_convex(self.store, path, args)
        except _ConvexError as exc:
            # Real Convex returns errors as HTTP 200 with status=error.
            self._send_json(200, self._err(str(exc)))
            return
        self._send_json(200, self._ok(value))

    def _handle_chat(self, body: Dict[str, Any]) -> None:
        """Return a deterministic OpenAI/MiniMax-style chat completion.

        Plain, URL-free, refusal-free, marker-free text so the worker's fast lane
        returns it (does NOT defer).  If the request asked to stream we still
        return a single non-stream JSON body — the compose config disables
        streaming (STREAMING_ENABLED=0) so the worker uses the non-stream path.
        """
        # We ignore the prompt entirely; the reply is constant and safe.
        completion = {
            "id": "mock-cmpl-1",
            "object": "chat.completion",
            "model": body.get("model", "MiniMax-M3"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": FAST_LANE_REPLY},
                    "finish_reason": "stop",
                }
            ],
        }
        self._send_json(200, completion)

    def _handle_shutdown(self) -> None:
        passed, messages = self.store.assert_no_cross_contamination()
        self._send_json(200, {
            "passed": passed,
            "messages": messages,
            "exitCode": 0 if passed else 1,
        })
        threading.Thread(target=self.server.shutdown, daemon=True).start()


class MockServer(socketserver.ThreadingTCPServer):
    """ThreadingTCPServer with the store wired into the handler class."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: Tuple[str, int], store: MockStore) -> None:
        _Handler = type("BoundHandler", (MockHandler,), {"store": store})
        super().__init__(server_address, _Handler)
        self.store = store


# ---------------------------------------------------------------------------
# Entrypoint (docker-compose / direct)
# ---------------------------------------------------------------------------

def _run(host: str = "0.0.0.0", port: int = 8800,
         worker_secret: str = "test-secret") -> None:
    """Start the mock server and block until shutdown."""
    store = MockStore(worker_secret=worker_secret)
    server = MockServer((host, port), store)

    def _handle_signal(signum: int, _frame: Any) -> None:
        log.info("signal %d received; running assertion and shutting down", signum)
        passed, msgs = store.assert_no_cross_contamination()
        for m in msgs:
            log.info("shutdown-line: %s", m)
        server.shutdown()
        sys.exit(0 if passed else 1)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("mock_outbound listening on %s:%d (Convex + chat + sink)", host, port)
    server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _run(
        host=os.environ.get("MOCK_HOST", "0.0.0.0"),
        port=int(os.environ.get("MOCK_PORT", "8800")),
        worker_secret=os.environ.get("WORKER_SECRET", "test-secret"),
    )
