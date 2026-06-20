"""SendblueChannel.send_rich now SENDS rich media (was: degrade-to-text kill-switch).

Operator chose to EXTEND the already-paid Sendblue line instead of paying Photon
~$250/mo. Sendblue natively supports the rich surface the project uses:
  * image/file/voice -> POST /send-message with `media_url` (a real attachment,
    not a text URL). Voice renders as a native voice note only for .caf; other
    audio arrives as an audio attachment (documented ceiling).
  * reaction/tapback -> POST /send-reaction {from_number, message_handle, reaction}
    where reaction is one of love|like|dislike|laugh|emphasize|question. The
    brain's arbitrary emoji is mapped onto that fixed set; unmappable -> skipped.
  * poll/text -> unchanged (poll degrades to a numbered list; iMessage has no poll).

Network-free: a recording fake client mirrors the real SendblueClient surface
(send_message(to_number, content, media_url), send_reaction(message_handle, reaction)).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skeleton"))

from channels.base import OutboundResult  # noqa: E402
from channels.sendblue_channel import SendblueChannel  # noqa: E402
from channels.rich import (  # noqa: E402
    FilePart,
    ImagePart,
    PollPart,
    ReactionPart,
    TextPart,
    VoicePart,
    parse_rich,
)

ADDR = "+15551234567"
HANDLE = "E8F2C3D1-A5B7-4E9F-8C1D-2A3B4C5D6E7F"  # an Apple GUID-shaped inbound handle


class RecordingClient:
    """Records send_message(media included) and send_reaction calls."""

    def __init__(self):
        self.sent = []       # list of dict(to_number, content, media_url)
        self.reactions = []  # list of dict(message_handle, reaction)

    def send_message(self, *, to_number, content="", media_url=None):
        self.sent.append({"to_number": to_number, "content": content, "media_url": media_url})
        return {"message_handle": "h1"}

    def send_reaction(self, *, message_handle, reaction):
        self.reactions.append({"message_handle": message_handle, "reaction": reaction})
        return {"message_handle": message_handle, "reaction": reaction}


def _ch():
    client = RecordingClient()
    return SendblueChannel(client), client


# ---- media: image / file / voice now go out as REAL attachments (media_url) ----

def test_image_part_sent_as_media_attachment_not_text():
    url = "https://cdn.example.com/cat.png"
    img = next(p for p in parse_rich(f"here you go {url}") if isinstance(p, ImagePart))
    ch, client = _ch()
    res = ch.send_rich(ADDR, img)
    assert res.ok is True
    assert len(client.sent) == 1
    sent = client.sent[0]
    assert sent["to_number"] == ADDR
    assert sent["media_url"] == url        # delivered as an attachment...
    assert not sent["content"]             # ...media-only, NOT a text URL


def test_file_part_sent_as_media_attachment():
    ch, client = _ch()
    res = ch.send_rich(ADDR, FilePart("https://x.io/report.pdf", name="report"))
    assert res.ok is True
    assert client.sent[0]["media_url"] == "https://x.io/report.pdf"


def test_voice_part_sent_as_media_attachment():
    ch, client = _ch()
    res = ch.send_rich(ADDR, VoicePart("https://x.io/clip.caf"))
    assert res.ok is True
    assert client.sent[0]["media_url"] == "https://x.io/clip.caf"


def test_non_remote_media_src_is_refused_file_exfil_guard():
    # A local path would make Sendblue (or our own code) read/exfiltrate a local
    # file; only http(s) URLs are allowed (mirrors PhotonChannel's guard).
    ch, client = _ch()
    for bad in ("/Users/x/.env", "../secret", "file:///etc/passwd"):
        res = ch.send_rich(ADDR, ImagePart(bad))
        assert res.ok is False
    assert client.sent == [] and client.reactions == []


def test_empty_src_returns_not_ok_and_sends_nothing():
    ch, client = _ch()
    for part in (ImagePart("  "), FilePart(""), VoicePart("")):
        assert ch.send_rich(ADDR, part).ok is False
    assert client.sent == []


def test_media_send_failure_falls_back_to_text_url_no_data_loss():
    # If the media POST fails, the URL must still reach the user as text (iMessage
    # auto-unfurls it) — preserves the original anti-regression intent.
    class FlakyMedia(RecordingClient):
        def send_message(self, *, to_number, content="", media_url=None):
            if media_url:
                raise RuntimeError("sendblue 500 on media")
            return super().send_message(to_number=to_number, content=content)

    client = FlakyMedia()
    ch = SendblueChannel(client)
    res = ch.send_rich(ADDR, ImagePart("https://x.io/a.png"))
    assert res.ok is True                          # recovered via text fallback
    assert client.sent[0]["content"] == "https://x.io/a.png"
    assert client.sent[0]["media_url"] is None


# ---- reactions: real tapbacks via /send-reaction, emoji mapped to the 6 types --

def test_reaction_with_reply_to_sends_tapback():
    ch, client = _ch()
    res = ch.send_rich(ADDR, ReactionPart("❤️"), reply_to=HANDLE)
    assert res.ok is True
    assert client.reactions == [{"message_handle": HANDLE, "reaction": "love"}]
    assert client.sent == []  # a reaction is not a message


def test_reaction_emoji_maps_to_fixed_tapbacks():
    cases = {"👍": "like", "👎": "dislike", "😂": "laugh", "🔥": "emphasize", "❓": "question"}
    for emoji, tapback in cases.items():
        ch, client = _ch()
        assert ch.send_rich(ADDR, ReactionPart(emoji), reply_to=HANDLE).ok is True
        assert client.reactions[0]["reaction"] == tapback


def test_reaction_accepts_a_literal_tapback_word():
    # The brain may emit the tapback name directly, e.g. [[react:love]].
    ch, client = _ch()
    assert ch.send_rich(ADDR, ReactionPart("love"), reply_to=HANDLE).ok is True
    assert client.reactions[0]["reaction"] == "love"


def test_reaction_without_reply_to_is_skipped():
    ch, client = _ch()
    res = ch.send_rich(ADDR, ReactionPart("❤️"))  # no reply_to target
    assert res.ok is False
    assert client.reactions == [] and client.sent == []


def test_unmappable_reaction_is_skipped_not_wrong_sentiment():
    # An emoji with no sensible tapback must NOT be coerced to a wrong one.
    ch, client = _ch()
    res = ch.send_rich(ADDR, ReactionPart("🦄"), reply_to=HANDLE)
    assert res.ok is False
    assert client.reactions == []


# ---- unchanged: text / poll -------------------------------------------------

def test_text_part_uses_send_message():
    ch, client = _ch()
    res = ch.send_rich(ADDR, TextPart("hello there"))
    assert res.ok is True
    assert client.sent[0]["to_number"] == ADDR and client.sent[0]["content"] == "hello there"


def test_poll_part_still_numbered_text_list():
    ch, client = _ch()
    res = ch.send_rich(ADDR, PollPart("pick one", ("apple", "banana")))
    assert res.ok is True
    assert client.sent[0]["content"] == "pick one\n1. apple\n2. banana"


# ---- best-effort contract: never raises -------------------------------------

def test_send_rich_never_raises_when_client_errors():
    class Boom:
        def send_message(self, *, to_number, content="", media_url=None):
            raise RuntimeError("sendblue 500")

    ch = SendblueChannel(Boom())
    res = ch.send_rich(ADDR, ImagePart("https://x.io/a.png"))
    assert isinstance(res, OutboundResult)
    assert res.ok is False and "500" in (res.error or "")
