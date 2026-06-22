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
from channels.rich import FilePart, ImagePart, PollPart, ReactionPart, TextPart, VoicePart
from channels._channel_utils import is_remote as _is_remote, poll_to_text as _poll_to_text

log = logging.getLogger("worker.channels.imessage")

MAX_REPLY_CHARS = 1800  # iMessage belt-and-suspenders clamp (matches bubbles hard_cap)

# The 6 iMessage tapbacks Sendblue's /send-reaction accepts.
_TAPBACKS = frozenset({"love", "like", "dislike", "laugh", "emphasize", "question"})

# Map the brain's free-form reaction emoji onto the fixed tapback set. Sendblue
# (unlike Photon's Spectrum) only supports these 6, so an arbitrary emoji is
# coerced to the closest tapback; an unmappable one is SKIPPED (never coerced to a
# wrong sentiment — see send_rich).
# ponytail: a hand-curated table of the common reactions the brain emits. Ceiling
# = "unknown emoji → no reaction"; upgrade path = a sentiment classifier if the
# brain starts emitting an unbounded emoji vocabulary.
_EMOJI_TO_TAPBACK = {
    "❤️": "love", "❤": "love", "🩷": "love", "😍": "love", "🥰": "love",
    "💕": "love", "💖": "love", "💗": "love", "♥️": "love",
    "👍": "like", "👍🏻": "like", "🙂": "like", "✅": "like", "👌": "like",
    "👎": "dislike", "👎🏻": "dislike",
    "😂": "laugh", "🤣": "laugh", "😆": "laugh", "😅": "laugh", "😄": "laugh", "😹": "laugh",
    "‼️": "emphasize", "❗": "emphasize", "❗️": "emphasize", "🔥": "emphasize",
    "💯": "emphasize", "⚡": "emphasize", "🙌": "emphasize",
    "❓": "question", "❔": "question", "🤔": "question", "❓️": "question",
}


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
        """Send one RichPart over Sendblue, best-effort (never raises).

        Sendblue natively carries the project's full rich surface, so this is no
        longer a degrade-to-text kill-switch:

          * TextPart    -> send_message (the normal path).
          * Image/File/Voice -> send_message(media_url=src): a REAL attachment.
            Voice renders as a native voice bubble only for .caf; other audio
            arrives as an audio attachment (documented ceiling). If the media POST
            fails, fall back to sending the URL as text so it still reaches the
            user (iMessage auto-unfurls it) — no data loss.
          * ReactionPart -> /send-reaction tapback targeting `reply_to` (the
            inbound Apple GUID). The free-form emoji is mapped onto Sendblue's 6
            tapbacks; no reply_to OR an unmappable emoji -> skipped (ok=False).
          * PollPart    -> numbered text list (iMessage has no native poll).

        Only http(s) media srcs are allowed (file-exfil guard, mirrors PhotonChannel).
        """
        try:
            if isinstance(part, TextPart):
                return self.send_message(address, part.text)

            if isinstance(part, PollPart):
                return self.send_message(address, _poll_to_text(part))

            if isinstance(part, (ImagePart, FilePart, VoicePart)):
                src = (part.src or "").strip()
                if not src:
                    return OutboundResult(ok=False, error="empty src")
                if not _is_remote(src):
                    log.warning("sendblue: refusing non-remote media src %r", src)
                    return OutboundResult(ok=False, error="non-remote media src refused")
                return self._send_media(address, src)

            if isinstance(part, ReactionPart):
                if not reply_to:
                    log.info("sendblue reaction skipped for %s: no reply_to target", address)
                    return OutboundResult(ok=False, error="reaction needs reply_to target")
                tapback = _emoji_to_tapback(part.emoji)
                if not tapback:
                    log.info("sendblue reaction %r not mappable to a tapback — skipped", part.emoji)
                    return OutboundResult(ok=False, error=f"unmappable reaction {part.emoji}")
                res = self._client.send_reaction(message_handle=reply_to, reaction=tapback)
                pid = res.get("message_handle") if isinstance(res, dict) else None
                return OutboundResult(ok=True, provider_id=pid)

            kind = type(part).__name__
            log.info("sendblue send_rich: unsupported part %s", kind)
            return OutboundResult(ok=False, error=f"unsupported on sendblue: {kind}")
        except Exception as e:  # best-effort: never raise into the loop
            log.warning("sendblue send_rich (%s) failed for %s: %s",
                        type(part).__name__, address, e)
            return OutboundResult(ok=False, error=str(e)[:200])

    def _send_media(self, address: str, src: str) -> OutboundResult:
        """Send `src` as a media attachment; on failure, fall back to a text URL."""
        try:
            res = self._client.send_message(to_number=address, media_url=src)
            pid = res.get("message_handle") if isinstance(res, dict) else None
            return OutboundResult(ok=True, provider_id=pid)
        except Exception as e:
            log.warning("sendblue media send failed for %s (%s) — falling back to text URL",
                        address, e)
            return self.send_message(address, src)  # iMessage auto-unfurls the URL


# ---------------------------------------------------------------------------
# Module helpers (also useful standalone / in tests)


def _emoji_to_tapback(emoji: str) -> Optional[str]:
    """Map a free-form reaction emoji onto Sendblue's 6 tapbacks, or None.

    Accepts a literal tapback word (e.g. the brain emits `[[react:love]]`) as-is.
    Returns None when the emoji has no sensible tapback — the caller then SKIPS the
    reaction rather than coercing it to a wrong sentiment.
    """
    e = (emoji or "").strip()
    if e.lower() in _TAPBACKS:
        return e.lower()
    return _EMOJI_TO_TAPBACK.get(e)



