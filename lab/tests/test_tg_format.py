"""Telegram Bot API HTML formatting (M3): render_html + split_html_safe.

Covers the Markdown-subset -> HTML mapping (parse_mode=HTML, NOT MarkdownV2),
escaping safety (injection-proof), and the tag-safe chunker. Includes regression
tests for the M2 independent-review findings: NUL-input safety (no raise, no
content corruption) and standalone-valid chunks (no dangling/orphan tags across a
split). Network-free.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from channels import tg_format  # noqa: E402

_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)((?:\s[^>]*)?)>")


def _is_balanced(html: str) -> bool:
    """True if every open tag in `html` is closed within it (LIFO), no orphans."""
    stack = []
    for m in _TAG.finditer(html):
        closing, name = m.group(1), m.group(2).lower()
        if closing:
            if not stack or stack.pop() != name:
                return False
        else:
            stack.append(name)
    return not stack


# ---- render_html: escaping ---------------------------------------------------

def test_escapes_html_specials_in_prose():
    assert tg_format.render_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_escapes_forged_tag_no_breakout():
    # A model emitting a literal HTML tag must be escaped, never passed through.
    assert tg_format.render_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_escapes_inside_inline_code():
    assert tg_format.render_html("use `a<b && c>d`") == "use <code>a&lt;b &amp;&amp; c&gt;d</code>"


# ---- render_html: emphasis + code -------------------------------------------

def test_bold_italic_inline_code():
    assert tg_format.render_html("**b** *i* `c`") == "<b>b</b> <i>i</i> <code>c</code>"


def test_italic_underscore():
    assert tg_format.render_html("_emph_") == "<i>emph</i>"


def test_fenced_code_with_language():
    out = tg_format.render_html("```python\nprint(1<2)\n```")
    assert out == '<pre><code class="language-python">print(1&lt;2)</code></pre>'


def test_fenced_code_without_language():
    out = tg_format.render_html("```\nplain & <code>\n```")
    assert out == "<pre><code>plain &amp; &lt;code&gt;</code></pre>"


def test_emphasis_markers_inside_code_are_literal():
    assert tg_format.render_html("`**not bold**`") == "<code>**not bold**</code>"


def test_lowercase_voice_untouched():
    # Formatting is structural; the SOUL lowercase voice is preserved verbatim.
    assert tg_format.render_html("ok, done — all set") == "ok, done — all set"


# ---- render_html: NUL safety (review findings #1 + #2) -----------------------

def test_render_nul_input_does_not_raise():
    # A literal NUL + digits previously indexed an unstashed placeholder -> IndexError.
    out = tg_format.render_html("see \x0099\x00 here")
    assert "99" not in out or "\x00" not in out  # NUL stripped, no crash
    assert "\x00" not in out


def test_render_nul_does_not_corrupt_other_content():
    # A crafted NUL sequence must not duplicate a real stashed code span.
    out = tg_format.render_html("\x000\x00 and `realcode`")
    assert out.count("<code>realcode</code>") == 1
    assert "\x00" not in out


def test_render_many_code_spans_restored_correctly():
    out = tg_format.render_html("`a` `b` `c`")
    assert out == "<code>a</code> <code>b</code> <code>c</code>"


# ---- split_html_safe ---------------------------------------------------------

def test_split_short_is_single():
    assert tg_format.split_html_safe("hello") == ["hello"]


def test_split_empty_is_empty():
    assert tg_format.split_html_safe("   ") == []


def test_split_long_under_hard_cap():
    chunks = tg_format.split_html_safe("para\n\n" * 2000)
    assert len(chunks) >= 2
    assert all(len(c) <= tg_format.TG_HARD_CAP for c in chunks)


def test_split_chunks_are_standalone_valid_html():
    # Regression #3: a long fenced code block split across chunks must close+reopen
    # the <pre><code> so EACH chunk is valid standalone HTML (not just balanced
    # <>/counts). Build a rendered <pre><code> body bigger than the soft limit.
    big = "x" * 9000
    rendered = f'<pre><code class="language-text">{big}</code></pre>'
    chunks = tg_format.split_html_safe(rendered, max_chars=3800)
    assert len(chunks) >= 2
    for c in chunks:
        assert _is_balanced(c), f"chunk not standalone-valid: {c[:60]!r}…"
        assert len(c) <= tg_format.TG_HARD_CAP


def test_split_blockquote_across_boundary_is_balanced():
    rendered = "<blockquote>" + ("line\n" * 2000) + "</blockquote>"
    chunks = tg_format.split_html_safe(rendered, max_chars=3000)
    assert len(chunks) >= 2
    assert all(_is_balanced(c) for c in chunks)


def test_split_reopens_with_original_attributes():
    big = "y" * 9000
    rendered = f'<pre><code class="language-python">{big}</code></pre>'
    chunks = tg_format.split_html_safe(rendered, max_chars=3800)
    # every chunk after the first reopens the code tag WITH its language attribute
    for c in chunks[1:]:
        assert c.startswith('<pre><code class="language-python">')
