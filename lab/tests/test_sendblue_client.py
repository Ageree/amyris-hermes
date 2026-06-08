"""Tests for the Sendblue outbound client (Task 1).

Import convention matches the existing lab tests (test_resolve.py / test_library.py):
add the source dir to sys.path, then import the bare module name. Source lives in
lab/skeleton/, tests live in lab/tests/ so the repo's pytest.ini (testpaths = tests)
discovers them.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from sendblue_client import SendblueClient


def test_send_message_posts_expected_payload_and_headers():
    client = SendblueClient(key_id="kid", secret="sec", from_number="+15550001111")
    with patch("sendblue_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "QUEUED"})
        resp = client.send_message(to_number="+15557654321", content="hi")
    assert resp["status"] == "QUEUED"
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.sendblue.co/api/send-message"
    assert kwargs["headers"]["sb-api-key-id"] == "kid"
    assert kwargs["headers"]["sb-api-secret-key"] == "sec"
    body = json.loads(kwargs["data"]) if "data" in kwargs else kwargs["json"]
    assert body["number"] == "+15557654321"
    assert body["from_number"] == "+15550001111"
    assert body["content"] == "hi"


def test_send_message_raises_on_non_2xx():
    client = SendblueClient(key_id="kid", secret="sec", from_number="+15550001111")
    with patch("sendblue_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=401, text="unauthorized")
        try:
            client.send_message(to_number="+1555", content="x")
            assert False, "expected error"
        except RuntimeError as e:
            assert "401" in str(e)


def test_constructor_rejects_missing_credentials():
    for kwargs in (
        {"key_id": "", "secret": "s", "from_number": "+1"},
        {"key_id": "k", "secret": "", "from_number": "+1"},
        {"key_id": "k", "secret": "s", "from_number": ""},
    ):
        try:
            SendblueClient(**kwargs)
            assert False, "expected ValueError"
        except ValueError:
            pass


def test_send_message_rejects_empty_args():
    client = SendblueClient(key_id="k", secret="s", from_number="+1")
    for to_number, content in (("", "hi"), ("+1555", "")):
        try:
            client.send_message(to_number=to_number, content=content)
            assert False, "expected ValueError"
        except ValueError:
            pass
