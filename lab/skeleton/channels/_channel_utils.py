"""Shared channel utilities — DRY helpers used by multiple channel adapters.

Extracted from sendblue_channel.py and photon_channel.py to eliminate identical
copies. Both iMessage transports (Sendblue, Photon) need the same security guard
(_is_remote) and the same poll-to-text degradation; keeping one copy here means a
fix in one place covers both.
"""
from __future__ import annotations

from channels.rich import PollPart


def is_remote(src: str) -> bool:
    """True only for an http(s) URL -- local paths are refused (file-exfil guard)."""
    return isinstance(src, str) and (src.startswith("http://") or src.startswith("https://"))


def poll_to_text(part: PollPart) -> str:
    """Degrade a PollPart to a numbered text list (iMessage has no native poll)."""
    lines = [part.question]
    lines.extend(f"{i}. {opt}" for i, opt in enumerate(part.options, 1))
    return "\n".join(lines)
