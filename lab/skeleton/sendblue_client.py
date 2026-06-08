"""Thin Sendblue iMessage client (outbound send + inbound parsing).

Throwaway spike for the Phase-1A walking skeleton — P1C supersedes it with the
real TS/Convex router. Verified Sendblue facts (docs 2026-06-08):
  - Base https://api.sendblue.co/api ; auth headers sb-api-key-id / sb-api-secret-key
  - Send: POST /send-message with JSON {number, from_number, content}
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

    def send_message(self, to_number: str, content: str) -> dict:
        if not to_number or not content:
            raise ValueError("to_number and content are required")
        payload = {"number": to_number, "from_number": self._from, "content": content}
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
