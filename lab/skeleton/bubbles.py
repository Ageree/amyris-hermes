"""Split one assistant reply into Poke-style iMessage "bubbles".

A real person texting sends a few short messages, not one wall of text. The model
is nudged (SOUL.md) to separate distinct thoughts with a blank line; this module
turns those blank-line paragraphs into separate bubbles, and defensively keeps
each bubble within a safe length (hard-slicing a pathologically long paragraph
that has no sentence boundaries, e.g. a giant token blob, rather than dropping it).

Pure + immutable: takes a string, returns a NEW list of strings. No I/O, no
network — the worker owns the actual Sendblue sends + pacing.

Design rules:
  * Primary boundary = a blank line (the model's intended message break).
  * An over-long paragraph is split on sentence boundaries, then hard-sliced if a
    single sentence is still too long. URLs/code survive: sentence splitting only
    fires on '.!?…' followed by whitespace (a URL's dots are not).
  * `max_bubbles` is a SOFT ceiling for normal replies; content is NEVER silently
    dropped below `max_bubbles * max_chars`. Past that runaway budget the tail is
    dropped with a visible '…' marker (and the caller logs it) — never a silent cut.
  * Every returned bubble is <= `hard_cap` (a final belt-and-suspenders clamp).
"""
from __future__ import annotations

import re
from typing import List

# A blank line (optionally with stray whitespace) separates intended messages.
_PARA_SPLIT = re.compile(r"\n[ \t]*\n+")
# Sentence boundary: end punctuation followed by whitespace. A URL like
# "example.com/x" has no '.' + whitespace inside it, so it is never split.
_SENT_SPLIT = re.compile(r"(?<=[.!?…。！？])\s+")

DEFAULT_MAX_BUBBLES = 4
DEFAULT_MAX_CHARS = 1200
DEFAULT_HARD_CAP = 1800
TRUNCATION_MARK = "…"


def _hard_slice(text: str, max_chars: int) -> List[str]:
    """Slice a boundary-less blob into <= max_chars pieces (last resort)."""
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)] or [text]


def _split_paragraph(paragraph: str, max_chars: int) -> List[str]:
    """A single paragraph -> one or more bubbles, each <= max_chars."""
    para = paragraph.strip()
    if not para:
        return []
    if len(para) <= max_chars:
        return [para]
    # Too long: greedily pack whole sentences into <= max_chars chunks.
    chunks: List[str] = []
    current = ""
    for sentence in _SENT_SPLIT.split(para):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            # A single sentence (or a giant token blob) longer than the cap.
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_slice(sentence, max_chars))
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def split_into_bubbles(
    text: str,
    *,
    max_bubbles: int = DEFAULT_MAX_BUBBLES,
    max_chars: int = DEFAULT_MAX_CHARS,
    hard_cap: int = DEFAULT_HARD_CAP,
) -> List[str]:
    """Split `text` into Poke-style bubbles (a NEW list; never mutates input).

    Returns [] for empty/whitespace-only input. A normal short reply with no blank
    line returns a single-element list (degrades to the old single-send behavior).
    """
    base = (text or "").strip()
    if not base:
        return []

    bubbles: List[str] = []
    for paragraph in _PARA_SPLIT.split(base):
        bubbles.extend(_split_paragraph(paragraph, max_chars))

    if not bubbles:
        return []

    # Soft ceiling: keep the first `max_bubbles`. Only mark truncation if real
    # content is being dropped (never a silent cut — caller logs the drop too).
    if len(bubbles) > max_bubbles:
        kept = bubbles[:max_bubbles]
        last = kept[-1]
        if not last.endswith(TRUNCATION_MARK):
            # leave room for the marker under the cap
            trimmed = last[: max_chars - len(TRUNCATION_MARK)].rstrip()
            kept[-1] = f"{trimmed}{TRUNCATION_MARK}"
        bubbles = kept

    # Final hard clamp per bubble; drop any that became empty.
    return [b[:hard_cap] for b in (b.strip() for b in bubbles) if b.strip()]


def was_truncated(bubbles: List[str]) -> bool:
    """True if the last bubble carries the drop marker (for caller logging)."""
    return bool(bubbles) and bubbles[-1].endswith(TRUNCATION_MARK)
