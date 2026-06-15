"""test_harness_logic.py — unit tests for mock_outbound + seed routing logic.

Network-free (no docker, no real APIs).  Proves the harness logic is correct so
the docker-compose-up leg is just an integration wrapper, not the only proof.

Covers:
  1. MockStore tenant isolation: alice's worker can only claim alice's rows.
  2. Cross-contamination detection PASSES on a clean run.
  3. NEGATIVE: a cross-routed complete is REJECTED by the validator (so the pass
     is never vacuous).
  4. Vacuous-pass guard: zero replies for a tenant FAILS the assertion.
  5. Convex protocol: /api/mutation + /api/query dispatch by `path`, success
     envelope, error envelope on bad secret, unknown path -> null success.
  6. Fake model: /v1/chat/completions returns an OpenAI-shaped body that the
     REAL fast_lane.fast_reply accepts (returns the text, does not defer).
  7. Full scenario via run_seed_in_process and via the live HTTP server.

Run with:
    cd /Users/saveliy/Documents/Amyris
    python3 -m pytest fleet/local/test_harness_logic.py -q
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

# Make fleet/local importable.
_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Make the real worker fast_lane importable for the model-shape test.
_SKELETON = _HERE.parent.parent / "lab" / "skeleton"
if str(_SKELETON) not in sys.path:
    sys.path.insert(0, str(_SKELETON))

from mock_outbound import (  # noqa: E402
    FAST_LANE_REPLY,
    MockServer,
    MockStore,
    _reply_target_matches_user,
    dispatch_convex,
)
from seed import run_seed_in_process  # noqa: E402


SECRET = "harness-secret"


def _make_store() -> MockStore:
    return MockStore(worker_secret=SECRET)


def _convex(base_url: str, kind: str, path: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call a Convex-shaped endpoint the way ConvexClient does."""
    data = json.dumps({"path": path, "args": args, "format": "json"}).encode()
    req = urllib.request.Request(
        f"{base_url}/api/{kind}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _get(base_url: str, path: str) -> Optional[Dict[str, Any]]:
    with urllib.request.urlopen(f"{base_url}{path}", timeout=5) as resp:
        return json.loads(resp.read())


def _post(base_url: str, path: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# 1. Store-level tenant isolation
# ---------------------------------------------------------------------------

class TestMockStoreIsolation:

    def test_alice_worker_only_claims_alice_rows(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hi from alice", "+1alice555")
        store.enqueue("u_bob",   "hi from bob",   "+1bob999")

        row = store.claim_next_for_user(SECRET, "u_alice")
        assert row is not None
        assert row["userId"] == "u_alice"
        assert row["replyTarget"] == "+1alice555"

    def test_alice_cannot_claim_bob_rows(self) -> None:
        store = _make_store()
        store.enqueue("u_bob", "bob's message", "+1bob999")
        assert store.claim_next_for_user(SECRET, "u_alice") is None

    def test_claimed_row_not_claimable_again(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "msg", "+1alice555")
        assert store.claim_next_for_user(SECRET, "u_alice") is not None
        assert store.claim_next_for_user(SECRET, "u_alice") is None

    def test_wrong_secret_rejects_claim(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "msg", "+1alice555")
        assert store.claim_next_for_user("WRONG", "u_alice") is None


# ---------------------------------------------------------------------------
# 2 + 3 + 4. Routing validation (clean / cross-routed / vacuous)
# ---------------------------------------------------------------------------

class TestRoutingValidation:

    def test_clean_routing_passes(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        store.enqueue("u_bob",   "hi", "+1bob999")
        a = store.claim_next_for_user(SECRET, "u_alice")
        b = store.claim_next_for_user(SECRET, "u_bob")
        store.complete(SECRET, a["id"], "ok, handled.")
        store.complete(SECRET, b["id"], "ok, handled.")

        passed, messages = store.assert_no_cross_contamination()
        assert passed, f"clean routing should pass; messages={messages}"
        assert "alice->alice" in messages
        assert "bob->bob" in messages

    def test_cross_routed_reply_is_rejected(self) -> None:
        """NEGATIVE proof: a row whose reply_target belongs to the OTHER tenant
        is flagged as cross-contamination and FAILS the assertion.

        We construct a row owned by u_alice but with bob's reply target (the exact
        shape a scoping/routing bug would produce), complete it, and assert the
        validator rejects it.  This guarantees the positive test isn't vacuous.
        """
        store = _make_store()
        # alice's row, but mis-addressed to BOB (the bug under test).
        store.enqueue("u_alice", "hi", "+1bob999")    # WRONG target for alice
        store.enqueue("u_bob",   "hi", "+1bob999")    # bob is fine
        a = store.claim_next_for_user(SECRET, "u_alice")
        b = store.claim_next_for_user(SECRET, "u_bob")
        store.complete(SECRET, a["id"], "leaked to bob!")
        store.complete(SECRET, b["id"], "ok, handled.")

        passed, messages = store.assert_no_cross_contamination()
        assert not passed, f"cross-routed reply MUST fail; messages={messages}"
        assert any("CROSS-CONTAMINATION" in m for m in messages)

    def test_vacuous_run_fails(self) -> None:
        """Zero replies -> assertion FAILS (not a vacuous pass)."""
        store = _make_store()
        passed, messages = store.assert_no_cross_contamination()
        assert not passed
        assert any("MISSING REPLY" in m for m in messages)

    def test_only_one_tenant_replies_fails(self) -> None:
        """Only alice replied -> FAIL (bob missing)."""
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        a = store.claim_next_for_user(SECRET, "u_alice")
        store.complete(SECRET, a["id"], "ok, handled.")
        passed, messages = store.assert_no_cross_contamination()
        assert not passed
        assert any("MISSING REPLY: u_bob" in m for m in messages)

    def test_reply_target_matches_user_helper(self) -> None:
        assert _reply_target_matches_user("+1alice555", "u_alice") is True
        assert _reply_target_matches_user("+1bob999",   "u_bob")   is True
        assert _reply_target_matches_user("+1alice555", "u_bob")   is False
        assert _reply_target_matches_user("+1bob999",   "u_alice") is False
        assert _reply_target_matches_user("",           "u_alice") is False


# ---------------------------------------------------------------------------
# 5. Convex protocol dispatch (function level, no HTTP)
# ---------------------------------------------------------------------------

class TestConvexDispatch:

    def test_claim_dispatch(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        row = dispatch_convex(store, "messages:claimNextForUser",
                              {"workerSecret": SECRET, "userId": "u_alice"})
        assert row is not None and row["userId"] == "u_alice"

    def test_complete_dispatch_records(self) -> None:
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        row = dispatch_convex(store, "messages:claimNextForUser",
                              {"workerSecret": SECRET, "userId": "u_alice"})
        ret = dispatch_convex(store, "messages:complete",
                              {"workerSecret": SECRET, "id": row["id"], "reply": "ok, handled."})
        assert ret is None  # Convex complete returns null
        assert len(store.replies_for("u_alice")) == 1

    def test_complete_bad_secret_raises_convex_error(self) -> None:
        from mock_outbound import _ConvexError
        store = _make_store()
        store.enqueue("u_alice", "hi", "+1alice555")
        row = dispatch_convex(store, "messages:claimNextForUser",
                              {"workerSecret": SECRET, "userId": "u_alice"})
        with pytest.raises(_ConvexError):
            dispatch_convex(store, "messages:complete",
                            {"workerSecret": "WRONG", "id": row["id"], "reply": "x"})

    def test_heartbeat_dispatch(self) -> None:
        store = _make_store()
        ret = dispatch_convex(store, "fleet:heartbeat",
                              {"workerSecret": SECRET, "userId": "u_alice"})
        assert ret == {"desired": "running"}

    def test_recent_for_user_dispatch(self) -> None:
        store = _make_store()
        ret = dispatch_convex(store, "messages:recentForUser",
                              {"workerSecret": SECRET, "userId": "u_alice"})
        assert ret == []

    def test_unknown_path_returns_none(self) -> None:
        store = _make_store()
        ret = dispatch_convex(store, "intents:listPending", {"workerSecret": SECRET})
        assert ret is None


# ---------------------------------------------------------------------------
# 6. Full in-process scenario
# ---------------------------------------------------------------------------

class TestSeedScenarioInProcess:

    def test_full_clean_scenario(self) -> None:
        store = _make_store()
        assert run_seed_in_process(store) is True

    def test_replies_recorded_per_tenant(self) -> None:
        store = _make_store()
        run_seed_in_process(store)
        assert len(store.replies_for("u_alice")) == 1
        assert len(store.replies_for("u_bob")) == 1
        assert store.replies_for("u_alice")[0].reply_target == "+1alice555"
        assert store.replies_for("u_bob")[0].reply_target == "+1bob999"


# ---------------------------------------------------------------------------
# 7. HTTP server integration (in-process, no docker)
# ---------------------------------------------------------------------------

class TestHttpServer:
    """Spin up MockServer on a random free port; drive with urllib."""

    @pytest.fixture(autouse=True)
    def _server(self) -> None:
        self.store = MockStore(worker_secret=SECRET)
        self.server = MockServer(("127.0.0.1", 0), self.store)
        _host, port = self.server.server_address
        self.base_url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.05)
        yield
        self.server.shutdown()

    def test_health(self) -> None:
        assert _get(self.base_url, "/health") == {"ok": True}

    def test_convex_enqueue_claim_complete_envelopes(self) -> None:
        # enqueue via mutation
        enq = _convex(self.base_url, "mutation", "messages:enqueue", {
            "userId": "u_alice", "text": "hi from alice", "replyTarget": "+1alice555",
        })
        assert enq["status"] == "success"
        assert "id" in enq["value"]

        # claim (scoped)
        claim = _convex(self.base_url, "mutation", "messages:claimNextForUser", {
            "workerSecret": SECRET, "userId": "u_alice",
        })
        assert claim["status"] == "success"
        row = claim["value"]
        assert row["userId"] == "u_alice"
        assert row["replyTarget"] == "+1alice555"

        # complete -> success envelope, value null
        comp = _convex(self.base_url, "mutation", "messages:complete", {
            "workerSecret": SECRET, "id": row["id"], "reply": "ok, handled.",
        })
        assert comp["status"] == "success"
        assert comp["value"] is None
        assert len(self.store.replies_for("u_alice")) == 1

    def test_bob_cannot_claim_alice_row_via_http(self) -> None:
        _convex(self.base_url, "mutation", "messages:enqueue", {
            "userId": "u_alice", "text": "hi", "replyTarget": "+1alice555",
        })
        claim = _convex(self.base_url, "mutation", "messages:claimNextForUser", {
            "workerSecret": SECRET, "userId": "u_bob",
        })
        assert claim["status"] == "success"
        assert claim["value"] is None  # bob gets nothing

    def test_complete_bad_secret_error_envelope(self) -> None:
        _convex(self.base_url, "mutation", "messages:enqueue", {
            "userId": "u_alice", "text": "hi", "replyTarget": "+1alice555",
        })
        claim = _convex(self.base_url, "mutation", "messages:claimNextForUser", {
            "workerSecret": SECRET, "userId": "u_alice",
        })
        comp = _convex(self.base_url, "mutation", "messages:complete", {
            "workerSecret": "WRONG", "id": claim["value"]["id"], "reply": "x",
        })
        # Real Convex returns errors as HTTP 200 with status=error.
        assert comp["status"] == "error"
        assert "errorMessage" in comp
        assert len(self.store.replies_for("u_alice")) == 0

    def test_unknown_convex_path_null_success(self) -> None:
        resp = _convex(self.base_url, "query", "intents:listPending", {
            "workerSecret": SECRET,
        })
        assert resp["status"] == "success"
        assert resp["value"] is None

    def test_chat_completion_shape_is_fast_lane_compatible(self) -> None:
        """The fake model body must be accepted by the REAL fast_lane.fast_reply.

        This proves Bug 2's fix: a worker pointed at this endpoint gets a usable
        reply (not a defer), so it reaches messages:complete.
        """
        from fast_lane import fast_reply  # real worker module
        out = fast_reply(
            "hi from alice",
            api_key="mock-key",
            soul="",
            base_url=f"{self.base_url}/v1",
            model="MiniMax-M3",
            timeout=5.0,
            medium=False,
        )
        assert out == FAST_LANE_REPLY, f"fast lane should return the canned reply; got {out!r}"

    def test_shutdown_assertion_passes_on_clean_run(self) -> None:
        for uid, target in [("u_alice", "+1alice555"), ("u_bob", "+1bob999")]:
            _convex(self.base_url, "mutation", "messages:enqueue", {
                "userId": uid, "text": "hi", "replyTarget": target,
            })
            claim = _convex(self.base_url, "mutation", "messages:claimNextForUser", {
                "workerSecret": SECRET, "userId": uid,
            })
            _convex(self.base_url, "mutation", "messages:complete", {
                "workerSecret": SECRET, "id": claim["value"]["id"], "reply": "ok, handled.",
            })
        result = _post(self.base_url, "/shutdown", {})
        assert result["passed"] is True, f"clean run should pass; got {result}"

    def test_status_reports_done_after_completion(self) -> None:
        _convex(self.base_url, "mutation", "messages:enqueue", {
            "userId": "u_alice", "text": "hi", "replyTarget": "+1alice555",
        })
        # not done before completion
        assert _get(self.base_url, "/status")["done"] is False
        claim = _convex(self.base_url, "mutation", "messages:claimNextForUser", {
            "workerSecret": SECRET, "userId": "u_alice",
        })
        _convex(self.base_url, "mutation", "messages:complete", {
            "workerSecret": SECRET, "id": claim["value"]["id"], "reply": "ok, handled.",
        })
        # alice's only row is done; status over present rows is done.
        assert _get(self.base_url, "/status")["done"] is True
