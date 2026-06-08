"""Tests for the Poke-style multi-bubble splitter (pure function)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from bubbles import split_into_bubbles, was_truncated  # noqa: E402


def test_short_single_message_is_one_bubble():
    assert split_into_bubbles("привет! чем могу помочь?") == ["привет! чем могу помочь?"]


def test_empty_or_whitespace_returns_empty_list():
    assert split_into_bubbles("") == []
    assert split_into_bubbles("   \n  \n ") == []
    assert split_into_bubbles(None) == []  # type: ignore[arg-type]


def test_blank_line_paragraphs_become_separate_bubbles():
    out = split_into_bubbles("первое сообщение\n\nвторое сообщение\n\nтретье")
    assert out == ["первое сообщение", "второе сообщение", "третье"]


def test_multiple_blank_lines_collapse_to_one_boundary():
    out = split_into_bubbles("a\n\n\n\nb")
    assert out == ["a", "b"]


def test_single_newlines_inside_a_bubble_are_kept():
    # a soft newline (list-ish) stays within ONE bubble; only blank lines split
    out = split_into_bubbles("line one\nline two\n\nnext bubble")
    assert out == ["line one\nline two", "next bubble"]


def test_long_paragraph_splits_on_sentence_boundaries():
    s1 = "это первое предложение. " * 40  # ~ long, many sentence boundaries
    out = split_into_bubbles(s1.strip(), max_chars=200)
    assert len(out) > 1
    assert all(len(b) <= 200 for b in out)


def test_boundaryless_blob_is_hard_sliced_under_max_chars():
    out = split_into_bubbles("x" * 5000, max_chars=1200, max_bubbles=6)
    assert all(len(b) <= 1200 for b in out)
    # 5000 chars fit in 5 bubbles (1200*4 + 200) — nothing dropped under the ceiling
    assert sum(len(b) for b in out) == 5000
    assert not was_truncated(out)


def test_urls_are_not_split_mid_token():
    url = "https://example.com/very/long/path?q=1&r=2#frag"
    out = split_into_bubbles(f"открой {url} и скажи что там", max_chars=1000)
    assert any(url in b for b in out)
    # the url survives intact in exactly one bubble
    assert sum(b.count(url) for b in out) == 1


def test_caps_bubble_count_and_marks_truncation_only_past_budget():
    # 12 paragraphs but max_bubbles=4 -> capped, last marked (content dropped)
    text = "\n\n".join(f"п{i}" for i in range(12))
    out = split_into_bubbles(text, max_bubbles=4)
    assert len(out) == 4
    assert was_truncated(out)


def test_every_bubble_within_hard_cap():
    out = split_into_bubbles("y" * 10000, max_chars=1200, max_bubbles=4, hard_cap=1800)
    assert all(len(b) <= 1800 for b in out)
    assert len(out) == 4  # capped


def test_normal_two_point_reply_is_two_short_bubbles():
    reply = "сделал, всё готово\n\nнапиши если нужно что-то ещё"
    out = split_into_bubbles(reply)
    assert out == ["сделал, всё готово", "напиши если нужно что-то ещё"]
    assert all(len(b) < 120 for b in out)
