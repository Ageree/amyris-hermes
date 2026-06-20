"""Regression: SendblueChannel.send_rich must DEGRADE attachments to text, not drop them.

Sendblue is the DEFAULT (kill-switch) provider, and send_reply runs parse_rich on
EVERY reply — so a reply containing a bare image-extension URL (or markdown image)
becomes an ImagePart. The old send_rich returned ok=False for Image/File/Voice,
SILENTLY DROPPING the URL — a regression vs the pre-rich plain-text send. The fix
degrades Image/File/Voice to their .src via send_message (iMessage auto-unfurls a
URL). Poll stays a numbered list; Reaction stays a logged no-op.

Network-free: a recording fake client mirrors the existing sendblue tests' shape.
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


class RecordingClient:
    """Records every send_message(to_number=, content=) call (mirrors MagicMock shape)."""

    def __init__(self):
        self.sent = []  # list of (to_number, content)

    def send_message(self, *, to_number, content):
        self.sent.append((to_number, content))
        return {"message_handle": "h1"}


def _ch():
    client = RecordingClient()
    return SendblueChannel(client), client


# ---- the B1/B3 regression: a bare image URL must NOT be dropped ---------------

def test_image_url_from_parse_rich_is_delivered_not_dropped():
    url = "https://cdn.example.com/cat.png"
    parts = parse_rich(f"here you go {url}")
    img = next(p for p in parts if isinstance(p, ImagePart))  # parse_rich made an ImagePart

    ch, client = _ch()
    res = ch.send_rich(ADDR, img)

    assert res.ok is True
    assert len(client.sent) == 1
    to_number, content = client.sent[0]
    assert to_number == ADDR
    assert url in content  # the URL survived (iMessage auto-unfurls it)


def test_markdown_image_part_src_is_delivered():
    ch, client = _ch()
    res = ch.send_rich(ADDR, ImagePart("https://x.io/a.jpg"))
    assert res.ok is True
    assert client.sent[0][1] == "https://x.io/a.jpg"


def test_file_part_src_delivered():
    ch, client = _ch()
    res = ch.send_rich(ADDR, FilePart("https://x.io/report.pdf", name="report"))
    assert res.ok is True
    assert "https://x.io/report.pdf" in client.sent[0][1]


def test_voice_part_src_delivered():
    ch, client = _ch()
    res = ch.send_rich(ADDR, VoicePart("https://x.io/clip.m4a"))
    assert res.ok is True
    assert "https://x.io/clip.m4a" in client.sent[0][1]


def test_empty_src_returns_not_ok_and_sends_nothing():
    ch, client = _ch()
    for part in (ImagePart("  "), FilePart(""), VoicePart("")):
        res = ch.send_rich(ADDR, part)
        assert res.ok is False
    assert client.sent == []  # empty src -> nothing on the wire


# ---- unchanged behavior: text / poll / reaction ------------------------------

def test_text_part_uses_send_message():
    ch, client = _ch()
    res = ch.send_rich(ADDR, TextPart("hello there"))
    assert res.ok is True
    assert client.sent[0] == (ADDR, "hello there")


def test_poll_part_still_numbered_text_list():
    ch, client = _ch()
    res = ch.send_rich(ADDR, PollPart("pick one", ("apple", "banana")))
    assert res.ok is True
    assert client.sent[0][1] == "pick one\n1. apple\n2. banana"


def test_reaction_part_is_logged_noop():
    ch, client = _ch()
    res = ch.send_rich(ADDR, ReactionPart("❤️"))
    assert res.ok is False  # Sendblue has no tapback API
    assert client.sent == []  # nothing sent


def test_send_rich_never_raises_when_client_errors():
    class Boom:
        def send_message(self, *, to_number, content):
            raise RuntimeError("sendblue 500")

    ch = SendblueChannel(Boom())
    res = ch.send_rich(ADDR, ImagePart("https://x.io/a.png"))
    assert isinstance(res, OutboundResult)
    assert res.ok is False and "500" in (res.error or "")  # best-effort, swallowed
