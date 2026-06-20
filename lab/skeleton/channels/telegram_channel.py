"""Telegram channel — adapter over TelegramClient + tg_format.

render() = Markdown-subset -> Bot API HTML; split() = tag-safe chunking within the
4096 limit. Telegram is ONE batch message per reply (no Poke bubbles — the ~1/s
per-chat limit makes streaming counterproductive), so split() yields few chunks.
send_typing("start") fires a sendChatAction; "stop" is a no-op (Telegram's typing
indicator auto-clears ~5s, so there is nothing to clear).

Sends are best-effort: any TelegramClient error becomes OutboundResult(ok=False).

RICH MARKDOWN (Bot API 10.1 sendRichMessage): when enabled (default; kill-switch
TELEGRAM_RICH_ENABLED=0), the main text reply is sent as ONE sendRichMessage with
the RAW reply text as `rich_message.markdown` — no render_html, no bubble-split
(Telegram rich is a single message). Rich markdown is a SUPERSET of the classic
markdown the brain emits, so the raw text renders richly. render()/split() become
pass-throughs in rich mode so the worker's render->split->send_message path feeds
the raw text straight through. If the rich send fails for ANY reason (or rich is
disabled), send_message falls back to the classic render_html + sendMessage path so
the user never loses the reply.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from channels.base import OutboundResult
from channels.rich import (
    FilePart,
    ImagePart,
    PollPart,
    ReactionPart,
    TextPart,
    VoicePart,
)
from channels.tg_format import render_html, split_html_safe

log = logging.getLogger("worker.channels.telegram")


def _message_id(res) -> Optional[str]:
    """Pull a string message_id out of a Bot API result dict (or None)."""
    if isinstance(res, dict):
        result = res.get("result")
        if isinstance(result, dict):
            return str(result.get("message_id") or "") or None
    return None


class TelegramChannel:
    """Outbound Telegram via one bot token. One instance serves all TG tenants."""

    kind = "telegram"

    def __init__(self, client, *, rich_markdown: Optional[bool] = None):
        self._client = client
        # Kill-switch: explicit flag wins; else env TELEGRAM_RICH_ENABLED
        # ("1"/default -> on, "0" -> off). No worker.py change needed.
        if rich_markdown is None:
            rich_markdown = os.environ.get("TELEGRAM_RICH_ENABLED", "1") != "0"
        self._rich = bool(rich_markdown)

    def render(self, text: str) -> str:
        # In rich mode the reply is sent verbatim as rich-markdown, so render() is a
        # pass-through (the raw text flows through the worker's render->split->send
        # path untouched). Classic mode still produces Bot API HTML.
        if self._rich:
            return (text or "").strip()
        return render_html(text)

    def split(self, text: str) -> list:
        # Rich is ONE message — never split. Classic mode keeps tag-safe chunking.
        if self._rich:
            body = (text or "").strip()
            return [body] if body else []
        return split_html_safe(text)

    def send_message(self, address: str, text: str,
                     *, reply_markup: Optional[dict] = None) -> OutboundResult:
        body = text or ""
        if not body.strip():
            return OutboundResult(ok=False, error="empty body")

        # Rich path: one sendRichMessage with the RAW text as markdown. Wrapped so a
        # rich failure NEVER loses the reply — fall back to the classic HTML path.
        # `body` here is RAW (render()/split() were pass-throughs in rich mode), so
        # the fallback must render_html it.
        if self._rich:
            try:
                res = self._client.send_rich_message(address, body, reply_markup=reply_markup)
                return OutboundResult(ok=True, provider_id=_message_id(res))
            except Exception as e:
                log.warning("telegram rich send failed for %s; falling back to classic: %s",
                            address, e)
                # render_html is pure regex but guard it too so the fallback can NEVER
                # raise (best-effort contract); on a render hiccup send the raw body —
                # the client's own 400->plain still lands it.
                try:
                    classic_body = render_html(body)
                except Exception:
                    classic_body = body
                return self._send_classic(address, classic_body)

        # Classic mode: byte-identical to today. The worker already ran render()
        # (-> HTML) + split(), so `body` is already-rendered HTML — send as-is.
        return self._send_classic(address, body)

    def _send_classic(self, address: str, body: str) -> OutboundResult:
        """Classic sendMessage (today's behavior). `body` is already-HTML; the
        client's own 400->plain fallback covers any residual malformed markup so the
        reply still lands. Best-effort: any client error -> ok=False, never raises."""
        try:
            res = self._client.send_message(address, body)
            return OutboundResult(ok=True, provider_id=_message_id(res))
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

    def send_rich(self, address: str, part, *, reply_to: Optional[str] = None) -> OutboundResult:
        """Send one RichPart, mapping it to the right Bot API method.

        Telegram natively supports every kind:
          Text->sendMessage(HTML) · Image->sendPhoto · File->sendDocument ·
          Voice->sendVoice · Reaction->setMessageReaction(reply_to=message_id) ·
          Poll->sendPoll (NATIVE). Best-effort: any client error → ok=False, never raises.
        """
        try:
            if isinstance(part, TextPart):
                # Text goes through send_message: rich-markdown when enabled (one
                # sendRichMessage, raw text), else the classic HTML+plain-fallback path.
                return self.send_message(address, part.text)

            if isinstance(part, ImagePart):
                res = self._client.send_photo(address, part.src)
            elif isinstance(part, FilePart):
                res = self._client.send_document(address, part.src)
            elif isinstance(part, VoicePart):
                res = self._client.send_voice(address, part.src)
            elif isinstance(part, ReactionPart):
                if not reply_to:
                    # No target message → can't react; degrade gracefully (no raise).
                    log.info("telegram reaction skipped for %s: no reply_to target", address)
                    return OutboundResult(ok=False, error="reaction needs reply_to target")
                res = self._client.set_message_reaction(address, reply_to, part.emoji)
            elif isinstance(part, PollPart):
                res = self._client.send_poll(address, part.question, list(part.options))
            else:
                log.warning("telegram send_rich: unsupported part %r", type(part).__name__)
                return OutboundResult(ok=False, error=f"unsupported part {type(part).__name__}")

            # setMessageReaction returns {"result": true}; _message_id guards that
            # (non-dict result) and yields None.
            return OutboundResult(ok=True, provider_id=_message_id(res))
        except Exception as e:  # best-effort: never raise into the loop
            log.warning("telegram send_rich (%s) failed for %s: %s",
                        type(part).__name__, address, e)
            return OutboundResult(ok=False, error=str(e)[:200])
