"""Telegram channel — adapter over TelegramClient + tg_format.

render() = Markdown-subset -> Bot API HTML; split() = tag-safe chunking within the
4096 limit. Telegram is ONE batch message per reply (no Poke bubbles — the ~1/s
per-chat limit makes streaming counterproductive), so split() yields few chunks.
send_typing("start") fires a sendChatAction; "stop" is a no-op (Telegram's typing
indicator auto-clears ~5s, so there is nothing to clear).

Sends are best-effort: any TelegramClient error becomes OutboundResult(ok=False).
"""
from __future__ import annotations

import logging
from typing import Optional

from channels.base import OutboundResult
from channels.tg_format import render_html, split_html_safe

log = logging.getLogger("worker.channels.telegram")


class TelegramChannel:
    """Outbound Telegram via one bot token. One instance serves all TG tenants."""

    kind = "telegram"

    def __init__(self, client):
        self._client = client

    def render(self, text: str) -> str:
        return render_html(text)

    def split(self, text: str) -> list:
        return split_html_safe(text)

    def send_message(self, address: str, text: str) -> OutboundResult:
        body = text or ""
        if not body.strip():
            return OutboundResult(ok=False, error="empty body")
        try:
            res = self._client.send_message(address, body)
            mid = None
            if isinstance(res, dict):
                mid = str((res.get("result") or {}).get("message_id") or "") or None
            return OutboundResult(ok=True, provider_id=mid)
        except Exception as e:  # best-effort: never raise into the loop
            log.warning("telegram send failed for %s: %s", address, e)
            return OutboundResult(ok=False, error=str(e)[:200])

    def send_typing(
        self, address: str, *, state: str = "start", max_duration_ms: Optional[int] = None
    ) -> OutboundResult:
        # Telegram auto-clears the typing action (~5s) — only "start" does work.
        if state != "start":
            return OutboundResult(ok=True)
        try:
            self._client.send_chat_action(address, "typing")
            return OutboundResult(ok=True)
        except Exception as e:  # cosmetic — never break the reply
            log.debug("telegram typing failed for %s: %s", address, e)
            return OutboundResult(ok=False, error=str(e)[:200])
