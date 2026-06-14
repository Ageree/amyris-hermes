"""Provider-agnostic outbound channel layer for the multi-tenant worker."""
from channels.base import Channel, ChannelRegistry, OutboundResult
from channels.sendblue_channel import SendblueChannel
from channels.telegram_channel import TelegramChannel

__all__ = [
    "Channel",
    "ChannelRegistry",
    "OutboundResult",
    "SendblueChannel",
    "TelegramChannel",
]
