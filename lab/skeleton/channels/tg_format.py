"""Telegram outbound formatting — plain assistant text -> Bot API HTML.

v1 uses parse_mode="HTML", NOT MarkdownV2: HTML escapes only & < >, whereas
MarkdownV2 needs 18 chars escaped (`. - ! =` appear in every list/decimal/
sentence) and is a chronic source of 400s. The lowercase SOUL voice is untouched
— formatting is purely structural, applied AFTER generation.

render_html maps the small Markdown subset the model emits:
  **bold** -> <b>, *italic*/_italic_ -> <i>, `code` -> <code>,
  ```lang fenced``` -> <pre><code class="language-lang">…</code></pre>.
Dynamic text is HTML-escaped FIRST (and code spans are stashed before inline
parsing so a `<` inside code is escaped, not treated as a tag).

split_html_safe chunks the rendered HTML within Telegram's 4096-char message
limit WITHOUT ever cutting an open tag.

NOTE: this is the structural core; M3 (the Telegram milestone) hardens edge cases
(nested emphasis, expandable <blockquote> for long tool dumps) and adds the deep
Bot API 10.1 conformance suite. Kept deliberately small + pure here.
"""
from __future__ import annotations

import re
from typing import List

TG_HARD_CAP = 4096      # Telegram sendMessage hard limit (chars)
TG_SOFT_CHARS = 3800    # leave headroom under the cap for safety

_FENCE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<![\w*])[*_]([^*_\n]+)[*_](?![\w*])")


def _esc(text: str) -> str:
    """Escape the three HTML-significant chars Telegram cares about."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_html(text: str) -> str:
    """Render the model's light Markdown into Telegram-safe HTML.

    Order matters: stash fenced + inline code (escaping their bodies) BEHIND
    placeholders, escape the remaining prose, apply inline emphasis, then restore
    the code blocks. This guarantees a `<` in code is escaped and emphasis markers
    inside code are not interpreted.
    """
    # Strip NUL FIRST: the placeholder scheme below is NUL-delimited, so a literal
    # NUL in model output (control chars do leak from LLMs echoing garbled/tool
    # text) would otherwise collide with / corrupt a placeholder. NUL is never
    # meaningful in a chat reply, so dropping it is lossless.
    src = (text or "").replace("\x00", "")
    stash: List[str] = []

    def _stash(rendered: str) -> str:
        stash.append(rendered)
        return f"\x00{len(stash) - 1}\x00"  # NUL-delimited placeholder (NUL pre-stripped above)

    # 1. Fenced code blocks -> <pre><code> (optionally language-tagged).
    def _fence(m: "re.Match") -> str:
        lang = m.group(1).strip()
        body = _esc(m.group(2).rstrip("\n"))
        cls = f' class="language-{lang}"' if lang else ""
        return _stash(f"<pre><code{cls}>{body}</code></pre>")

    src = _FENCE_RE.sub(_fence, src)

    # 2. Inline `code` -> <code>.
    src = _INLINE_CODE_RE.sub(lambda m: _stash(f"<code>{_esc(m.group(1))}</code>"), src)

    # 3. Escape the remaining prose.
    src = _esc(src)

    # 4. Inline emphasis on the escaped prose.
    src = _BOLD_RE.sub(r"<b>\1</b>", src)
    src = _ITALIC_RE.sub(r"<i>\1</i>", src)

    # 5. Restore stashed code blocks. Bounds-safe: an index we never stashed
    # (impossible now NUL is stripped, but defensive) restores to nothing.
    def _unstash(m: "re.Match") -> str:
        i = int(m.group(1))
        return stash[i] if 0 <= i < len(stash) else ""

    src = re.sub(r"\x00(\d+)\x00", _unstash, src)
    return src.strip()


def _slice_no_tag_cut(text: str, limit: int) -> int:
    """Return a cut index <= limit that does not fall inside an open '<...>' tag."""
    if len(text) <= limit:
        return len(text)
    window = text[:limit]
    lt = window.rfind("<")
    gt = window.rfind(">")
    if lt > gt:  # an unclosed tag straddles the boundary — cut before it
        return lt if lt > 0 else limit
    return limit


_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s[^>]*)?)>")


def _balance_chunks(chunks: List[str]) -> List[str]:
    """Make each chunk standalone-valid HTML by closing tags left open at a chunk
    boundary and reopening them at the start of the next chunk.

    A long fenced code block or <blockquote> split across chunks would otherwise
    leave chunk N with an unclosed <pre><code> and chunk N+1 with an orphan
    </code></pre> — both rejected by Telegram parse_mode=HTML. We thread the open-
    tag stack across chunks (reopening with the ORIGINAL opening tag, attributes
    included, e.g. <code class="language-python">) so every chunk parses on its own.
    """
    out: List[str] = []
    carry: List[str] = []  # full opening-tag strings to reopen at the next chunk start
    for chunk in chunks:
        body = "".join(carry) + chunk
        stack: List[tuple] = []  # (tagName, fullOpeningString)
        for m in _TAG_RE.finditer(body):
            closing, name = m.group(1), m.group(2).lower()
            if closing:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == name:
                        del stack[i]
                        break
            else:
                stack.append((name, m.group(0)))
        closers = "".join(f"</{name}>" for name, _ in reversed(stack))
        out.append(body + closers)
        carry = [full for _, full in stack]
    return out


def split_html_safe(text: str, *, max_chars: int = TG_SOFT_CHARS, hard_cap: int = TG_HARD_CAP) -> List[str]:
    """Chunk rendered HTML into <= max_chars pieces, each standalone-valid HTML.

    Telegram is ONE batch message per reply (no Poke bubbles — the ~1/s per-chat
    limit makes multi-bubble counterproductive), so this only fires for replies
    longer than a single message. Splits on paragraph then line boundaries; a
    boundary-less giant blob is hard-sliced at a tag-safe index; then tags spanning
    a boundary are closed+reopened so no chunk has a dangling/orphan tag.
    """
    body = (text or "").strip()
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]

    chunks: List[str] = []
    remaining = body
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        # Prefer a paragraph or line break within the window; else a tag-safe cut.
        window = remaining[:max_chars]
        cut = window.rfind("\n\n")
        if cut < max_chars // 2:
            cut = window.rfind("\n")
        if cut < max_chars // 2:
            cut = _slice_no_tag_cut(remaining, max_chars)
        chunk = remaining[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip()

    return [c[:hard_cap] for c in _balance_chunks(chunks) if c]
