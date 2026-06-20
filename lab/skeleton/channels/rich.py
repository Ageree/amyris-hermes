"""Shared rich-message contract — parse a flat brain reply into ordered parts.

The brain (`hermes chat --query=`) returns a single flat string. To support rich
messaging WITHOUT teaching the brain a new output protocol, the channel layer
parses a small, prose-safe markup convention out of that string into an ordered
list of `RichPart`s. Each channel then renders the parts IT supports; unsupported
parts degrade (e.g. iMessage has no native poll, so it would render the poll as a
numbered text list — that's the channel's call, not this parser's).

Directive tokens (chosen so they don't appear in ordinary replies):

  * `[[react:EMOJI]]` — a LEADING token (one or more, before any text) → a
    `ReactionPart(EMOJI)` targeting the user's most-recent inbound message. The
    token(s) are stripped from the remaining text.

  * a fenced block::

        ```poll
        <question>
        <option 1>
        <option 2>
        ...
        ```

    → `PollPart(question, [options])`. The fence is removed from the text stream.

  * a markdown image `![alt](URL)` OR a bare http(s) URL whose path ends in an
    image extension (.png/.jpg/.jpeg/.gif/.webp) → `ImagePart(URL)`. A non-image
    URL is left as ordinary inline text.

  * everything else → `TextPart`. Consecutive text is merged; whitespace-only
    text is dropped.

If a reply contains NONE of the tokens, `parse_rich` returns a single
`[TextPart(whole_reply)]` — back-compatible with the plain-text send path.

ponytail: tiny + regex-based by design. The known ceiling is "directive collisions
in normal prose" — the tokens are deliberately unusual; if false positives ever
show up, the upgrade path is a stricter/escaped grammar, not a parser rewrite.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    src: str  # http(s) URL or local file path


@dataclass(frozen=True)
class FilePart:
    src: str  # http(s) URL or local file path
    name: Union[str, None] = None


@dataclass(frozen=True)
class VoicePart:
    src: str  # http(s) URL or local file path


@dataclass(frozen=True)
class ReactionPart:
    emoji: str  # targets the user's most-recent inbound; channel decides how


@dataclass(frozen=True)
class PollPart:
    question: str
    options: tuple  # immutable; built from the fenced option lines


RichPart = Union[TextPart, ImagePart, FilePart, VoicePart, ReactionPart, PollPart]

# Leading reaction token(s): `[[react:❤️]]` possibly repeated at the very start.
_REACT = re.compile(r"^\s*\[\[react:([^\]\n]+?)\]\]\s*")
# Fenced poll block (DOTALL on the body; tolerant of CRLF and trailing space).
_POLL = re.compile(r"```poll[ \t]*\r?\n(.*?)\r?\n?```", re.DOTALL)
# Markdown image: ![alt](URL)
_MD_IMG = re.compile(r"!\[[^\]]*\]\((\S+?)\)")
# Markdown link (NON-image form: no leading `!`): consumed as one opaque token so
# the bare-URL scan never peeks inside its parens (else an image-extension URL in
# a link would shred `[text](https://x/banner.png)`).
_MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(\S+?\)")
# Bare http(s) image URL ending in a known image extension.
_IMG_EXT = r"(?:png|jpe?g|gif|webp)"
_BARE_IMG = re.compile(
    r"https?://\S+?\." + _IMG_EXT + r"(?:\?\S*)?",
    re.IGNORECASE,
)


def _strip_leading_reactions(reply: str) -> tuple[list[ReactionPart], str]:
    """Peel one or more leading `[[react:…]]` tokens off the front of `reply`."""
    reactions: list[ReactionPart] = []
    rest = reply
    while True:
        m = _REACT.match(rest)
        if not m:
            break
        emoji = m.group(1).strip()
        if emoji:
            reactions.append(ReactionPart(emoji))
        rest = rest[m.end():]
    return reactions, rest


def _parse_poll(block: str) -> Union[PollPart, None]:
    """Turn a fenced poll body (question line + option lines) into a PollPart."""
    lines = [ln.strip() for ln in block.splitlines()]
    lines = [ln for ln in lines if ln]
    if len(lines) < 2:  # need a question and at least one option
        return None
    question, *options = lines
    return PollPart(question, tuple(options))


def _split_images(text: str) -> list[RichPart]:
    """Split a text run on image refs (markdown OR bare image URL), preserving order.

    Non-image text between/around images becomes TextPart; whitespace-only is
    dropped by the caller's merge step.
    """
    parts: list[RichPart] = []
    pos = 0
    # Scan for the earliest of (markdown image, markdown link, bare image URL)
    # repeatedly. A markdown link is emitted verbatim as text (re-coalesced by
    # _merge_text) so the bare-URL scan can't shred an image-extension URL it wraps.
    while True:
        md = _MD_IMG.search(text, pos)
        link = _MD_LINK.search(text, pos)
        bare = _BARE_IMG.search(text, pos)
        candidates = [m for m in (md, link, bare) if m is not None]
        if not candidates:
            break
        m = min(candidates, key=lambda x: x.start())
        if m.start() > pos:
            parts.append(TextPart(text[pos:m.start()]))
        if m.re is _MD_LINK:
            parts.append(TextPart(m.group(0)))  # link stays opaque text
        else:
            url = m.group(1) if m.re is _MD_IMG else m.group(0)
            parts.append(ImagePart(url))
        pos = m.end()
    if pos < len(text):
        parts.append(TextPart(text[pos:]))
    return parts


def _merge_text(parts: list[RichPart]) -> list[RichPart]:
    """Merge consecutive TextParts and drop whitespace-only text."""
    out: list[RichPart] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            merged = "".join(buf).strip()
            if merged:
                out.append(TextPart(merged))
            buf.clear()

    for p in parts:
        if isinstance(p, TextPart):
            buf.append(p.text)
        else:
            flush()
            out.append(p)
    flush()
    return out


def parse_rich(reply: str) -> list[RichPart]:
    """Parse a flat brain reply into an ordered list of RichParts.

    Order is preserved: leading reactions first, then text/image/poll runs in the
    sequence they appear. A reply with no directives yields a single TextPart
    (back-compat with the plain-text send path).
    """
    if reply is None:
        return []

    reactions, body = _strip_leading_reactions(reply)

    parts: list[RichPart] = list(reactions)

    # Walk the body, carving out poll fences in place; text between fences is
    # further split on image refs. This preserves the source ordering.
    pos = 0
    for m in _POLL.finditer(body):
        before = body[pos:m.start()]
        if before:
            parts.extend(_split_images(before))
        poll = _parse_poll(m.group(1))
        if poll is not None:
            parts.append(poll)
        else:
            # Malformed fence → keep the raw block as text (don't lose content).
            parts.extend(_split_images(m.group(0)))
        pos = m.end()
    tail = body[pos:]
    if tail:
        parts.extend(_split_images(tail))

    merged = _merge_text(parts)

    # Back-compat: an empty parse of a non-empty reply still yields the raw text.
    if not merged and (reply or "").strip():
        return [TextPart(reply.strip())]
    return merged
