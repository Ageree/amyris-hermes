"""Tests for the Sendblue typing-indicator client method."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from sendblue_client import SendblueClient  # noqa: E402


def _client():
    return SendblueClient(key_id="kid", secret="sec", from_number="+15550001111")


def test_send_typing_start_posts_expected_payload_and_endpoint():
    client = _client()
    with patch("sendblue_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {"status": "SENT", "error_message": None}
        )
        resp = client.send_typing("+15557654321", state="start", max_duration_ms=10000)
    assert resp["status"] == "SENT"
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.sendblue.co/api/send-typing-indicator"
    body = kwargs["json"]
    assert body["from_number"] == "+15550001111"
    assert body["number"] == "+15557654321"
    assert body["state"] == "start"
    assert body["max_duration_ms"] == 10000
    assert kwargs["headers"]["sb-api-key-id"] == "kid"


def test_send_typing_stop_omits_duration():
    client = _client()
    with patch("sendblue_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "SENT"})
        client.send_typing("+1555", state="stop")
    body = mock_post.call_args.kwargs["json"]
    assert body["state"] == "stop"
    assert "max_duration_ms" not in body


def test_send_typing_defaults_to_start():
    client = _client()
    with patch("sendblue_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "SENT"})
        client.send_typing("+1555")
    assert mock_post.call_args.kwargs["json"]["state"] == "start"


def test_send_typing_raises_on_non_2xx():
    client = _client()
    with patch("sendblue_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=400, text="bad")
        try:
            client.send_typing("+1555")
            assert False, "expected error"
        except RuntimeError as e:
            assert "400" in str(e)


def test_send_typing_rejects_bad_args():
    client = _client()
    for to_number, state in (("", "start"), ("+1555", "wiggle")):
        try:
            client.send_typing(to_number, state=state)
            assert False, "expected ValueError"
        except ValueError:
            pass
