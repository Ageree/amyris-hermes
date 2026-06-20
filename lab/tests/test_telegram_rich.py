"""Telegram rich messaging (B2): client media methods + channel send_rich dispatch.

Network-free: requests.post is monkeypatched (client tests) / TelegramClient is faked
(channel tests). Asserts each RichPart kind hits the correct Bot API method + payload
shape (sendPoll InputPollOption objects; setMessageReaction emoji ReactionType), and
that send_rich is best-effort (degrades, never raises). The LIVE round-trip is the
operator-run live_channel tier.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import channels.telegram_client as tc_mod  # noqa: E402
from channels.telegram_client import TelegramClient, MAX_RETRY_AFTER  # noqa: E402
from channels.telegram_channel import TelegramChannel  # noqa: E402
from channels.rich import (  # noqa: E402
    FilePart,
    ImagePart,
    PollPart,
    ReactionPart,
    TextPart,
    VoicePart,
)


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
# TelegramClient — media + poll + reaction wire shapes
# --------------------------------------------------------------------------- #

def test_send_photo_payload(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True, "result": {"message_id": 5}})])
    out = TelegramClient("123:abc").send_photo("555", "https://x.test/a.png", "cap")
    url, payload = sent[0]
    assert url.endswith("/bot123:abc/sendPhoto")
    assert payload["chat_id"] == "555"
    assert payload["photo"] == "https://x.test/a.png"
    assert payload["caption"] == "cap"
    assert payload["parse_mode"] == "HTML"
    assert out["result"]["message_id"] == 5


def test_send_photo_no_caption_omits_caption(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True})])
    TelegramClient("t").send_photo("555", "https://x.test/a.png")
    payload = sent[0][1]
    assert "caption" not in payload
    assert "parse_mode" not in payload


def test_send_document_payload(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True})])
    TelegramClient("t").send_document("555", "https://x.test/report.pdf")
    url, payload = sent[0]
    assert url.endswith("/sendDocument")
    assert payload["document"] == "https://x.test/report.pdf"


def test_send_voice_payload(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True})])
    TelegramClient("t").send_voice("555", "https://x.test/note.ogg")
    url, payload = sent[0]
    assert url.endswith("/sendVoice")
    assert payload == {"chat_id": "555", "voice": "https://x.test/note.ogg"}


def test_send_poll_uses_inputpolloption_objects(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True, "result": {"message_id": 7}})])
    out = TelegramClient("t").send_poll("555", "Pizza?", ["yes", "no", "maybe"])
    url, payload = sent[0]
    assert url.endswith("/sendPoll")
    assert payload["chat_id"] == "555"
    assert payload["question"] == "Pizza?"
    # Bot API 7.0+: options are InputPollOption objects, not bare strings.
    assert payload["options"] == [{"text": "yes"}, {"text": "no"}, {"text": "maybe"}]
    assert out["result"]["message_id"] == 7


def test_send_poll_coerces_non_str_options(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True})])
    TelegramClient("t").send_poll("555", "Pick", [1, 2])
    assert sent[0][1]["options"] == [{"text": "1"}, {"text": "2"}]


def test_set_message_reaction_shape(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(200, {"ok": True, "result": True})])
    TelegramClient("t").set_message_reaction("555", 42, "❤️")
    url, payload = sent[0]
    assert url.endswith("/setMessageReaction")
    assert payload["chat_id"] == "555"
    assert payload["message_id"] == 42
    assert payload["reaction"] == [{"type": "emoji", "emoji": "❤️"}]


def test_media_400_caption_retries_plain(monkeypatch):
    sent = _patch_post(monkeypatch, [_Resp(400, text="bad caption"), _Resp(200, {"ok": True})])
    TelegramClient("t").send_photo("555", "https://x.test/a.png", "<b>broken")
    assert len(sent) == 2
    assert "parse_mode" in sent[0][1]
    assert "parse_mode" not in sent[1][1]  # plain-caption retry


def test_media_429_honors_retry_after(monkeypatch):
    _patch_post(monkeypatch, [_Resp(429, {"parameters": {"retry_after": 3}}), _Resp(200, {"ok": True})])
    slept = []
    TelegramClient("t", sleep_fn=lambda s: slept.append(s)).send_photo("555", "https://x.test/a.png")
    assert slept == [3.0]


def test_media_429_capped(monkeypatch):
    _patch_post(monkeypatch, [_Resp(429, {"parameters": {"retry_after": 9999}}), _Resp(200, {"ok": True})])
    slept = []
    TelegramClient("t", sleep_fn=lambda s: slept.append(s)).send_document("555", "https://x.test/r.pdf")
    assert slept == [MAX_RETRY_AFTER]


def test_send_poll_non_2xx_raises(monkeypatch):
    _patch_post(monkeypatch, [_Resp(500, text="boom")])
    with pytest.raises(RuntimeError):
        TelegramClient("t").send_poll("555", "q", ["a", "b"])


def test_set_reaction_non_2xx_raises(monkeypatch):
    _patch_post(monkeypatch, [_Resp(400, text="nope")])
    with pytest.raises(RuntimeError):
        TelegramClient("t").set_message_reaction("555", 1, "👍")


# --------------------------------------------------------------------------- #
# TelegramChannel.send_rich — dispatch + degradation (best-effort, never raises)
# --------------------------------------------------------------------------- #

class _FakeClient:
    """Records calls; each method returns a Bot API-shaped dict with a message_id."""

    def __init__(self):
        self.calls = []
        self.fail = None  # method name to make raise

    def _maybe_fail(self, method):
        if self.fail == method:
            raise RuntimeError(f"simulated {method} failure")

    def send_message(self, chat_id, text, **kw):
        self._maybe_fail("send_message")
        self.calls.append(("send_message", chat_id, text))
        return {"ok": True, "result": {"message_id": 100}}

    def send_photo(self, chat_id, photo, caption=None, **kw):
        self._maybe_fail("send_photo")
        self.calls.append(("send_photo", chat_id, photo))
        return {"ok": True, "result": {"message_id": 101}}

    def send_document(self, chat_id, document, caption=None, **kw):
        self._maybe_fail("send_document")
        self.calls.append(("send_document", chat_id, document))
        return {"ok": True, "result": {"message_id": 102}}

    def send_voice(self, chat_id, voice, **kw):
        self._maybe_fail("send_voice")
        self.calls.append(("send_voice", chat_id, voice))
        return {"ok": True, "result": {"message_id": 103}}

    def send_poll(self, chat_id, question, options, **kw):
        self._maybe_fail("send_poll")
        self.calls.append(("send_poll", chat_id, question, options))
        return {"ok": True, "result": {"message_id": 104}}

    def set_message_reaction(self, chat_id, message_id, emoji, **kw):
        self._maybe_fail("set_message_reaction")
        self.calls.append(("set_message_reaction", chat_id, message_id, emoji))
        return {"ok": True, "result": True}


def _channel():
    # These tests exercise RichPart DISPATCH + back-compat, not rich-markdown, so
    # pin classic mode for deterministic behavior independent of TELEGRAM_RICH_ENABLED.
    c = _FakeClient()
    return TelegramChannel(c, rich_markdown=False), c


def test_send_rich_text_uses_send_message():
    ch, client = _channel()
    res = ch.send_rich("555", TextPart("hello"))
    assert res.ok and res.provider_id == "100"
    assert client.calls[0][0] == "send_message"
    assert client.calls[0][2] == "hello"


def test_send_rich_image_uses_send_photo():
    ch, client = _channel()
    res = ch.send_rich("555", ImagePart("https://x.test/a.png"))
    assert res.ok and res.provider_id == "101"
    assert client.calls[0] == ("send_photo", "555", "https://x.test/a.png")


def test_send_rich_file_uses_send_document():
    ch, client = _channel()
    res = ch.send_rich("555", FilePart("https://x.test/r.pdf", name="r.pdf"))
    assert res.ok and res.provider_id == "102"
    assert client.calls[0] == ("send_document", "555", "https://x.test/r.pdf")


def test_send_rich_voice_uses_send_voice():
    ch, client = _channel()
    res = ch.send_rich("555", VoicePart("https://x.test/note.ogg"))
    assert res.ok and res.provider_id == "103"
    assert client.calls[0] == ("send_voice", "555", "https://x.test/note.ogg")


def test_send_rich_poll_native_send_poll():
    ch, client = _channel()
    res = ch.send_rich("555", PollPart("Pizza?", ("yes", "no")))
    assert res.ok and res.provider_id == "104"
    method, chat, question, options = client.calls[0]
    assert method == "send_poll"
    assert question == "Pizza?"
    # tuple options become a list for the client (which wraps to InputPollOption).
    assert options == ["yes", "no"]


def test_send_rich_reaction_with_reply_to():
    ch, client = _channel()
    res = ch.send_rich("555", ReactionPart("❤️"), reply_to="42")
    assert res.ok
    assert client.calls[0] == ("set_message_reaction", "555", "42", "❤️")


def test_send_rich_reaction_without_reply_to_degrades():
    ch, client = _channel()
    res = ch.send_rich("555", ReactionPart("❤️"))  # no reply_to target
    assert res.ok is False
    assert "reply_to" in (res.error or "")
    assert client.calls == []  # nothing sent — graceful skip, no raise


def test_send_rich_client_error_is_best_effort():
    ch, client = _channel()
    client.fail = "send_photo"
    res = ch.send_rich("555", ImagePart("https://x.test/a.png"))
    assert res.ok is False
    assert "simulated" in (res.error or "")  # swallowed, not raised


def test_send_rich_unknown_part_degrades():
    ch, client = _channel()

    class Weird:
        pass

    res = ch.send_rich("555", Weird())
    assert res.ok is False
    assert "unsupported" in (res.error or "")
    assert client.calls == []


# --------------------------------------------------------------------------- #
# Back-compat: existing text path untouched
# --------------------------------------------------------------------------- #

def test_existing_send_message_still_works():
    ch, client = _channel()
    res = ch.send_message("555", "plain reply")
    assert res.ok and res.provider_id == "100"
    assert client.calls[0][0] == "send_message"


def test_render_and_split_unchanged():
    ch, _ = _channel()
    # render() must still produce HTML; split() must still chunk. (smoke, not exhaustive)
    assert isinstance(ch.render("**bold**"), str)
    assert isinstance(ch.split("hello world"), list)
