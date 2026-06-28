"""Shared channel utilities — DRY helpers used by multiple channel adapters.

Extracted from sendblue_channel.py and photon_channel.py to eliminate identical
copies. Both iMessage transports (Sendblue, Photon) need the same security guard
(_is_remote) and the same poll-to-text degradation; keeping one copy here means a
fix in one place covers both.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from channels.rich import PollPart


def is_remote(src: str) -> bool:
    """True only for a safe http(s) URL.

    Refuses local paths and obvious SSRF targets such as loopback/private IPs and
    metadata hosts. DNS rebinding needs network-level egress controls; this guard
    blocks the prompt-injected literals we can identify before transport.
    """
    if not isinstance(src, str):
        return False
    if not (src.startswith("http://") or src.startswith("https://")):
        return False
    host = urlsplit(src).hostname or ""
    if not host:
        return False
    if host in ("localhost", "metadata.google.internal") or host.endswith(".internal"):
        return False
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return False
    except ValueError:
        pass
    return True


def poll_to_text(part: PollPart) -> str:
    """Degrade a PollPart to a numbered text list (iMessage has no native poll)."""
    lines = [part.question]
    lines.extend(f"{i}. {opt}" for i, opt in enumerate(part.options, 1))
    return "\n".join(lines)
