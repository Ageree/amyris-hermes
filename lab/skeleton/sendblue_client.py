"""Thin Sendblue iMessage client (outbound send + inbound parsing).

Throwaway spike for the Phase-1A walking skeleton — P1C supersedes it with the
real TS/Convex router. Verified Sendblue facts (docs.sendblue.com, 2026-06-20):
  - Base https://api.sendblue.co/api ; auth headers sb-api-key-id / sb-api-secret-key
  - Send: POST /send-message with JSON {number, from_number, content?, media_url?}.
    `media_url` is a public http(s) URL — image/file attachment, OR a voice note
    (Apple renders a native voice bubble only for .caf; other audio arrives as an
    audio attachment). `content` is optional when `media_url` is present.
  - Reaction (tapback): POST /send-reaction with JSON
    {from_number, message_handle, reaction}. `reaction` ∈
    love|like|dislike|laugh|emphasize|question; `message_handle` is the inbound
    message's Apple GUID (from the inbound webhook). iMessage-only.
  - Typing indicator: POST /send-typing-indicator with JSON
    {from_number, number, state:"start"|"stop", max_duration_ms?}. iMessage-only;
    best-effort (a 200 "SENT" does NOT guarantee delivery if the chat is stale).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

SENDBLUE_BASE = "https://api.sendblue.co/api"


class SendblueClient:
    """Minimal outbound Sendblue client. Raises on missing creds / non-2xx."""

    def __init__(self, key_id: str, secret: str, from_number: str, timeout: float = 20.0):
        if not key_id or not secret or not from_number:
            raise ValueError("SendblueClient requires key_id, secret, from_number")
        self._headers = {
            "sb-api-key-id": key_id,
            "sb-api-secret-key": secret,
            "Content-Type": "application/json",
        }
        self._from = from_number
        self._timeout = timeout

    def send_message(
        self, to_number: str, content: str = "", *, media_url: Optional[str] = None
    ) -> dict:
        """Send a text and/or a media attachment. At least one of content/media_url.

        `media_url` (a public http(s) URL) delivers an image/file/voice attachment;
        when present `content` may be empty (a media-only bubble, e.g. a voice note).
        """
        if not to_number:
            raise ValueError("to_number is required")
        if not content and not media_url:
            raise ValueError("content or media_url is required")
        payload = {"number": to_number, "from_number": self._from}
        if content:
            payload["content"] = content
        if media_url:
            payload["media_url"] = media_url
        r = requests.post(
            f"{SENDBLUE_BASE}/send-message",
            json=payload,
            headers=self._headers,
            timeout=self._timeout,
        )
        if not (200 <= r.status_code < 300):
            raise RuntimeError(
                f"Sendblue send-message failed {r.status_code}: {r.text[:300]}"
            )
        return r.json()

    def send_reaction(self, *, message_handle: str, reaction: str) -> dict:
        """Send an iMessage tapback to a prior inbound message (by its Apple GUID).

        `reaction` must be one of love|like|dislike|laugh|emphasize|question (the
        fixed iMessage tapback set). Best-effort like every iMessage write — a
        stale/too-old target may not accept it; callers treat failures as non-fatal.
        """
        if not message_handle or not reaction:
            raise ValueError("message_handle and reaction are required")
        payload = {
            "from_number": self._from,
            "message_handle": message_handle,
            "reaction": reaction,
        }
        r = requests.post(
            f"{SENDBLUE_BASE}/send-reaction",
            json=payload,
            headers=self._headers,
            timeout=self._timeout,
        )
        if not (200 <= r.status_code < 300):
            raise RuntimeError(
                f"Sendblue send-reaction failed {r.status_code}: {r.text[:300]}"
            )
        return r.json()

    def send_typing(
        self,
        to_number: str,
        *,
        state: str = "start",
        max_duration_ms: Optional[int] = None,
    ) -> dict:
        """Fire an iMessage typing indicator (the "…" bubble) at `to_number`.

        state="start" shows it; state="stop" clears it. `max_duration_ms` is an
        optional auto-expiry hint (Sendblue's documented expiry is otherwise
        unspecified — the worker re-fires on a timer well inside this window).

        Best-effort by nature (iMessage-only; a stale chat still returns 200
        "SENT" without delivering) — callers MUST treat failures as non-fatal and
        never let a typing error block the actual reply.
        """
        if not to_number:
            raise ValueError("to_number is required")
        if state not in ("start", "stop"):
            raise ValueError("state must be 'start' or 'stop'")
        payload: dict = {"from_number": self._from, "number": to_number, "state": state}
        if max_duration_ms is not None:
            payload["max_duration_ms"] = int(max_duration_ms)
        r = requests.post(
            f"{SENDBLUE_BASE}/send-typing-indicator",
            json=payload,
            headers=self._headers,
            timeout=self._timeout,
        )
        if not (200 <= r.status_code < 300):
            raise RuntimeError(
                f"Sendblue send-typing-indicator failed {r.status_code}: {r.text[:300]}"
            )
        return r.json()


@dataclass(frozen=True)
class InboundMessage:
    """Normalized, validated Sendblue inbound webhook event."""

    text: str
    user_number: str  # Sendblue `number` — the end-user to reply to
    handle: str  # `message_handle` — idempotency key
    media_url: str
    opted_out: bool


def parse_inbound(payload: dict) -> Optional[InboundMessage]:
    """Validate + normalize a Sendblue inbound webhook.

    Returns None for anything we must ignore (outbound echo, opted-out, empty
    text/number). Never trust external data — validate at the boundary.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("is_outbound") is True:
        return None
    if payload.get("opted_out") is True:
        return None
    text = (payload.get("content") or "").strip()
    user_number = (payload.get("number") or "").strip()
    if not text or not user_number:
        return None
    return InboundMessage(
        text=text,
        user_number=user_number,
        handle=str(payload.get("message_handle") or ""),
        media_url=payload.get("media_url") or "",
        opted_out=False,
    )
