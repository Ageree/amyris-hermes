"""iMessage channel — thin adapter over the existing SendblueClient.

Zero behavior churn vs. the pre-channel worker: render() is a plain-text strip
(iMessage has no rich formatting), split() is the existing Poke-bubble splitter,
and send_message/send_typing forward to SendblueClient with the SAME call shapes
(`to_number=`, `content=`, `state=`) the worker tests assert. The only change is
that the recipient address is passed PER CALL instead of pinned to a config
constant, which is what makes multi-tenant routing possible.
"""
from __future__ import annotations

import logging
from typing import Optional

from bubbles import split_into_bubbles
from channels.base import OutboundResult

log = logging.getLogger("worker.channels.imessage")

MAX_REPLY_CHARS = 1800  # iMessage belt-and-suspenders clamp (matches bubbles hard_cap)


class SendblueChannel:
    """Outbound iMessage via Sendblue. One instance serves all iMessage tenants."""

    kind = "imessage"

    def __init__(self, client, *, max_bubbles: int = 4, max_chars: int = 1200,
                 max_reply_chars: int = MAX_REPLY_CHARS):
        self._client = client
        self._max_bubbles = int(max_bubbles)
        self._max_chars = int(max_chars)
        self._max_reply_chars = int(max_reply_chars)

    def render(self, text: str) -> str:
        """iMessage is plain text — just trim. (The wire-format seam for parity.)"""
        return (text or "").strip()

    def split(self, text: str) -> list:
        """Poke-style bubble split with this channel's caps."""
        return split_into_bubbles(text, max_bubbles=self._max_bubbles, max_chars=self._max_chars)

    def send_message(self, address: str, text: str) -> OutboundResult:
        body = (text or "")[: self._max_reply_chars]
        if not body.strip():
            return OutboundResult(ok=False, error="empty body")
        try:
            res = self._client.send_message(to_number=address, content=body)
            pid = res.get("message_handle") if isinstance(res, dict) else None
            return OutboundResult(ok=True, provider_id=pid)
        except Exception as e:  # best-effort: never raise into the loop
            log.warning("sendblue send failed for %s: %s", address, e)
            return OutboundResult(ok=False, error=str(e)[:200])

    def send_typing(
        self, address: str, *, state: str = "start", max_duration_ms: Optional[int] = None
    ) -> OutboundResult:
        try:
            self._client.send_typing(address, state=state, max_duration_ms=max_duration_ms)
            return OutboundResult(ok=True)
        except Exception as e:  # cosmetic — never let typing break the reply
            log.debug("sendblue typing %s failed for %s: %s", state, address, e)
            return OutboundResult(ok=False, error=str(e)[:200])
