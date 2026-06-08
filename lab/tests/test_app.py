"""Tests for the FastAPI inbound webhook app (Task 5).

Uses fastapi.testclient.TestClient; run_hermes and SendblueClient.send_message
are mocked. Import convention matches the existing lab tests: sys.path-insert
the skeleton source dir and import the bare module name.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from fastapi.testclient import TestClient
from app import create_app

PAYLOAD = {"content": "hello", "number": "+1555", "is_outbound": False,
           "message_handle": "h1", "opted_out": False}


class _FakeCfg:
    sendblue_key_id = "k"
    sendblue_secret = "s"
    sendblue_from = "+1999"
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
        r = _client().post("/sendblue/inbound", json=PAYLOAD)
    assert r.status_code == 200
    rh.assert_called_once()
    assert sm.call_args.kwargs.get("content") == "hi back" or sm.call_args.args[1] == "hi back"


def test_inbound_ignores_outbound_echo_without_calling_hermes():
    with patch("app.run_hermes") as rh:
        r = _client().post("/sendblue/inbound", json={**PAYLOAD, "is_outbound": True})
    assert r.status_code == 200
    rh.assert_not_called()


def test_inbound_dedupes_by_handle():
    with patch("app.run_hermes", return_value="x") as rh, \
         patch("app.SendblueClient.send_message", return_value={}):
        c = _client()
        c.post("/sendblue/inbound", json=PAYLOAD)
        c.post("/sendblue/inbound", json=PAYLOAD)  # same handle
    assert rh.call_count == 1


def test_inbound_never_500s_when_hermes_raises():
    with patch("app.run_hermes", side_effect=RuntimeError("boom")), \
         patch("app.SendblueClient.send_message", return_value={}) as sm:
        r = _client().post("/sendblue/inbound", json=PAYLOAD)
    assert r.status_code == 200
    # A friendly error reply is still sent back to the user.
    sent = sm.call_args.kwargs.get("content") or sm.call_args.args[1]
    assert "error" in sent.lower()


def test_inbound_never_500s_when_sendblue_raises():
    with patch("app.run_hermes", return_value="ok"), \
         patch("app.SendblueClient.send_message", side_effect=RuntimeError("sb down")):
        r = _client().post("/sendblue/inbound", json=PAYLOAD)
    assert r.status_code == 200


def test_inbound_truncates_reply_to_1800_chars():
    long_reply = "z" * 5000
    with patch("app.run_hermes", return_value=long_reply), \
         patch("app.SendblueClient.send_message", return_value={}) as sm:
        _client().post("/sendblue/inbound", json=PAYLOAD)
    sent = sm.call_args.kwargs.get("content") or sm.call_args.args[1]
    assert len(sent) == 1800


def test_inbound_handles_invalid_json_without_500():
    r = _client().post("/sendblue/inbound", data="not json",
                       headers={"Content-Type": "application/json"})
    assert r.status_code == 200
