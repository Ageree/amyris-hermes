"""test_harness_logic.py — unit tests for mock_outbound + seed routing logic.

Network-free (no docker, no real APIs).  Proves:
  1. MockStore tenant isolation: alice's worker can only claim alice's rows.
  2. MockStore tenant isolation: bob's worker can only claim bob's rows.
  3. Zero cross-contamination detection: correct routing passes the assertion.
  4. Cross-contamination detection: a worker completing another tenant's row
     is caught and reported.
  5. Wrong secret: claims are rejected when the worker secret doesn't match.
  6. Full scenario via run_seed_in_process: end-to-end without HTTP.
  7. HTTP server integration: spin up MockServer on a free port, drive with
     urllib.request, verify the /health, /api/enqueue, /api/claimNextForUser,
     /api/complete, and /shutdown endpoints in process.

Run with:
    cd /Users/saveliy/Documents/Amyris
    python3 -m pytest fleet/local/test_harness_logic.py -q
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

# Make fleet/local importable without installing anything.
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mock_outbound import (
    MockServer,
    MockStore,
    OutboundRecord,
    _reply_target_matches_user,
)
from seed import run_seed_in_process


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SECRET = "harness-secret"


def _make_store() -> MockStore:
    return MockStore(worker_secret=SECRET)


def _post(base_url: str, path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _get(base_url: str, path: str) -> Optional[Dict[str, Any]]:
    with urllib.request.urlopen(f"{base_url}{path}", timeout=5) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# 1. Basic store operations
# ---------------------------------------------------------------------------

class TestMockStoreIsolation:

    def test_alice_worker_only_claims_alice_rows(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hello", "+1alice555")
        store.enqueue("u_bob",   "hello", "+1bob999")

        row = store.claim_next_for_user(SECRET, "u_alice")
        assert row is not None, "alice should claim her row"
        assert row["userId"] == "u_alice"
        assert row["replyTarget"] == "+1alice555"

    def test_bob_worker_only_claims_bob_rows(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hello", "+1alice555")
        store.enqueue("u_bob",   "hi bob", "+1bob999")

        row = store.claim_next_for_user(SECRET, "u_bob")
        assert row is not None, "bob should claim his row"
        assert row["userId"] == "u_bob"
        assert row["replyTarget"] == "+1bob999"

    def test_alice_cannot_claim_bob_rows(self) -> None:
        store = _make_store()
        store.enqueue("u_bob", "bob's message", "+1bob999")

        row = store.claim_next_for_user(SECRET, "u_alice")
        assert row is None, "alice should not be able to claim bob's row"

    def test_empty_queue_returns_none(self) -> None:
        store = _make_store()
        assert store.claim_next_for_user(SECRET, "u_alice") is None

    def test_claimed_row_not_claimable_again(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "msg", "+1alice555")

        first = store.claim_next_for_user(SECRET, "u_alice")
        assert first is not None
        second = store.claim_next_for_user(SECRET, "u_alice")
        assert second is None, "already-claimed row must not be returned again"


# ---------------------------------------------------------------------------
# 2. Completion and reply recording
# ---------------------------------------------------------------------------

class TestMockStoreCompletion:

    def test_complete_records_reply(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        row = store.claim_next_for_user(SECRET, "u_alice")
        assert row is not None

        ok = store.complete(SECRET, row["id"], "Hello alice!", claiming_user_id="u_alice")
        assert ok is True

        replies = store.replies_for("u_alice")
        assert len(replies) == 1
        assert replies[0].reply == "Hello alice!"
        assert replies[0].reply_target == "+1alice555"

    def test_wrong_secret_rejected(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        row = store.claim_next_for_user(SECRET, "u_alice")
        assert row is not None

        ok = store.complete("WRONG-SECRET", row["id"], "nope")
        assert ok is False
        assert len(store.replies_for("u_alice")) == 0

    def test_fail_marks_row_failed(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        row = store.claim_next_for_user(SECRET, "u_alice")
        assert row is not None

        ok = store.fail(SECRET, row["id"], "something broke")
        assert ok is True

    def test_all_done_true_when_complete(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        store.enqueue("u_bob",   "hi", "+1bob999")

        row_a = store.claim_next_for_user(SECRET, "u_alice")
        row_b = store.claim_next_for_user(SECRET, "u_bob")
        assert row_a and row_b

        assert not store.all_done(["u_alice", "u_bob"])

        store.complete(SECRET, row_a["id"], "reply a", claiming_user_id="u_alice")
        assert not store.all_done(["u_alice", "u_bob"])  # bob still pending

        store.complete(SECRET, row_b["id"], "reply b", claiming_user_id="u_bob")
        assert store.all_done(["u_alice", "u_bob"])


# ---------------------------------------------------------------------------
# 3. Cross-contamination detection
# ---------------------------------------------------------------------------

class TestCrossContaminationDetection:

    def test_clean_routing_passes_assertion(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        store.enqueue("u_bob",   "hi", "+1bob999")

        row_a = store.claim_next_for_user(SECRET, "u_alice")
        row_b = store.claim_next_for_user(SECRET, "u_bob")
        store.complete(SECRET, row_a["id"], "Hi alice!", claiming_user_id="u_alice")
        store.complete(SECRET, row_b["id"], "Hi bob!",   claiming_user_id="u_bob")

        passed, messages = store.assert_no_cross_contamination()
        assert passed, f"Expected clean routing to pass; messages={messages}"
        # Both canonical log lines must appear in the messages list
        combined = " ".join(messages)
        assert "alice" in combined
        assert "bob"   in combined

    def test_cross_contamination_is_detected(self) -> None:
        """Simulate a scoping bug: worker_alice claims and 'completes' bob's row."""
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        store.enqueue("u_bob",   "hi", "+1bob999")

        # Correct claim for alice
        row_a = store.claim_next_for_user(SECRET, "u_alice")
        store.complete(SECRET, row_a["id"], "Hi alice!", claiming_user_id="u_alice")

        # Bob's row is never claimed by bob's worker; instead we simulate alice's
        # worker somehow completing it (data integrity bug scenario).
        # We manipulate the store directly since the HTTP API enforces userId-scoped claims.
        row_b = store.claim_next_for_user(SECRET, "u_bob")
        assert row_b is not None
        # alice's worker "completes" bob's row with alice's user_id — cross-contamination.
        store.complete(SECRET, row_b["id"], "Hi (wrong worker)!", claiming_user_id="u_alice")

        passed, messages = store.assert_no_cross_contamination()
        # The assertion should detect that alice replied to bob's target.
        # alice->+1bob999 is cross-contamination (bob's target doesn't contain "alice").
        assert not passed, f"Expected contamination to be detected; messages={messages}"
        assert any("CROSS-CONTAMINATION" in m for m in messages)

    def test_reply_target_matches_user_helper(self) -> None:
        """Unit test the routing heuristic used by assert_no_cross_contamination."""
        assert _reply_target_matches_user("+1alice555", "u_alice") is True
        assert _reply_target_matches_user("+1bob999",   "u_bob")   is True
        assert _reply_target_matches_user("+1alice555", "u_bob")   is False
        assert _reply_target_matches_user("+1bob999",   "u_alice") is False
        # Edge cases
        assert _reply_target_matches_user("alice-phone", "u_alice") is True
        assert _reply_target_matches_user("",            "u_alice") is False


# ---------------------------------------------------------------------------
# 4. Full scenario via run_seed_in_process (no HTTP, no docker)
# ---------------------------------------------------------------------------

class TestSeedScenarioInProcess:

    def test_full_clean_scenario(self) -> None:
        """End-to-end: enqueue alice+bob, both workers claim+complete, assert clean."""
        store = _make_store()
        passed = run_seed_in_process(store, timeout=5.0)
        assert passed, "Expected the clean two-tenant scenario to pass"

    def test_replies_are_recorded_per_tenant(self) -> None:
        store = _make_store()
        run_seed_in_process(store, timeout=5.0)

        alice_replies = store.replies_for("u_alice")
        bob_replies   = store.replies_for("u_bob")

        assert len(alice_replies) == 1, f"Expected 1 alice reply; got {alice_replies}"
        assert len(bob_replies)   == 1, f"Expected 1 bob reply;   got {bob_replies}"
        # Each reply went to the correct target
        assert alice_replies[0].reply_target == "+1alice555"
        assert bob_replies[0].reply_target   == "+1bob999"


# ---------------------------------------------------------------------------
# 5. HTTP server integration tests (in-process, no docker)
# ---------------------------------------------------------------------------

class TestHttpServer:
    """Spin up MockServer on a random free port; drive with urllib.request."""

    @pytest.fixture(autouse=True)
    def _server(self) -> None:
        """Start the server in a background thread; stop after the test."""
        self.store = MockStore(worker_secret=SECRET)
        # Port 0 = OS assigns a free port.
        self.server = MockServer(("127.0.0.1", 0), self.store)
        host, port = self.server.server_address
        self.base_url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        # Give the server a moment to start accepting.
        time.sleep(0.05)
        yield
        self.server.shutdown()

    def test_health_endpoint(self) -> None:
        resp = _get(self.base_url, "/health")
        assert resp == {"ok": True}

    def test_enqueue_and_claim(self) -> None:
        enq = _post(self.base_url, "/api/enqueue", {
            "userId": "u_alice",
            "text": "hello http",
            "replyTarget": "+1alice555",
        })
        assert "id" in enq

        claim = _post(self.base_url, "/api/claimNextForUser", {
            "workerSecret": SECRET,
            "userId": "u_alice",
        })
        assert claim is not None
        assert claim["userId"] == "u_alice"
        assert claim["replyTarget"] == "+1alice555"

    def test_bob_cannot_claim_alice_row_via_http(self) -> None:
        _post(self.base_url, "/api/enqueue", {
            "userId": "u_alice",
            "text": "alice msg",
            "replyTarget": "+1alice555",
        })
        claim = _post(self.base_url, "/api/claimNextForUser", {
            "workerSecret": SECRET,
            "userId": "u_bob",
        })
        # bob should get null (no rows for bob)
        assert claim is None

    def test_complete_via_http(self) -> None:
        _post(self.base_url, "/api/enqueue", {
            "userId": "u_alice", "text": "hi", "replyTarget": "+1alice555",
        })
        row = _post(self.base_url, "/api/claimNextForUser", {
            "workerSecret": SECRET, "userId": "u_alice",
        })
        assert row is not None

        result = _post(self.base_url, "/api/complete", {
            "workerSecret": SECRET,
            "id": row["id"],
            "reply": "Hello via HTTP!",
            "userId": "u_alice",
        })
        assert result["ok"] is True

    def test_shutdown_assertion_passes_on_clean_run(self) -> None:
        # Enqueue one message per tenant and complete them correctly.
        for uid, target in [("u_alice", "+1alice555"), ("u_bob", "+1bob999")]:
            _post(self.base_url, "/api/enqueue", {
                "userId": uid, "text": "hi", "replyTarget": target,
            })
            row = _post(self.base_url, "/api/claimNextForUser", {
                "workerSecret": SECRET, "userId": uid,
            })
            assert row is not None, f"claim failed for {uid}"
            _post(self.base_url, "/api/complete", {
                "workerSecret": SECRET, "id": row["id"],
                "reply": f"Hi {uid}!", "userId": uid,
            })

        result = _post(self.base_url, "/shutdown", {})
        assert result["passed"] is True, f"Expected shutdown assertion to pass; got {result}"

    def test_unknown_path_returns_404(self) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _get(self.base_url, "/no-such-path")
        assert exc_info.value.code == 404

    def test_wrong_secret_via_http(self) -> None:
        _post(self.base_url, "/api/enqueue", {
            "userId": "u_alice", "text": "hi", "replyTarget": "+1alice555",
        })
        row = _post(self.base_url, "/api/claimNextForUser", {
            "workerSecret": SECRET, "userId": "u_alice",
        })
        # The server returns HTTP 400 when the secret is wrong because ok=False
        # maps to status 400 in _send_json.  urllib raises HTTPError on non-2xx.
        try:
            result = _post(self.base_url, "/api/complete", {
                "workerSecret": "WRONG",
                "id": row["id"],
                "reply": "should not record",
            })
            # If somehow we get a 2xx, ok must be False
            assert result is not None and result.get("ok") is False
        except urllib.error.HTTPError as exc:
            assert exc.code == 400, f"Expected 400 for wrong secret, got {exc.code}"
        # Either way, no reply should have been recorded.
        assert len(self.store.replies_for("u_alice")) == 0
