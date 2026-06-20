"""Photon (iMessage) inbound consumer — gRPC stream → durable Convex queue.

Photon inbound does NOT arrive over an HTTP webhook (like Sendblue/Telegram); it
flows over the Spectrum gRPC stream that the Hermes-shipped sidecar owns. The
sidecar (plugins/platforms/photon/sidecar/index.mjs, reused under
lab/photon-sidecar/) re-serializes each message to a normalized JSON event and
streams it to ONE consumer over a loopback ``GET /inbound`` (NDJSON, bearer
token). This module is that consumer.

Topology (design §"Deployment topology"): a single sidecar + a single consumer
per PROJECT (the project stream already carries every sender), co-located with
the shared bridge worker. The consumer is the iMessage analogue of the http.ts
``/sendblue/inbound`` webhook: it resolves the sender phone → tenant via the
VERIFIED channelBindings and ENQUEUES (durable) so the existing claim → worker →
bridge → ``hermes chat`` path is reused unchanged.

What it does per inbound line:
  1. parse the NDJSON event (sidecar shape — see ``map_event_to_body``);
  2. dedup on ``messageId`` (the gRPC stream is at-least-once; a sidecar reconnect
     replays) via a bounded LRU — the cheap process-local first guard; Convex's
     ``by_channel_handle`` is the durable second guard;
  3. skip reaction events (v1: reactions are a channel-layer concern that targets
     ``last_inbound`` later — they are not enqueued as messages);
  4. resolve sender → enqueue via ``messages:enqueuePhotonInbound`` (server-side
     binding lookup + ``enqueueImpl``); unknown sender → log + skip (no enqueue).

Best-effort throughout: a single bad line or a transient enqueue failure is
logged and never kills the always-on loop. Modeled on ``adapter.py::_inbound_loop``.

``ponytail:`` the in-process dedup is bounded-LRU (BoundedDedup, default 2000
ids); ceiling = a burst of >2000 unique ids inside a single reconnect-replay
window could re-admit an evicted id, but Convex's by_channel_handle dedup catches
that durably — raise the LRU size if replay windows ever exceed it.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests

from _dedup import BoundedDedup

log = logging.getLogger("photon.inbound")

# A reaction is not an enqueued message (v1) — it targets last_inbound in the
# channel layer. Everything else with a body becomes a queued tenant row.
_REACTION_TYPE = "reaction"


@dataclass(frozen=True)
class InboundBody:
    """The text body extracted from a Photon inbound event (immutable).

    ``media_url`` is the locally-cached path or remote url the sidecar inlined,
    when present (v1 does NOT block on media ingestion — it just carries the path
    so a downstream turn can use it). ``skip`` marks events we never enqueue
    (reactions, empty/unknown content).
    """

    text: str
    media_url: Optional[str] = None
    skip: bool = False


# Attachment/voice → a short text note so the assistant knows media arrived,
# without blocking on media ingestion (design §"Inbound attachments"). The cached
# path/url (if the sidecar inlined one) rides along in `media_url`.
_ATTACHMENT_NOTE = "(sent a file)"
_IMAGE_NOTE = "(sent an image)"
_VOICE_NOTE = "(sent a voice note)"


def map_event_to_body(event: dict[str, Any]) -> InboundBody:
    """Pure mapper: a sidecar inbound event → the body to enqueue (or skip).

    Event shape (from ``sidecar/index.mjs::normalizeEvent``)::

        {
          "messageId": "...",
          "platform": "iMessage",
          "space": {"id": "...", "type": "dm"|"group", "phone": "+E164"},
          "sender": {"id": "+E164"},
          "content": {"type": "text", "text": "..."}
                   | {"type": "attachment"|"voice", "id", "name", "mimeType",
                      "size", "duration"?, "data"?, "encoding"?, "path"?, "url"?}
                   | {"type": "reaction", "emoji", "targetMessageId", ...}
                   | {"type": "group", "items": [{"id", "content": {...}}]},
          "timestamp": "2026-05-14T19:06:32.000Z"
        }

    The sidecar base64-inlines binary bytes as ``content.data``; v1 does NOT
    decode/cache them here — it only surfaces a text note + any path/url the
    sidecar already resolved (``content.path`` / ``content.url``). Reactions and
    empty/unknown content return ``skip=True``.
    """
    content = event.get("content") or {}
    if not isinstance(content, dict):
        return InboundBody(text="", skip=True)
    ctype = content.get("type")

    if ctype == "text":
        text = (content.get("text") or "").strip()
        return InboundBody(text=text, skip=not text)

    if ctype in {"attachment", "voice"}:
        return _binary_body(content)

    if ctype == "group":
        parts: list[str] = []
        media_url: Optional[str] = None
        for item in content.get("items") or []:
            if not isinstance(item, dict):
                continue
            inner = map_event_to_body({"content": item.get("content")})
            if inner.skip and not inner.text:
                continue
            if inner.text:
                parts.append(inner.text)
            if media_url is None and inner.media_url:
                media_url = inner.media_url
        text = "\n".join(p for p in parts if p).strip()
        return InboundBody(text=text, media_url=media_url, skip=not text)

    # reaction (v1: not enqueued) + any unknown content type → skip.
    return InboundBody(text="", skip=True)


def _binary_body(content: dict[str, Any]) -> InboundBody:
    """Map an attachment/voice payload to a text note + any cached path/url."""
    is_voice = content.get("type") == "voice"
    mime = (content.get("mimeType") or "").lower()
    if is_voice:
        note = _VOICE_NOTE
    elif mime.startswith("image/"):
        note = _IMAGE_NOTE
    else:
        note = _ATTACHMENT_NOTE
    # The sidecar may already expose a resolved local path / remote url; carry it
    # so a downstream turn can fetch it. Do NOT inline base64 bytes into the queue.
    raw_path = content.get("path") or content.get("url")
    media_url = str(raw_path) if isinstance(raw_path, str) and raw_path else None
    return InboundBody(text=note, media_url=media_url)


# Default reply/dispatch resolver: enqueue via the worker-secret-gated mutation
# that resolves the binding server-side and inserts the durable row. Kept as a
# tiny callable so tests inject a fake convex client + fake resolver behavior
# (the producer↔consumer contract test feeds REAL sidecar event shapes through).
def _default_enqueue(
    convex: Any, worker_secret: str, *, provider_message_id: str, address: str,
    text: str, media_url: Optional[str],
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "workerSecret": worker_secret,
        "providerMessageId": provider_message_id,
        "address": address,
        "text": text,
    }
    if media_url:
        args["mediaUrl"] = media_url
    return convex.mutation("messages:enqueuePhotonInbound", args) or {}


class PhotonInboundConsumer:
    """Singleton loop: sidecar ``/inbound`` NDJSON → resolve sender → Convex enqueue.

    One instance per project (the project gRPC stream carries every sender). It
    owns ONLY routing: dedup + content-mapping + the enqueue call. The sidecar
    owns the gRPC reconnect/heartbeat; this loop just re-opens the loopback HTTP
    stream when it drops.
    """

    def __init__(
        self,
        convex: Any,
        worker_secret: str,
        *,
        sidecar_url: str,
        sidecar_token: str,
        dedup_maxsize: int = 2000,
        enqueue_fn: Callable[..., dict[str, Any]] = _default_enqueue,
        max_backoff: float = 30.0,
    ) -> None:
        if not worker_secret:
            raise ValueError("PhotonInboundConsumer requires a worker_secret")
        if not sidecar_url:
            raise ValueError("PhotonInboundConsumer requires a sidecar_url")
        self._convex = convex
        self._worker_secret = worker_secret
        self._inbound_url = sidecar_url.rstrip("/") + "/inbound"
        self._headers = {"X-Hermes-Sidecar-Token": sidecar_token}
        self._dedup = BoundedDedup(dedup_maxsize)
        self._enqueue_fn = enqueue_fn
        self._max_backoff = max_backoff
        self._running = False

    # -- per-line handling (pure of I/O except the enqueue call) -----------

    def handle_line(self, line: str) -> Optional[str]:
        """Process one NDJSON line. Returns an outcome tag (for tests/logs).

        Outcomes: "heartbeat" | "bad-json" | "dup" | "skip" | "no-id" |
        "no-sender" | "unknown-sender" | "enqueued" | "error". Never raises — a
        bad line must not break the stream loop.
        """
        line = (line or "").strip()
        if not line:
            return "heartbeat"
        import json

        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            log.debug("photon inbound: skipping non-JSON line")
            return "bad-json"
        if not isinstance(event, dict):
            return "bad-json"

        msg_id = event.get("messageId")
        if not msg_id or not isinstance(msg_id, str):
            log.debug("photon inbound: event missing messageId — skipping")
            return "no-id"
        # Process-local dedup FIRST (cheap). Convex by_channel_handle is the
        # durable backstop if an evicted id ever replays.
        if not self._dedup.add(msg_id):
            return "dup"

        body = map_event_to_body(event)
        if body.skip:
            return "skip"

        address = self._sender_address(event)
        if not address:
            log.warning("photon inbound: event %s has no sender address — skipping", msg_id)
            return "no-sender"

        try:
            res = self._enqueue_fn(
                self._convex,
                self._worker_secret,
                provider_message_id=msg_id,
                address=address,
                text=body.text,
                media_url=body.media_url,
            )
        except Exception as e:  # best-effort: never kill the loop on a transient enqueue error
            log.warning("photon inbound: enqueue failed for %s: %s", msg_id, e)
            return "error"

        if not res.get("enqueued"):
            # Unknown sender (no verified binding) — log + skip per v1 policy
            # (no enqueue, no budget burn). Matches http.ts unknown-sender drop.
            log.info("photon inbound: unknown sender %s (no binding) — skipping", address)
            return "unknown-sender"
        return "enqueued"

    @staticmethod
    def _sender_address(event: dict[str, Any]) -> str:
        """E.164 sender phone: sender.id, else space.phone, else space.id."""
        sender = event.get("sender") or {}
        space = event.get("space") or {}
        addr = (
            (sender.get("id") if isinstance(sender, dict) else None)
            or (space.get("phone") if isinstance(space, dict) else None)
            or (space.get("id") if isinstance(space, dict) else None)
            or ""
        )
        return str(addr).strip()

    # -- the always-on stream loop ----------------------------------------

    def run_forever(self) -> None:
        """Open the sidecar ``/inbound`` stream and process lines, with reconnect.

        Blocks. The sidecar owns gRPC reconnects; here we only re-open the local
        HTTP stream on drop, with capped exponential backoff.
        """
        self._running = True
        backoff = 1.0
        while self._running:
            try:
                with requests.get(
                    self._inbound_url, headers=self._headers, stream=True, timeout=None
                ) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"/inbound returned {resp.status_code}")
                    backoff = 1.0  # reset on a clean connect
                    for line in resp.iter_lines(decode_unicode=True):
                        if not self._running:
                            break
                        self.handle_line(line if line is not None else "")
            except Exception as e:
                if not self._running:
                    break
                log.warning(
                    "photon inbound: stream dropped (%s); reconnecting in %.1fs", e, backoff
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)

    def stop(self) -> None:
        self._running = False
