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

    def send_rich(
        self, address: str, part, *, reply_to: Optional[str] = None
    ) -> OutboundResult:
        """Send ONE RichPart (channels/rich.py) to `address`, best-effort.

        Each channel handles every RichPart kind; an UNSUPPORTED kind DEGRADES
        gracefully and NEVER raises (it returns OutboundResult, ok possibly
        False/logged), so a rich reply can always fall back to plain delivery:

          * iMessage (Photon): Text -> /send ; Image/File/Voice -> /send-attachment ;
            Reaction -> /react (target = `reply_to` provider msg id; if None,
            log + skip with ok=False) ; Poll -> degrade to a numbered text list
            via /send.
          * Telegram: Text -> sendMessage(HTML) ; Image -> sendPhoto ;
            File -> sendDocument ; Voice -> sendVoice ;
            Reaction -> setMessageReaction (reply_to = message_id) ;
            Poll -> sendPoll (NATIVE).

        `reply_to` is the provider message id of the user's most-recent inbound,
        used by Reaction parts (and any channel that anchors a part to a message).
        """
        ...

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

        iMessage transport is chosen by IMESSAGE_PROVIDER (cfg.imessage_provider,
        default "sendblue" — Sendblue stays the kill-switch). When provider=="photon"
        AND the Photon sidecar config + creds are present, build a PhotonChannel;
        otherwise fall through to the Sendblue branch (so a misconfigured "photon"
        request degrades to the known-good Sendblue path rather than yielding NO
        iMessage channel — get("imessage") would then raise and strand replies).
        Telegram when a bot token is set. A worker with only Sendblue creds gets an
        iMessage-only registry — get("telegram") then raises, which is correct (it
        can't serve Telegram rows). Imports are lazy to avoid a hard dependency on a
        transport's client when that transport isn't configured.

        New cfg fields are read via getattr(cfg, name, default) so this works
        whether or not WorkerConfig yet carries them (the integration agent adds
        imessage_provider / photon_* by these exact names).
        """
        channels: dict = {}

        imessage_built = False
        provider = (getattr(cfg, "imessage_provider", "") or "sendblue").lower()
        photon_base = getattr(cfg, "photon_sidecar_base", "") or ""
        photon_pid = getattr(cfg, "photon_project_id", "") or ""
        photon_secret = getattr(cfg, "photon_project_secret", "") or ""

        if provider == "photon" and photon_base and photon_pid and photon_secret:
            from channels.photon_channel import PhotonChannel

            channels["imessage"] = PhotonChannel(
                sidecar_base=photon_base,
                bearer=getattr(cfg, "photon_bearer", "") or "",
                sidecar_dir=getattr(cfg, "photon_sidecar_dir", None) or None,
                project_id=photon_pid,
                project_secret=photon_secret,
            )
            imessage_built = True

        if (
            not imessage_built
            and cfg.sendblue_key_id
            and cfg.sendblue_secret
            and cfg.sendblue_from
        ):
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
