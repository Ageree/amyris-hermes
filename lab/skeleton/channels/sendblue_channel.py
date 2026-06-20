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
from channels.rich import FilePart, ImagePart, PollPart, TextPart, VoicePart

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

    def send_rich(self, address: str, part, *, reply_to: Optional[str] = None) -> OutboundResult:
        """Send one RichPart over Sendblue, degrading gracefully (never raises).

        Sendblue is the iMessage KILL-SWITCH transport — it has no attachment /
        voice / reaction API wired here, so only text-shaped parts can be
        delivered. Per the channel contract, every kind degrades best-effort
        (never raises) so a rich reply still falls back to plain delivery:

          * TextPart -> send_message (the normal path).
          * PollPart -> degrade to a numbered text list via send_message (same as
            Photon's iMessage poll degradation — iMessage has no native poll).
          * Image/File/Voice -> degrade to TEXT: send the .src URL via
            send_message so iMessage auto-unfurls it. Dropping it (the old
            ok=False no-op) was a regression vs the pre-rich plain-text send,
            since parse_rich turns a bare image URL into an ImagePart.
          * Reaction -> logged no-op, ok=False (Sendblue has no tapback API).

        For full iMessage rich messaging, set IMESSAGE_PROVIDER=photon (PhotonChannel).
        """
        if isinstance(part, TextPart):
            return self.send_message(address, part.text)
        if isinstance(part, PollPart):
            lines = [part.question]
            lines.extend(f"{i}. {opt}" for i, opt in enumerate(part.options, 1))
            return self.send_message(address, "\n".join(lines))
        if isinstance(part, (ImagePart, FilePart, VoicePart)):
            src = (part.src or "").strip()
            if not src:
                return OutboundResult(ok=False, error="empty src")
            return self.send_message(address, src)
        kind = type(part).__name__
        log.info("sendblue send_rich: %s unsupported (iMessage kill-switch path)", kind)
        return OutboundResult(ok=False, error=f"unsupported on sendblue: {kind}")
