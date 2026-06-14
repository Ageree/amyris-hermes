"""Thin Telegram Bot API client (outbound send + typing).

Single send path for ALL Telegram tenants (rate limits are PER BOT TOKEN: ~30/s
global, ~1/s per chat, 429 -> parameters.retry_after). Outbound uses
parse_mode="HTML" with link previews disabled. Two resilience behaviors the
worker relies on:

  * 400 fallback: a malformed-HTML send (the model emitted something render_html
    didn't fully normalize) retries ONCE as plain text (no parse_mode) so the user
    always gets the answer.
  * 429 backoff: honor `parameters.retry_after` with ONE bounded retry.

NOTE: HTTP wiring lives here; the live round-trip + Bot API 10.1 conformance are
exercised in M3 (the Telegram milestone). Network failures raise — the
TelegramChannel adapter swallows them into a best-effort OutboundResult.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

log = logging.getLogger("worker.channels.telegram.client")

DEFAULT_BASE = "https://api.telegram.org"
MAX_RETRY_AFTER = 10.0  # cap a 429 backoff so a hostile retry_after can't hang the loop


class TelegramClient:
    """Minimal outbound Telegram client keyed by one bot token."""

    def __init__(self, token: str, *, base_url: str = DEFAULT_BASE, timeout: float = 20.0,
                 sleep_fn=time.sleep):
        if not token:
            raise ValueError("TelegramClient requires a bot token")
        self._token = token
        self._base = f"{base_url}/bot{token}"
        self._timeout = timeout
        self._sleep = sleep_fn

    def _post(self, method: str, payload: dict) -> requests.Response:
        return requests.post(f"{self._base}/{method}", json=payload, timeout=self._timeout)

    def send_message(self, chat_id: str, text: str, *, parse_mode: Optional[str] = "HTML",
                     disable_link_preview: bool = True) -> dict:
        """Send `text` to `chat_id`. HTML by default; falls back to plain on 400.

        429 -> honor a bounded retry_after once. Raises on a non-2xx that is not a
        recoverable 400/429.
        """
        payload: dict = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if disable_link_preview:
            payload["link_preview_options"] = {"is_disabled": True}

        r = self._post("sendMessage", payload)

        if r.status_code == 429:
            retry_after = 1.0
            try:
                retry_after = float(r.json().get("parameters", {}).get("retry_after", 1.0))
            except Exception:
                pass
            self._sleep(min(MAX_RETRY_AFTER, max(0.0, retry_after)))
            r = self._post("sendMessage", payload)

        if r.status_code == 400 and parse_mode:
            # Malformed HTML — retry once as plain text so the answer still lands.
            log.warning("telegram 400 on HTML send to %s; retrying plain: %s", chat_id, r.text[:200])
            plain = {k: v for k, v in payload.items() if k != "parse_mode"}
            r = self._post("sendMessage", plain)

        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"telegram sendMessage failed {r.status_code}: {r.text[:300]}")
        return r.json()

    def send_chat_action(self, chat_id: str, action: str = "typing") -> dict:
        """Fire a chat action (the "typing…" indicator). Best-effort by nature."""
        r = self._post("sendChatAction", {"chat_id": chat_id, "action": action})
        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"telegram sendChatAction failed {r.status_code}: {r.text[:200]}")
        return r.json()
