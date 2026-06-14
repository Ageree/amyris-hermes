"""Channel abstraction — make the worker provider-agnostic (multi-tenancy M2).

The worker used to talk to Sendblue directly and pin every reply to the single
operator number. With multiple tenants on two providers (iMessage + Telegram) the
reply path must route by the CLAIMED message's own channel + address. A small
duck-typed `Channel` Protocol (matches the repo style) gives the worker one
uniform send/typing/split/render seam; one instance serves ALL tenants on that
provider (the address is passed per call), so there is no per-user client churn.

Design rules:
  * Sends are BEST-EFFORT: a provider hiccup returns OutboundResult(ok=False) and
    is logged, NEVER raised — a transient send failure must not kill the always-on
    poll loop or strand a message.
  * render() turns plain assistant text into the provider's wire format (iMessage:
    plain; Telegram: HTML). split() chunks the rendered text within provider
    limits. The worker calls render() then split() then send_message().
  * ChannelRegistry.from_config builds ONLY the channels whose credentials exist,
    and get() fails loudly (KeyError) for an unconfigured kind rather than
    silently dropping a reply.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

log = logging.getLogger("worker.channels")


@dataclass(frozen=True)
class OutboundResult:
    """Outcome of a best-effort outbound send/typing call (immutable)."""

    ok: bool
    provider_id: Optional[str] = None
    error: Optional[str] = None


@runtime_checkable
class Channel(Protocol):
    """A provider-agnostic outbound channel (iMessage, Telegram, ...).

    runtime_checkable so tests can assert each concrete impl satisfies it. Note
    Protocol's isinstance check verifies member NAMES exist, not signatures —
    the conformance tests additionally exercise the real call shapes.
    """

    kind: str  # "imessage" | "telegram"

    def send_message(self, address: str, text: str) -> OutboundResult: ...

    def send_typing(
        self, address: str, *, state: str = "start", max_duration_ms: Optional[int] = None
    ) -> OutboundResult: ...

    def split(self, text: str) -> list: ...

    def render(self, text: str) -> str: ...


class ChannelRegistry:
    """Immutable kind -> Channel map. `process_one` selects by the claimed channel."""

    def __init__(self, channels: dict):
        # Defensive copy so callers can't mutate the registry after construction.
        self._channels = dict(channels)

    def get(self, kind: str) -> Channel:
        """Return the channel for `kind`, or raise KeyError if unconfigured.

        Failing loud (rather than defaulting) surfaces a misconfigured fleet (e.g.
        a Telegram row claimed on a worker with no bot token) instead of silently
        misrouting or dropping the reply.
        """
        ch = self._channels.get(kind)
        if ch is None:
            raise KeyError(
                f"no channel registered for kind {kind!r} (have: {sorted(self._channels)})"
            )
        return ch

    def kinds(self) -> list:
        return sorted(self._channels)

    def __contains__(self, kind: object) -> bool:
        return kind in self._channels

    def __len__(self) -> int:
        return len(self._channels)

    @classmethod
    def from_config(cls, cfg) -> "ChannelRegistry":
        """Build the channels whose credentials are present in `cfg`.

        iMessage (Sendblue) when the key/secret/from are set; Telegram when a bot
        token is set. A worker with only Sendblue creds gets an iMessage-only
        registry — get("telegram") then raises, which is correct (it can't serve
        Telegram rows). Imports are lazy to avoid a hard dependency on the Telegram
        client when only iMessage is configured.
        """
        channels: dict = {}

        if cfg.sendblue_key_id and cfg.sendblue_secret and cfg.sendblue_from:
            from sendblue_client import SendblueClient
            from channels.sendblue_channel import SendblueChannel

            client = SendblueClient(cfg.sendblue_key_id, cfg.sendblue_secret, cfg.sendblue_from)
            channels["imessage"] = SendblueChannel(
                client, max_bubbles=cfg.bubble_max_count, max_chars=cfg.bubble_max_chars
            )

        token = getattr(cfg, "telegram_bot_token", "")
        if token:
            from channels.telegram_client import TelegramClient
            from channels.telegram_channel import TelegramChannel

            channels["telegram"] = TelegramChannel(TelegramClient(token))

        return cls(channels)
