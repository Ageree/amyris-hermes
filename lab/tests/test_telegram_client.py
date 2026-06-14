"""TelegramClient HTTP wiring (M3): HTML payload, 400->plain, 429 retry_after.

Network-free: `requests.post` is monkeypatched with a fake response sequence. The
LIVE Telegram round-trip is the operator-run live_channel test.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import channels.telegram_client as tc_mod  # noqa: E402
from channels.telegram_client import TelegramClient, MAX_RETRY_AFTER  # noqa: E402


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _patch_post(monkeypatch, responses):
    """Patch requests.post to return `responses` in order; record sent payloads."""
    sent = []
    seq = list(responses)

    def fake_post(url, json=None, timeout=None):
        sent.append((url, json))
        return seq.pop(0) if seq else _Resp(200, {"ok": True})

    monkeypatch.setattr(tc_mod.requests, "post", fake_post)
    return sent


def test_requires_token():
    with pytest.raises(ValueError):
        TelegramClient("")


def test_send_message_html_payload(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True, "result": {"message_id": 1}})])
    TelegramClient("123:abc").send_message("555", "<b>hi</b>")
    url, payload = sent[0]
    assert url.endswith("/bot123:abc/sendMessage")
    assert payload["chat_id"] == "555"
    assert payload["text"] == "<b>hi</b>"
    assert payload["parse_mode"] == "HTML"
    assert payload["link_preview_options"] == {"is_disabled": True}


def test_send_message_returns_json(monkeypatch):
    _patch_post(monkeypatch, [_Resp(200, {"ok": True, "result": {"message_id": 9}})])
    out = TelegramClient("t").send_message("555", "hi")
    assert out["result"]["message_id"] == 9


def test_link_preview_can_be_enabled(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True})])
    TelegramClient("t").send_message("555", "hi", disable_link_preview=False)
    assert "link_preview_options" not in sent[0][1]


def test_400_retries_without_parse_mode(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(400, text="bad entity"), _Resp(200, {"ok": True})])
    TelegramClient("t").send_message("555", "<b>broken")
    assert len(sent) == 2
    assert "parse_mode" in sent[0][1]
    assert "parse_mode" not in sent[1][1]  # plain-text retry


def test_400_without_parse_mode_does_not_loop(monkeypatch):
    # A 400 on a plain (no parse_mode) send must NOT retry again -> it raises.
    sent = _patch_post(monkeypatch, [_Resp(400, text="still bad")])
    with pytest.raises(RuntimeError):
        TelegramClient("t").send_message("555", "hi", parse_mode=None)
    assert len(sent) == 1


def test_429_honors_retry_after(monkeypatch):
    _patch_post(monkeypatch, [_Resp(429, {"parameters": {"retry_after": 2}}), _Resp(200, {"ok": True})])
    slept = []
    c = TelegramClient("t", sleep_fn=lambda s: slept.append(s))
    c.send_message("555", "hi")
    assert slept == [2.0]


def test_429_retry_after_is_capped(monkeypatch):
    _patch_post(monkeypatch, [_Resp(429, {"parameters": {"retry_after": 9999}}), _Resp(200, {"ok": True})])
    slept = []
    TelegramClient("t", sleep_fn=lambda s: slept.append(s)).send_message("555", "hi")
    assert slept == [MAX_RETRY_AFTER]  # a hostile retry_after can't hang the loop


def test_429_malformed_retry_after_defaults(monkeypatch):
    _patch_post(monkeypatch, [_Resp(429, {"bogus": True}), _Resp(200, {"ok": True})])
    slept = []
    TelegramClient("t", sleep_fn=lambda s: slept.append(s)).send_message("555", "hi")
    assert slept == [1.0]


def test_non_2xx_raises(monkeypatch):
    _patch_post(monkeypatch, [_Resp(500, text="boom")])
    with pytest.raises(RuntimeError):
        TelegramClient("t").send_message("555", "hi")


def test_send_chat_action(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True})])
    TelegramClient("t").send_chat_action("555", "typing")
    url, payload = sent[0]
    assert url.endswith("/sendChatAction")
    assert payload == {"chat_id": "555", "action": "typing"}


def test_send_chat_action_non_2xx_raises(monkeypatch):
    _patch_post(monkeypatch, [_Resp(403, text="forbidden")])
    with pytest.raises(RuntimeError):
        TelegramClient("t").send_chat_action("555")
