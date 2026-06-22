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
                log.debug("429 retry_after parse failed for sendMessage to %s", chat_id, exc_info=True)
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

    # --- Rich media (Bot API 10.1) -------------------------------------------
    # ponytail: media args carry a URL STRING (Telegram fetches it). Local-file
    # multipart upload is a deliberate follow-up — the ceiling is "the model
    # emitted a local path, not a URL"; the upgrade path is a multipart `files=`
    # branch here. send_rich keeps everything else (parse_mode, captions) intact.

    def _send_media(self, method: str, payload: dict) -> dict:
        """Shared send for media methods with the same 400->plain caption fallback.

        A bad-HTML caption (400) retries ONCE with the caption's parse_mode dropped,
        mirroring send_message — the media still lands even if the caption is off.
        Raises on a non-recoverable non-2xx.
        """
        r = self._post(method, payload)

        if r.status_code == 429:
            retry_after = 1.0
            try:
                retry_after = float(r.json().get("parameters", {}).get("retry_after", 1.0))
            except Exception:
                log.debug("429 retry_after parse failed for %s", method, exc_info=True)
            self._sleep(min(MAX_RETRY_AFTER, max(0.0, retry_after)))
            r = self._post(method, payload)

        if r.status_code == 400 and payload.get("parse_mode"):
            log.warning("telegram 400 on %s caption to %s; retrying plain: %s",
                        method, payload.get("chat_id"), r.text[:200])
            plain = {k: v for k, v in payload.items() if k != "parse_mode"}
            r = self._post(method, plain)

        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"telegram {method} failed {r.status_code}: {r.text[:300]}")
        return r.json()

    def send_photo(self, chat_id: str, photo: str, caption: Optional[str] = None,
                   *, parse_mode: Optional[str] = "HTML") -> dict:
        """Send a photo by URL (or file_id). Optional HTML caption with plain fallback."""
        payload: dict = {"chat_id": chat_id, "photo": photo}
        if caption:
            payload["caption"] = caption
            if parse_mode:
                payload["parse_mode"] = parse_mode
        return self._send_media("sendPhoto", payload)

    def send_document(self, chat_id: str, document: str, caption: Optional[str] = None,
                      *, parse_mode: Optional[str] = "HTML") -> dict:
        """Send a document by URL (or file_id). Optional HTML caption with plain fallback."""
        payload: dict = {"chat_id": chat_id, "document": document}
        if caption:
            payload["caption"] = caption
            if parse_mode:
                payload["parse_mode"] = parse_mode
        return self._send_media("sendDocument", payload)

    def send_voice(self, chat_id: str, voice: str) -> dict:
        """Send a voice note by URL (or file_id). No caption parse needed."""
        return self._send_media("sendVoice", {"chat_id": chat_id, "voice": voice})

    def send_poll(self, chat_id: str, question: str, options: list) -> dict:
        """Send a native poll. Bot API 7.0+ wants options as InputPollOption objects."""
        payload = {
            "chat_id": chat_id,
            "question": question,
            "options": [{"text": str(opt)} for opt in options],
        }
        r = self._post("sendPoll", payload)
        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"telegram sendPoll failed {r.status_code}: {r.text[:300]}")
        return r.json()

    # --- Rich Markdown (Bot API 10.1 sendRichMessage) ------------------------
    # The NEW one-shot rich format: a single rich-markdown string (headings,
    # tables, blockquotes, bullet lists, bold/italic, links, code) rendered by
    # Telegram itself — a SUPERSET of the classic markdown the brain emits, so the
    # raw reply text is passed straight through as `rich_message.markdown`.
    # Wire format probed LIVE against api.telegram.org: the field is
    # `rich_message.markdown` (wrong names -> 400 "rich message must be non-empty").

    def send_rich_message(self, chat_id: str, markdown: str, *,
                          reply_markup: Optional[dict] = None) -> dict:
        """POST sendRichMessage with `rich_message.markdown` = `markdown`.

        Mirrors send_message's 429 backoff: honor `parameters.retry_after` with ONE
        bounded retry (capped by MAX_RETRY_AFTER). There is NO 400->plain fallback
        here (rich markdown has no parse_mode to drop) — any non-recoverable non-2xx
        RAISES RuntimeError, same contract as the other client methods (the channel
        layer swallows it into a best-effort result + classic fallback).
        """
        payload: dict = {"chat_id": chat_id, "rich_message": {"markdown": markdown}}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup

        r = self._post("sendRichMessage", payload)

        if r.status_code == 429:
            retry_after = 1.0
            try:
                retry_after = float(r.json().get("parameters", {}).get("retry_after", 1.0))
            except Exception:
                log.debug("429 retry_after parse failed for sendRichMessage to %s", chat_id, exc_info=True)
            self._sleep(min(MAX_RETRY_AFTER, max(0.0, retry_after)))
            r = self._post("sendRichMessage", payload)

        if not (200 <= r.status_code < 300):
            raise RuntimeError(f"telegram sendRichMessage failed {r.status_code}: {r.text[:300]}")
        return r.json()

    def set_message_reaction(self, chat_id: str, message_id, emoji: str) -> dict:
        """Set a single emoji reaction on a message (ReactionType `emoji`)."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
        }
        r = self._post("setMessageReaction", payload)
        if not (200 <= r.status_code < 300):
            raise RuntimeError(
                f"telegram setMessageReaction failed {r.status_code}: {r.text[:300]}"
            )
        return r.json()
