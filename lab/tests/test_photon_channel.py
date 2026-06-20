"""Unit tests for PhotonChannel — the iMessage rich transport (Photon sidecar).

The HTTP wire is FAKED via the injected `poster` (no real sidecar, no network):
each test asserts the method hit the right sidecar route with the right payload,
and that every send is best-effort (returns OutboundResult, never raises).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skeleton"))

from channels.base import Channel, OutboundResult  # noqa: E402
from channels.photon_channel import (  # noqa: E402
    PhotonChannel,
    _is_remote,
    _poll_to_text,
    _port_from_base,
)
from channels.rich import (  # noqa: E402
    FilePart,
    ImagePart,
    PollPart,
    ReactionPart,
    TextPart,
    VoicePart,
)

BASE = "http://127.0.0.1:8790"
BEARER = "tok-abc"
ADDR = "+15551234567"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True, "messageId": "m1"}
        self.text = text

    def json(self):
        return self._payload


class FakePoster:
    """Records every POST and returns a scripted/queued FakeResponse."""

    def __init__(self, response=None, responses=None):
        self.calls = []  # list of dicts: {url, json, headers, timeout}
        self._fixed = response
        self._queue = list(responses) if responses else None

    def __call__(self, url, *, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self._queue is not None:
            return self._queue.pop(0)
        if self._fixed is not None:
            return self._fixed
        return FakeResponse()

    @property
    def last(self):
        return self.calls[-1]


class FakeHead:
    """Records every HEAD and returns a scripted Content-Type (or raises).

    Mirrors FakePoster's inject-the-wire style: `content_type` is returned in a
    fake response's headers; `raises` simulates a HEAD timeout/failure.
    """

    def __init__(self, content_type=None, raises=None):
        self.calls = []  # list of (url,) seen
        self._content_type = content_type
        self._raises = raises

    def __call__(self, url, *, timeout):
        self.calls.append(url)
        if self._raises is not None:
            raise self._raises
        headers = {"Content-Type": self._content_type} if self._content_type is not None else {}
        return type("FakeHeadResponse", (), {"headers": headers})()


def make_channel(poster, head_fn=None):
    # Default head_fn raises → no concrete MIME → no mimeType added. Keeps the
    # existing attachment tests hermetic (no real network HEAD) and byte-identical
    # to pre-sniff behavior. Tests that exercise sniffing pass an explicit FakeHead.
    return PhotonChannel(
        sidecar_base=BASE,
        bearer=BEARER,
        project_id="pid",
        project_secret="psecret",
        poster=poster,
        head_fn=head_fn or FakeHead(raises=ConnectionError("no net in tests")),
    )


# -- Protocol conformance ----------------------------------------------------


def test_satisfies_channel_protocol():
    ch = make_channel(FakePoster())
    assert isinstance(ch, Channel)
    assert ch.kind == "imessage"


def test_secrets_come_from_args_not_literals():
    # Sanity: no hardcoded creds — they are exactly what we passed in.
    ch = make_channel(FakePoster())
    assert ch._project_id == "pid" and ch._project_secret == "psecret"
    assert ch._bearer == BEARER


# -- send_message ------------------------------------------------------------


def test_send_message_hits_send_route_with_bearer():
    poster = FakePoster(FakeResponse(payload={"ok": True, "messageId": "abc"}))
    ch = make_channel(poster)
    res = ch.send_message(ADDR, "hello there")
    assert res == OutboundResult(ok=True, provider_id="abc")
    assert poster.last["url"] == f"{BASE}/send"
    assert poster.last["json"] == {
        "spaceId": ADDR, "text": "hello there", "format": "markdown",
    }
    assert poster.last["headers"]["X-Hermes-Sidecar-Token"] == BEARER


def test_send_message_tags_format_markdown():
    # SP2: markdown must reach the sidecar so it renders (degrades to plain
    # elsewhere) instead of being shown as literal text.
    poster = FakePoster()
    ch = make_channel(poster)
    ch.send_message(ADDR, "**bold** and _italic_")
    assert poster.last["json"]["format"] == "markdown"


def test_send_message_empty_body_short_circuits_without_call():
    poster = FakePoster()
    ch = make_channel(poster)
    res = ch.send_message(ADDR, "   ")
    assert res.ok is False
    assert poster.calls == []  # never touched the wire


def test_send_message_http_error_returns_not_ok_no_raise():
    poster = FakePoster(FakeResponse(status_code=500, text="boom"))
    ch = make_channel(poster)
    res = ch.send_message(ADDR, "hi")
    assert res.ok is False and "500" in (res.error or "")


def test_send_message_sidecar_reported_error_returns_not_ok():
    poster = FakePoster(FakeResponse(payload={"ok": False, "error": "bad space"}))
    ch = make_channel(poster)
    res = ch.send_message(ADDR, "hi")
    assert res.ok is False and "bad space" in (res.error or "")


def test_send_message_transport_exception_returns_not_ok():
    def boom(url, *, json, headers, timeout):
        raise ConnectionError("refused")

    ch = make_channel(boom)
    res = ch.send_message(ADDR, "hi")
    assert res.ok is False and "refused" in (res.error or "")


# -- send_typing -------------------------------------------------------------


def test_send_typing_hits_typing_route():
    poster = FakePoster(FakeResponse(payload={"ok": True}))
    ch = make_channel(poster)
    res = ch.send_typing(ADDR, state="start")
    assert res.ok is True
    assert poster.last["url"] == f"{BASE}/typing"
    assert poster.last["json"] == {"spaceId": ADDR, "state": "start"}


def test_send_typing_failure_is_best_effort():
    ch = make_channel(FakePoster(FakeResponse(status_code=400, text="nope")))
    res = ch.send_typing(ADDR, state="stop")
    assert res.ok is False  # cosmetic — degrades, never raises


# -- send_rich: text ---------------------------------------------------------


def test_send_rich_text_uses_send_route():
    poster = FakePoster()
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, TextPart("yo"))
    assert res.ok is True
    assert poster.last["url"] == f"{BASE}/send"
    assert poster.last["json"]["text"] == "yo"


# -- send_rich: attachments --------------------------------------------------


def test_send_rich_image_uses_send_attachment_kind_attachment():
    poster = FakePoster()
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, ImagePart("https://x/cat.png"))
    assert res.ok is True
    assert poster.last["url"] == f"{BASE}/send-attachment"
    assert poster.last["json"] == {
        "spaceId": ADDR, "path": "https://x/cat.png", "kind": "attachment",
    }


def test_send_rich_file_includes_name_when_present():
    poster = FakePoster()
    ch = make_channel(poster)
    ch.send_rich(ADDR, FilePart("https://x/report.pdf", name="report.pdf"))
    assert poster.last["json"] == {
        "spaceId": ADDR, "path": "https://x/report.pdf", "kind": "attachment",
        "name": "report.pdf",
    }


def test_send_rich_file_omits_name_when_absent():
    poster = FakePoster()
    ch = make_channel(poster)
    ch.send_rich(ADDR, FilePart("https://x/report.pdf"))
    assert "name" not in poster.last["json"]
    assert poster.last["json"]["kind"] == "attachment"


def test_send_rich_voice_uses_kind_voice():
    poster = FakePoster()
    ch = make_channel(poster)
    ch.send_rich(ADDR, VoicePart("https://x/note.m4a"))
    assert poster.last["url"] == f"{BASE}/send-attachment"
    assert poster.last["json"] == {
        "spaceId": ADDR, "path": "https://x/note.m4a", "kind": "voice",
    }


# -- send_rich: file-exfil guard (non-remote media src refused) ---------------


def test_send_rich_image_local_abs_path_refused_no_call():
    # /etc/passwd would be readFile()'d by the sidecar and texted back — refuse it.
    poster = FakePoster()
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, ImagePart("/etc/passwd"))
    assert res.ok is False and "non-remote" in (res.error or "")
    assert poster.calls == []  # never touched the wire


def test_send_rich_image_relative_path_refused_no_call():
    poster = FakePoster()
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, ImagePart("../x"))
    assert res.ok is False and "non-remote" in (res.error or "")
    assert poster.calls == []


def test_send_rich_file_and_voice_local_path_refused_no_call():
    poster = FakePoster()
    ch = make_channel(poster)
    assert ch.send_rich(ADDR, FilePart("/Users/me/.env")).ok is False
    assert ch.send_rich(ADDR, VoicePart("/tmp/note.m4a")).ok is False
    assert poster.calls == []  # neither reached /send-attachment


def test_send_rich_image_http_url_hits_send_attachment():
    poster = FakePoster()
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, ImagePart("http://x/a.png"))
    assert res.ok is True
    assert poster.last["url"] == f"{BASE}/send-attachment"


# -- send_rich: MIME sniffing for extensionless URLs (the picsum bug) ----------


def test_send_rich_image_extensionless_url_sniffs_mime_from_head():
    # picsum-style: URL ends in '300' (no extension) → spectrum-ts can't infer
    # MIME. We HEAD it, read Content-Type image/png, and pass mimeType so the
    # sidecar overrides its (failed) extension guess.
    poster = FakePoster()
    head = FakeHead(content_type="image/png")
    ch = make_channel(poster, head_fn=head)
    res = ch.send_rich(ADDR, ImagePart("https://picsum.photos/seed/x/400/300"))
    assert res.ok is True
    assert head.calls == ["https://picsum.photos/seed/x/400/300"]  # HEADed the src
    assert poster.last["url"] == f"{BASE}/send-attachment"
    assert poster.last["json"]["mimeType"] == "image/png"
    assert poster.last["json"]["path"] == "https://picsum.photos/seed/x/400/300"


def test_send_rich_image_head_text_html_omits_mime_graceful_fallback():
    # A redirect/error HTML page (text/html) is NOT a media type → omit mimeType
    # and fall back to today's behavior (the send still attempts).
    poster = FakePoster()
    head = FakeHead(content_type="text/html; charset=utf-8")
    ch = make_channel(poster, head_fn=head)
    res = ch.send_rich(ADDR, ImagePart("https://cdn/redirect/300"))
    assert res.ok is True
    assert "mimeType" not in poster.last["json"]
    assert "name" not in poster.last["json"]


def test_send_rich_image_head_strips_mime_params():
    # "image/jpeg; charset=binary" → "image/jpeg" (params stripped).
    poster = FakePoster()
    head = FakeHead(content_type="image/jpeg; charset=binary")
    ch = make_channel(poster, head_fn=head)
    ch.send_rich(ADDR, ImagePart("https://cdn/signed/photo"))
    assert poster.last["json"]["mimeType"] == "image/jpeg"


def test_send_rich_image_head_octet_stream_omits_mime():
    # A useless catch-all → omit, let the sidecar's extension guess stand.
    poster = FakePoster()
    head = FakeHead(content_type="application/octet-stream")
    ch = make_channel(poster, head_fn=head)
    ch.send_rich(ADDR, ImagePart("https://cdn/blob/300"))
    assert "mimeType" not in poster.last["json"]


def test_send_rich_image_head_failure_omits_mime_no_raise():
    # HEAD timeout/refused → best-effort: no mimeType, send still attempts.
    poster = FakePoster()
    head = FakeHead(raises=TimeoutError("head timed out"))
    ch = make_channel(poster, head_fn=head)
    res = ch.send_rich(ADDR, ImagePart("https://cdn/slow/300"))
    assert res.ok is True
    assert "mimeType" not in poster.last["json"]


def test_send_rich_extensionless_url_gets_synthetic_name_with_ext():
    # No extension in the path → attach a sensible name with the MIME's extension.
    poster = FakePoster()
    head = FakeHead(content_type="image/png")
    ch = make_channel(poster, head_fn=head)
    ch.send_rich(ADDR, ImagePart("https://picsum.photos/seed/x/400/300"))
    assert poster.last["json"]["name"] == "attachment.png"


def test_send_rich_image_with_extension_keeps_no_synthetic_name():
    # URL already has an extension → mimeType added, but NO synthetic name (the
    # extension already names it). mimeType is additive.
    poster = FakePoster()
    head = FakeHead(content_type="image/png")
    ch = make_channel(poster, head_fn=head)
    ch.send_rich(ADDR, ImagePart("https://x/cat.png"))
    assert poster.last["json"]["mimeType"] == "image/png"
    assert "name" not in poster.last["json"]


def test_send_rich_file_keeps_caller_name_and_adds_mime():
    # FilePart already has a name → mimeType is additive; the name is NOT dropped
    # or overwritten by the synthetic one.
    poster = FakePoster()
    head = FakeHead(content_type="application/pdf")
    ch = make_channel(poster, head_fn=head)
    ch.send_rich(ADDR, FilePart("https://x/download/abc123", name="report.pdf"))
    assert poster.last["json"]["name"] == "report.pdf"  # caller name preserved
    assert poster.last["json"]["mimeType"] == "application/pdf"


def test_send_rich_voice_extensionless_sniffs_mime_keeps_kind_voice():
    poster = FakePoster()
    head = FakeHead(content_type="audio/mp4")
    ch = make_channel(poster, head_fn=head)
    ch.send_rich(ADDR, VoicePart("https://x/voice/note"))
    assert poster.last["json"]["kind"] == "voice"
    assert poster.last["json"]["mimeType"] == "audio/mp4"


def test_sniff_skips_for_non_remote_guarded_src_no_head():
    # The file-exfil guard short-circuits BEFORE any sniff — a local src must
    # never trigger a HEAD (and must still be refused with no wire call).
    poster = FakePoster()
    head = FakeHead(content_type="image/png")
    ch = make_channel(poster, head_fn=head)
    res = ch.send_rich(ADDR, ImagePart("/etc/passwd"))
    assert res.ok is False and "non-remote" in (res.error or "")
    assert head.calls == []  # guard runs first; never HEADed a local path
    assert poster.calls == []


# -- send_rich: reaction -----------------------------------------------------


def test_send_rich_reaction_hits_react_route_with_reply_to():
    poster = FakePoster(FakeResponse(payload={"ok": True, "reactionId": "r9"}))
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, ReactionPart("❤️"), reply_to="msg-42")
    assert res == OutboundResult(ok=True, provider_id="r9")
    assert poster.last["url"] == f"{BASE}/react"
    assert poster.last["json"] == {"spaceId": ADDR, "messageId": "msg-42", "emoji": "❤️"}


def test_send_rich_reaction_without_reply_to_degrades_no_call_no_raise():
    poster = FakePoster()
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, ReactionPart("\U0001f44d"), reply_to=None)
    assert res.ok is False
    assert "reply_to" in (res.error or "")
    assert poster.calls == []  # never hit /react with no target


# -- send_rich: poll degradation --------------------------------------------


def test_send_rich_poll_degrades_to_numbered_text_via_send():
    poster = FakePoster()
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, PollPart("Lunch?", ("Pizza", "Sushi", "Tacos")))
    assert res.ok is True
    assert poster.last["url"] == f"{BASE}/send"  # NOT a poll route — iMessage has none
    assert poster.last["json"]["text"] == "Lunch?\n1. Pizza\n2. Sushi\n3. Tacos"


def test_send_rich_unsupported_part_returns_not_ok():
    ch = make_channel(FakePoster())
    res = ch.send_rich(ADDR, object())
    assert res.ok is False and "unsupported" in (res.error or "")


def test_send_rich_attachment_failure_returns_not_ok_no_raise():
    poster = FakePoster(FakeResponse(payload={"ok": False, "error": "no such path"}))
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, ImagePart("https://x/missing.png"))
    assert res.ok is False and "no such path" in (res.error or "")


# -- render / split ----------------------------------------------------------


def test_render_strips():
    ch = make_channel(FakePoster())
    assert ch.render("  hi  ") == "hi"


def test_split_reuses_bubbles():
    ch = make_channel(FakePoster())
    out = ch.split("first thought\n\nsecond thought")
    assert out == ["first thought", "second thought"]


# -- helpers -----------------------------------------------------------------


def test_port_from_base():
    assert _port_from_base("http://127.0.0.1:8790") == 8790
    assert _port_from_base("http://localhost:8789/") == 8789
    assert _port_from_base("not-a-url") is None


def test_poll_to_text_numbers_options():
    txt = _poll_to_text(PollPart("Q?", ("a", "b")))
    assert txt == "Q?\n1. a\n2. b"


def test_is_remote_only_http_https():
    assert _is_remote("http://x/a.png") is True
    assert _is_remote("https://x/a.png") is True
    assert _is_remote("/etc/passwd") is False
    assert _is_remote("../x") is False
    assert _is_remote("file:///etc/passwd") is False
    assert _is_remote("ftp://x/a") is False
    assert _is_remote(None) is False  # defensive: non-str src never treated as remote


# Scheme-confusion / whitespace-prefix bypass attempts on the file-exfil guard.
# The guard is an allowlist (exact 'http://'/'https://' prefix), so each of these
# must fail-closed: _is_remote False AND send_rich returns ok=False with NO wire call.
_GUARD_BYPASS_SRCS = [
    "HTTP://evil/x.png",     # uppercase scheme (case-sensitive startswith → refused)
    "Https://evil/x.png",
    "https:/evil/x.png",     # single slash — not the literal 'https://' prefix
    "http:/evil/x.png",
    "  http://evil/x.png",   # leading whitespace before scheme
    "\thttp://evil/x.png",
    "\nhttps://evil/x.png",
    "x http://evil/x.png",   # http present but not at start
    "/etc/http://passwd",    # 'http://' as a substring, not a prefix
    "file:///etc/passwd",
    "javascript:http://x",
]


@pytest.mark.parametrize("src", _GUARD_BYPASS_SRCS)
def test_is_remote_rejects_bypass_vectors(src):
    assert _is_remote(src) is False


@pytest.mark.parametrize("src", _GUARD_BYPASS_SRCS)
@pytest.mark.parametrize("cls", [ImagePart, FilePart, VoicePart])
def test_send_rich_bypass_vectors_refused_no_call(cls, src):
    poster = FakePoster()
    ch = make_channel(poster)
    res = ch.send_rich(ADDR, cls(src))
    assert res.ok is False and "non-remote" in (res.error or "")
    assert poster.calls == []  # guard short-circuits before any sidecar/poster call


# NOTE: the sidecar's `new URL(path)` change for remote media (index.mjs
# /send-attachment, the C1 fix) can't be unit-tested in Python — it's covered by
# the live e2e (real spectrum-ts fetchUrlBytes against a real Photon line).


# -- ensure_sidecar (no real spawn) -----------------------------------------


def test_ensure_sidecar_returns_true_when_already_healthy():
    # /healthz answers 200 → no spawn attempted.
    poster = FakePoster(FakeResponse(payload={"ok": True}))
    ch = make_channel(poster)
    assert ch.ensure_sidecar() is True
    assert poster.last["url"] == f"{BASE}/healthz"


def test_ensure_sidecar_aborts_without_creds_when_unhealthy():
    # Unhealthy + missing project creds → must NOT spawn, returns False.
    def unhealthy(url, *, json, headers, timeout):
        raise ConnectionError("down")

    ch = PhotonChannel(sidecar_base=BASE, bearer=BEARER, poster=unhealthy)  # no creds
    assert ch.ensure_sidecar() is False
    assert ch._proc is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
