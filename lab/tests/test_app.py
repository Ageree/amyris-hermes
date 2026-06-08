"""Tests for the FastAPI inbound webhook app (Task 5) + the [SECURITY] hardening.

Uses fastapi.testclient.TestClient; run_hermes and SendblueClient.send_message
are mocked. Import convention matches the existing lab tests: sys.path-insert
the skeleton source dir and import the bare module name.

[SECURITY] coverage (3 findings):
  1. Auth — secret path token (constant-time) + reply-target allowlist.
  2. Idempotency — empty-handle hard reject + bounded LRU dedup store.
  3. Blocking — run_hermes runs via asyncio.to_thread under a concurrency cap,
     with an explicit timeout=60.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from fastapi.testclient import TestClient
from app import create_app
from _dedup import BoundedDedup

TOKEN = "s3cr3t-t0ken"
ALLOWED = "+1555"

PAYLOAD = {"content": "hello", "number": ALLOWED, "is_outbound": False,
           "message_handle": "h1", "opted_out": False}

GOOD_URL = f"/sendblue/inbound/{TOKEN}"


class _FakeCfg:
    sendblue_key_id = "k"
    sendblue_secret = "s"
    sendblue_from = "+1999"
    webhook_secret = TOKEN
    allowed_user_number = ALLOWED
    max_concurrency = 1
    hermes_home = "/h"
    hermes_dir = "/d"
    python_bin = "/p"


def _client():
    return TestClient(create_app(_FakeCfg()))


def test_healthz():
    r = _client().get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_inbound_runs_hermes_and_replies():
    with patch("app.run_hermes", return_value="hi back") as rh, \
         patch("app.SendblueClient.send_message", return_value={"status": "QUEUED"}) as sm:
        r = _client().post(GOOD_URL, json=PAYLOAD)
    assert r.status_code == 200
    rh.assert_called_once()
    assert sm.call_args.kwargs.get("content") == "hi back" or sm.call_args.args[1] == "hi back"


def test_inbound_ignores_outbound_echo_without_calling_hermes():
    with patch("app.run_hermes") as rh:
        r = _client().post(GOOD_URL, json={**PAYLOAD, "is_outbound": True})
    assert r.status_code == 200
    rh.assert_not_called()


def test_inbound_dedupes_by_handle():
    with patch("app.run_hermes", return_value="x") as rh, \
         patch("app.SendblueClient.send_message", return_value={}):
        c = _client()
        c.post(GOOD_URL, json=PAYLOAD)
        c.post(GOOD_URL, json=PAYLOAD)  # same handle
    assert rh.call_count == 1


def test_inbound_never_500s_when_hermes_raises():
    with patch("app.run_hermes", side_effect=RuntimeError("boom")), \
         patch("app.SendblueClient.send_message", return_value={}) as sm:
        r = _client().post(GOOD_URL, json=PAYLOAD)
    assert r.status_code == 200
    # A friendly error reply is still sent back to the user.
    sent = sm.call_args.kwargs.get("content") or sm.call_args.args[1]
    assert "error" in sent.lower()


def test_inbound_never_500s_when_sendblue_raises():
    with patch("app.run_hermes", return_value="ok"), \
         patch("app.SendblueClient.send_message", side_effect=RuntimeError("sb down")):
        r = _client().post(GOOD_URL, json=PAYLOAD)
    assert r.status_code == 200


def test_inbound_truncates_reply_to_1800_chars():
    long_reply = "z" * 5000
    with patch("app.run_hermes", return_value=long_reply), \
         patch("app.SendblueClient.send_message", return_value={}) as sm:
        _client().post(GOOD_URL, json=PAYLOAD)
    sent = sm.call_args.kwargs.get("content") or sm.call_args.args[1]
    assert len(sent) == 1800


def test_inbound_handles_invalid_json_without_500():
    r = _client().post(GOOD_URL, data="not json",
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Finding 1a — secret path token (constant-time auth gate)
# ---------------------------------------------------------------------------

def test_inbound_wrong_token_returns_401_without_calling_hermes():
    with patch("app.run_hermes") as rh:
        r = _client().post("/sendblue/inbound/WRONG", json=PAYLOAD)
    assert r.status_code == 401
    rh.assert_not_called()


def test_inbound_absent_token_is_not_routed_and_does_not_call_hermes():
    # No token segment at all -> the route does not match -> 404, never processed.
    with patch("app.run_hermes") as rh:
        r = _client().post("/sendblue/inbound", json=PAYLOAD)
    assert r.status_code in (404, 405)
    rh.assert_not_called()


def test_inbound_correct_token_is_processed():
    with patch("app.run_hermes", return_value="ok") as rh, \
         patch("app.SendblueClient.send_message", return_value={}):
        r = _client().post(GOOD_URL, json=PAYLOAD)
    assert r.status_code == 200
    rh.assert_called_once()


# ---------------------------------------------------------------------------
# Finding 1b — reply-target allowlist (server-side identity)
# ---------------------------------------------------------------------------

def test_inbound_from_non_allowed_number_is_ignored_without_calling_hermes():
    with patch("app.run_hermes") as rh, \
         patch("app.SendblueClient.send_message") as sm:
        r = _client().post(GOOD_URL, json={**PAYLOAD, "number": "+1888"})
    assert r.status_code == 200
    assert r.json() == {"ignored": True}
    rh.assert_not_called()
    sm.assert_not_called()


def test_reply_always_goes_to_allowed_number_even_if_payload_differs():
    # Authenticated but malicious payload: a DIFFERENT 'number'. Reply must STILL
    # go to allowed_user_number — destination is derived from config, never payload.
    # (Such a payload is rejected by the allowlist, so we instead assert that even
    #  when the allowlist passes, to_number is config-derived.)
    with patch("app.run_hermes", return_value="ok"), \
         patch("app.SendblueClient.send_message", return_value={}) as sm:
        _client().post(GOOD_URL, json=PAYLOAD)
    to_number = sm.call_args.kwargs.get("to_number") or sm.call_args.args[0]
    assert to_number == ALLOWED


def test_reply_target_ignores_extra_attacker_controlled_fields():
    # An authenticated payload carrying attacker-controlled routing-ish fields
    # (e.g. a forged from_number) must NOT influence the reply destination — it
    # is always config-derived.
    with patch("app.run_hermes", return_value="ok"), \
         patch("app.SendblueClient.send_message", return_value={}) as sm:
        _client().post(GOOD_URL, json={**PAYLOAD, "from_number": "+1666"})
    to_number = sm.call_args.kwargs.get("to_number") or sm.call_args.args[0]
    assert to_number == ALLOWED


# ---------------------------------------------------------------------------
# Finding 2 — idempotency: empty-handle hard reject + bounded dedup
# ---------------------------------------------------------------------------

def test_inbound_empty_handle_is_hard_rejected_without_calling_hermes():
    with patch("app.run_hermes") as rh, \
         patch("app.SendblueClient.send_message") as sm:
        r = _client().post(GOOD_URL, json={**PAYLOAD, "message_handle": ""})
    assert r.status_code == 200
    assert r.json() == {"ignored": True}
    rh.assert_not_called()
    sm.assert_not_called()


def test_inbound_missing_handle_is_hard_rejected_without_calling_hermes():
    body = {k: v for k, v in PAYLOAD.items() if k != "message_handle"}
    with patch("app.run_hermes") as rh, \
         patch("app.SendblueClient.send_message") as sm:
        r = _client().post(GOOD_URL, json=body)
    assert r.status_code == 200
    assert r.json() == {"ignored": True}
    rh.assert_not_called()
    sm.assert_not_called()


def test_bounded_dedup_evicts_and_never_exceeds_cap():
    d = BoundedDedup(maxsize=3)
    assert d.add("a") is True
    assert d.add("b") is True
    assert d.add("c") is True
    assert d.add("a") is False  # duplicate
    assert len(d) == 3
    # adding a 4th distinct key evicts the oldest ("a")
    assert d.add("d") is True
    assert len(d) == 3
    assert "a" not in d
    assert "d" in d
    # flood far past the cap — never grows beyond maxsize
    for i in range(1000):
        d.add(f"k{i}")
    assert len(d) == 3


# ---------------------------------------------------------------------------
# Finding 3 — non-blocking: run_hermes via asyncio.to_thread, timeout=60
# ---------------------------------------------------------------------------

def test_run_hermes_is_invoked_via_to_thread_with_timeout_60():
    real_to_thread = asyncio.to_thread

    async def _spy(func, *args, **kwargs):
        _spy.called = True
        _spy.func = func
        _spy.kwargs = kwargs
        return await real_to_thread(func, *args, **kwargs)

    _spy.called = False

    with patch("app.run_hermes", return_value="ok") as rh, \
         patch("app.SendblueClient.send_message", return_value={}), \
         patch("app.asyncio.to_thread", new=_spy):
        r = _client().post(GOOD_URL, json=PAYLOAD)

    assert r.status_code == 200
    assert _spy.called is True
    assert _spy.func is rh  # the patched run_hermes was the thing dispatched
    # timeout=60 is passed through to run_hermes (not the bridge default of 180)
    assert _spy.kwargs.get("timeout") == 60
    assert rh.call_args.kwargs.get("timeout") == 60
