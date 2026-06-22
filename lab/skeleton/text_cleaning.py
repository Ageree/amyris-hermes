"""Shared text-cleaning utilities for stripping model reasoning blocks.

Both hermes_bridge.py and fast_lane.py need to strip `<think>...</think>` blocks
emitted by M3's reasoning mode. Consolidating the regexes here means one place to
update if the tag format changes, and both paths get the dangling-open-tag handling
that was previously only in fast_lane.
"""
from __future__ import annotations

import re

# Strip completed <think>...</think> reasoning blocks (case-insensitive).
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# Strip a dangling open <think> with no close (reasoning truncated by max_tokens):
# without this, raw reasoning would leak as the "answer".
THINK_OPEN_RE = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def strip_think_blocks(text: str) -> str:
    """Remove completed and dangling <think> reasoning blocks from text."""
    t = THINK_RE.sub("", text or "")
    t = THINK_OPEN_RE.sub("", t)
    return t.strip()
