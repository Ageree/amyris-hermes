"""Telegram NEW rich messages (Bot API 10.1 sendRichMessage).

Client: requests.post is monkeypatched (network-free) — asserts the EXACT wire
body `rich_message.markdown` (probed live against api.telegram.org) and the 429
bounded-retry. Channel: TelegramClient is faked — asserts the main text reply goes
out as ONE sendRichMessage with the RAW reply text (not html-rendered, not split),
falls back to classic sendMessage on any rich failure (reply never lost), and that
TELEGRAM_RICH_ENABLED=0 uses the classic path byte-identical to today.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import channels.telegram_client as tc_mod  # noqa: E402
from channels.telegram_client import TelegramClient, MAX_RETRY_AFTER  # noqa: E402
from channels.telegram_channel import TelegramChannel  # noqa: E402
from channels.rich import TextPart  # noqa: E402


class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _patch_post(monkeypatch, responses):
    """Patch requests.post to return `responses` in order; record (url, payload)."""
    sent = []
    seq = list(responses)

    def fake_post(url, json=None, timeout=None):
        sent.append((url, json))
        return seq.pop(0) if seq else _Resp(200, {"ok": True})

    monkeypatch.setattr(tc_mod.requests, "post", fake_post)
    return sent


# --------------------------------------------------------------------------- #
# TelegramClient.send_rich_message — wire shape (rich_message.markdown) + 429
# --------------------------------------------------------------------------- #

def test_send_rich_message_wire_body(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True, "result": {"message_id": 7}})])
    md = "# Title\n\n- a\n- b\n\n> quote"
    out = TelegramClient("123:abc").send_rich_message("555", md)
    url, payload = sent[0]
    assert url.endswith("/bot123:abc/sendRichMessage")
    assert payload["chat_id"] == "555"
    # The EXACT field probed live: rich_message.markdown (== the raw text).
    assert payload["rich_message"] == {"markdown": md}
    assert "reply_markup" not in payload
    assert out["result"]["message_id"] == 7


def test_send_rich_message_plumbs_reply_markup(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True})])
    kb = {"inline_keyboard": [[{"text": "Open", "url": "https://x.test"}]]}
    TelegramClient("t").send_rich_message("555", "hi", reply_markup=kb)
    assert sent[0][1]["reply_markup"] == kb


def test_send_rich_message_429_honors_retry_after(monkeypatch):
    _patch_post(monkeypatch, [_Resp(429, {"parameters": {"retry_after": 4}}), _Resp(200, {"ok": True})])
    slept = []
    TelegramClient("t", sleep_fn=lambda s: slept.append(s)).send_rich_message("555", "hi")
    assert slept == [4.0]


def test_send_rich_message_429_capped(monkeypatch):
    _patch_post(monkeypatch, [_Resp(429, {"parameters": {"retry_after": 9999}}), _Resp(200, {"ok": True})])
    slept = []
    TelegramClient("t", sleep_fn=lambda s: slept.append(s)).send_rich_message("555", "hi")
    assert slept == [MAX_RETRY_AFTER]  # hostile retry_after can't hang the loop


def test_send_rich_message_non_2xx_raises(monkeypatch):
    # A non-recoverable non-2xx (e.g. wrong field -> 400) raises, same contract as siblings.
    _patch_post(monkeypatch, [_Resp(400, text="rich message must be non-empty")])
    with pytest.raises(RuntimeError):
        TelegramClient("t").send_rich_message("555", "hi")


# --------------------------------------------------------------------------- #
# TelegramChannel — rich main-text reply + robust classic fallback + kill-switch
# --------------------------------------------------------------------------- #

class _FakeClient:
    """Records calls. Mirrors the client surface; either send path can be made to fail."""

    def __init__(self):
        self.rich_calls = []
        self.classic_calls = []
        self.fail_rich = False

    def send_rich_message(self, chat_id, markdown, *, reply_markup=None):
        self.rich_calls.append((chat_id, markdown, reply_markup))
        if self.fail_rich:
            raise RuntimeError("simulated sendRichMessage failure")
        return {"ok": True, "result": {"message_id": 200}}

    def send_message(self, chat_id, text, **kw):
        self.classic_calls.append((chat_id, text))
        return {"ok": True, "result": {"message_id": 100}}


def test_rich_enabled_sends_one_rich_message_with_raw_text():
    client = _FakeClient()
    ch = TelegramChannel(client, rich_markdown=True)
    raw = "# Heading\n\n**bold** and a [link](https://x.test)\n\n- one\n- two"
    res = ch.send_message("555", raw)
    assert res.ok and res.provider_id == "200"
    # ONE sendRichMessage, raw text verbatim (NOT html-rendered, NOT split).
    assert len(client.rich_calls) == 1
    assert client.rich_calls[0] == ("555", raw, None)
    assert client.classic_calls == []  # classic path NOT used


def test_rich_send_text_part_routes_through_rich():
    client = _FakeClient()
    ch = TelegramChannel(client, rich_markdown=True)
    res = ch.send_rich("555", TextPart("## hi\n\n> quote"))
    assert res.ok and res.provider_id == "200"
    assert client.rich_calls[0] == ("555", "## hi\n\n> quote", None)


def test_rich_render_and_split_are_passthrough():
    # The worker's render()->split()->send_message path must feed RAW markdown
    # through in rich mode (no HTML, single chunk).
    ch = TelegramChannel(_FakeClient(), rich_markdown=True)
    raw = "# Title\n\n**bold**\n\n- a\n- b"
    assert ch.render(raw) == raw          # no render_html
    assert ch.split(raw) == [raw]         # no bubble-split


def test_rich_failure_falls_back_to_classic_and_reply_not_lost():
    client = _FakeClient()
    client.fail_rich = True
    ch = TelegramChannel(client, rich_markdown=True)
    res = ch.send_message("555", "**hi**")
    assert res.ok and res.provider_id == "100"  # reply STILL delivered via classic
    assert len(client.rich_calls) == 1          # rich was attempted...
    assert len(client.classic_calls) == 1       # ...then fell back to classic
    # Fallback renders the raw markdown to HTML (the raw text was never html-rendered).
    assert client.classic_calls[0][1] == "<b>hi</b>"


def test_rich_disabled_uses_classic_path_byte_identical():
    client = _FakeClient()
    ch = TelegramChannel(client, rich_markdown=False)
    # Classic: worker pre-renders via render() then send_message(already-HTML).
    rendered = ch.render("**hi**")          # render_html -> "<b>hi</b>"
    assert rendered == "<b>hi</b>"
    chunks = ch.split(rendered)             # classic tag-safe split
    assert chunks == ["<b>hi</b>"]
    res = ch.send_message("555", chunks[0])
    assert res.ok and res.provider_id == "100"
    assert client.rich_calls == []          # rich never touched
    assert client.classic_calls[0] == ("555", "<b>hi</b>")  # sent as-is, no re-render


def test_env_kill_switch_off(monkeypatch):
    monkeypatch.setenv("TELEGRAM_RICH_ENABLED", "0")
    ch = TelegramChannel(_FakeClient())  # no explicit flag -> reads env
    assert ch._rich is False


def test_env_default_on(monkeypatch):
    monkeypatch.delenv("TELEGRAM_RICH_ENABLED", raising=False)
    ch = TelegramChannel(_FakeClient())
    assert ch._rich is True


def test_rich_empty_body_short_circuits():
    client = _FakeClient()
    ch = TelegramChannel(client, rich_markdown=True)
    res = ch.send_message("555", "   ")
    assert res.ok is False and "empty" in (res.error or "")
    assert client.rich_calls == [] and client.classic_calls == []
