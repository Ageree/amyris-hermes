"""Photon inbound consumer — producer↔consumer contract test (B4).

Feeds REAL-shaped sidecar ``/inbound`` NDJSON events (the exact JSON
``sidecar/index.mjs::normalizeEvent`` emits) through PhotonInboundConsumer with a
FAKE convex client + a fake binding resolver, and asserts:

  * a text DM resolves the sender → enqueues with the right args
    (channel=imessage, replyTarget=sender, body=text, provider_message_id carried);
  * a repeated messageId is dropped by the bounded LRU dedup (gRPC at-least-once);
  * an unknown sender (no verified binding) is logged + skipped (NO enqueue);
  * an inbound attachment becomes a text note "(sent an image)" + the cached path;
  * a reaction event is skipped (v1: reactions are not enqueued messages);
  * a malformed line / missing messageId / heartbeat never enqueue and never raise.

This is the seam test the repo's producer↔consumer gotcha demands: the FAKE here
mirrors the REAL ``messages:enqueuePhotonInbound`` contract (resolve binding →
``{enqueued, userId}``), so a drift between the Python args and the Convex
mutation's arg names would fail HERE, not only in a live e2e.

Run: cd lab && python -m pytest tests/test_photon_inbound.py -q
"""
from __future__ import annotations

import json

import pytest

from photon_inbound import InboundBody, PhotonInboundConsumer, map_event_to_body


# --- A fake Convex client that mirrors messages:enqueuePhotonInbound ---------


class FakeConvex:
    """Records mutation calls; resolves a fixed set of (address → userId) bindings.

    Mirrors the REAL mutation: an address with a verified binding returns
    {enqueued: True, userId}; an unknown address returns {enqueued: False,
    userId: None} (and does NOT record a queued row). This is the producer side
    of the contract — if the consumer sends the wrong arg names, the assertions
    on .calls break.
    """

    def __init__(self, bindings: dict[str, str]):
        self._bindings = dict(bindings)
        self.calls: list[dict] = []
        self.enqueued: list[dict] = []

    def mutation(self, path: str, args: dict):
        assert path == "messages:enqueuePhotonInbound", f"unexpected path {path}"
        self.calls.append(args)
        addr = args.get("address")
        user = self._bindings.get(addr)
        if user is None:
            return {"enqueued": False, "userId": None}
        self.enqueued.append(args)
        return {"enqueued": True, "userId": user}


def _consumer(bindings: dict[str, str], **kw) -> tuple[PhotonInboundConsumer, FakeConvex]:
    convex = FakeConvex(bindings)
    consumer = PhotonInboundConsumer(
        convex,
        "test-worker-secret",
        sidecar_url="http://127.0.0.1:8789",
        sidecar_token="tok",
        **kw,
    )
    return consumer, convex


# Real sidecar event shapes (from index.mjs::normalizeEvent) -------------------


def _text_event(message_id: str, sender: str, text: str) -> str:
    return json.dumps(
        {
            "messageId": message_id,
            "platform": "iMessage",
            "space": {"id": f"any;-;{sender}", "type": "dm", "phone": sender},
            "sender": {"id": sender},
            "content": {"type": "text", "text": text},
            "timestamp": "2026-06-20T19:06:32.000Z",
        }
    )


def _attachment_event(message_id: str, sender: str, *, mime: str, path: str | None) -> str:
    content: dict = {
        "type": "attachment",
        "id": "att-1",
        "name": "pic.jpg",
        "mimeType": mime,
        "size": 12345,
    }
    if path:
        content["path"] = path
    return json.dumps(
        {
            "messageId": message_id,
            "platform": "iMessage",
            "space": {"id": f"any;-;{sender}", "type": "dm", "phone": sender},
            "sender": {"id": sender},
            "content": content,
            "timestamp": "2026-06-20T19:06:32.000Z",
        }
    )


def _reaction_event(message_id: str, sender: str) -> str:
    return json.dumps(
        {
            "messageId": message_id,
            "platform": "iMessage",
            "space": {"id": f"any;-;{sender}", "type": "dm", "phone": sender},
            "sender": {"id": sender},
            "content": {
                "type": "reaction",
                "emoji": "❤️",
                "targetMessageId": "m-prev",
                "targetDirection": "outbound",
            },
            "timestamp": "2026-06-20T19:06:32.000Z",
        }
    )


# --- map_event_to_body (the pure mapper) -------------------------------------


def test_map_text():
    body = map_event_to_body(json.loads(_text_event("m1", "+15551234567", "  hi there  ")))
    assert body == InboundBody(text="hi there", media_url=None, skip=False)


def test_map_empty_text_is_skipped():
    body = map_event_to_body(json.loads(_text_event("m1", "+1555", "   ")))
    assert body.skip is True


def test_map_image_attachment_note_and_path():
    ev = json.loads(_attachment_event("m1", "+1555", mime="image/jpeg", path="/tmp/pic.jpg"))
    body = map_event_to_body(ev)
    assert body.text == "(sent an image)"
    assert body.media_url == "/tmp/pic.jpg"
    assert body.skip is False


def test_map_non_image_attachment_note():
    ev = json.loads(_attachment_event("m1", "+1555", mime="application/pdf", path=None))
    body = map_event_to_body(ev)
    assert body.text == "(sent a file)"
    assert body.media_url is None


def test_map_voice_note():
    ev = json.loads(
        json.dumps(
            {
                "messageId": "m1",
                "content": {"type": "voice", "mimeType": "audio/mp4", "duration": 3},
            }
        )
    )
    assert map_event_to_body(ev).text == "(sent a voice note)"


def test_map_reaction_is_skipped():
    body = map_event_to_body(json.loads(_reaction_event("m1", "+1555")))
    assert body.skip is True


def test_map_group_merges_text():
    ev = {
        "messageId": "m1",
        "content": {
            "type": "group",
            "items": [
                {"id": "a", "content": {"type": "text", "text": "look"}},
                {"id": "b", "content": {"type": "attachment", "mimeType": "image/png",
                                        "path": "/tmp/x.png"}},
            ],
        },
    }
    body = map_event_to_body(ev)
    assert "look" in body.text and "(sent an image)" in body.text
    assert body.media_url == "/tmp/x.png"


# --- consumer.handle_line (the routing + dedup + enqueue contract) -----------


def test_known_sender_text_enqueues_with_contract_args():
    sender = "+15551234567"
    consumer, convex = _consumer({sender: "user_abc"})
    outcome = consumer.handle_line(_text_event("m1", sender, "hello"))
    assert outcome == "enqueued"
    assert len(convex.enqueued) == 1
    call = convex.enqueued[0]
    # The producer↔consumer contract: exact arg names the Convex mutation expects.
    assert call["workerSecret"] == "test-worker-secret"
    assert call["providerMessageId"] == "m1"  # carried so reactions can target it later
    assert call["address"] == sender          # replyTarget=sender resolved server-side
    assert call["text"] == "hello"
    assert "mediaUrl" not in call             # omitted when no media


def test_duplicate_message_id_is_dropped():
    sender = "+15551234567"
    consumer, convex = _consumer({sender: "user_abc"})
    assert consumer.handle_line(_text_event("dup-id", sender, "first")) == "enqueued"
    # gRPC at-least-once / sidecar reconnect replay: same messageId again.
    assert consumer.handle_line(_text_event("dup-id", sender, "first")) == "dup"
    assert len(convex.enqueued) == 1  # enqueued exactly once


def test_unknown_sender_is_skipped_no_enqueue():
    consumer, convex = _consumer({"+19990000000": "user_known"})
    outcome = consumer.handle_line(_text_event("m1", "+15550000000", "hi stranger"))
    assert outcome == "unknown-sender"
    # The mutation WAS called (server-side resolution), but it enqueued nothing.
    assert len(convex.calls) == 1
    assert convex.enqueued == []


def test_attachment_enqueues_note_and_media_url():
    sender = "+15551234567"
    consumer, convex = _consumer({sender: "user_abc"})
    outcome = consumer.handle_line(
        _attachment_event("m1", sender, mime="image/jpeg", path="/tmp/pic.jpg")
    )
    assert outcome == "enqueued"
    call = convex.enqueued[0]
    assert call["text"] == "(sent an image)"
    assert call["mediaUrl"] == "/tmp/pic.jpg"


def test_reaction_event_is_skipped_no_enqueue():
    sender = "+15551234567"
    consumer, convex = _consumer({sender: "user_abc"})
    assert consumer.handle_line(_reaction_event("m1", sender)) == "skip"
    assert convex.calls == []


def test_heartbeat_and_malformed_lines_never_enqueue_or_raise():
    consumer, convex = _consumer({"+1555": "user_abc"})
    assert consumer.handle_line("") == "heartbeat"
    assert consumer.handle_line("   ") == "heartbeat"
    assert consumer.handle_line("not json {") == "bad-json"
    assert consumer.handle_line(json.dumps([1, 2, 3])) == "bad-json"
    # Valid JSON but no messageId.
    assert consumer.handle_line(json.dumps({"content": {"type": "text", "text": "x"}})) == "no-id"
    assert convex.calls == []


def test_event_without_sender_is_skipped():
    consumer, convex = _consumer({"+1555": "user_abc"})
    ev = json.dumps(
        {"messageId": "m1", "space": {}, "sender": {},
         "content": {"type": "text", "text": "orphan"}}
    )
    assert consumer.handle_line(ev) == "no-sender"
    assert convex.calls == []


def test_enqueue_exception_is_caught_not_raised():
    sender = "+15551234567"

    class Boom:
        def mutation(self, *a, **k):
            raise RuntimeError("convex down")

    consumer = PhotonInboundConsumer(
        Boom(), "secret", sidecar_url="http://x", sidecar_token="t"
    )
    # Best-effort: a transient enqueue failure is logged, returns "error", no raise.
    assert consumer.handle_line(_text_event("m1", sender, "hi")) == "error"


def test_sender_falls_back_to_space_phone_then_id():
    # sender.id missing → space.phone; both missing → space.id.
    ev_phone = json.dumps(
        {"messageId": "m1", "sender": {}, "space": {"phone": "+1777", "id": "g"},
         "content": {"type": "text", "text": "x"}}
    )
    consumer, convex = _consumer({"+1777": "u"})
    assert consumer.handle_line(ev_phone) == "enqueued"
    assert convex.enqueued[0]["address"] == "+1777"


def test_constructor_validates_required_args():
    with pytest.raises(ValueError):
        PhotonInboundConsumer(FakeConvex({}), "", sidecar_url="http://x", sidecar_token="t")
    with pytest.raises(ValueError):
        PhotonInboundConsumer(FakeConvex({}), "s", sidecar_url="", sidecar_token="t")
