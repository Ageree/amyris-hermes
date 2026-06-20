"""Unit tests for the shared rich-message parser (channels/rich.py).

Covers every part type, multi-part ordering, reaction-then-text, the poll fence,
markdown AND bare image URLs, the no-directive back-compat path, a non-image URL
staying inline, and whitespace-only text being dropped.
"""
from __future__ import annotations

from channels.rich import (
    FilePart,
    ImagePart,
    PollPart,
    ReactionPart,
    TextPart,
    VoicePart,
    parse_rich,
)


# --- frozen-dataclass shape -------------------------------------------------

def test_dataclasses_are_frozen_and_immutable():
    import dataclasses
    import pytest

    t = TextPart("hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.text = "bye"  # type: ignore[misc]


def test_part_fields():
    assert TextPart("x").text == "x"
    assert ImagePart("u").src == "u"
    assert FilePart("u").name is None
    assert FilePart("u", "doc.pdf").name == "doc.pdf"
    assert VoicePart("u").src == "u"
    assert ReactionPart("❤️").emoji == "❤️"
    p = PollPart("q", ("a", "b"))
    assert p.question == "q" and p.options == ("a", "b")


# --- back-compat: no directives --------------------------------------------

def test_plain_prose_is_single_textpart():
    reply = "hey, here is your answer. nothing fancy at all."
    assert parse_rich(reply) == [TextPart(reply)]


def test_none_and_whitespace_only():
    assert parse_rich(None) == []
    assert parse_rich("   \n  \t ") == []


# --- reactions --------------------------------------------------------------

def test_leading_reaction_only():
    assert parse_rich("[[react:❤️]]") == [ReactionPart("❤️")]


def test_reaction_then_text():
    parts = parse_rich("[[react:👍]] sounds good to me")
    assert parts == [ReactionPart("👍"), TextPart("sounds good to me")]


def test_multiple_leading_reactions():
    parts = parse_rich("[[react:❤️]][[react:👍]] done")
    assert parts == [ReactionPart("❤️"), ReactionPart("👍"), TextPart("done")]


def test_reaction_not_leading_stays_text():
    # A react token in the MIDDLE of prose is not a leading directive -> stays text.
    parts = parse_rich("here is [[react:❤️]] inline")
    assert parts == [TextPart("here is [[react:❤️]] inline")]


# --- images -----------------------------------------------------------------

def test_markdown_image():
    parts = parse_rich("look ![cat](https://x.com/cat.png) cute")
    assert parts == [
        TextPart("look"),
        ImagePart("https://x.com/cat.png"),
        TextPart("cute"),
    ]


def test_bare_image_url():
    parts = parse_rich("see https://x.com/pic.jpg here")
    assert parts == [
        TextPart("see"),
        ImagePart("https://x.com/pic.jpg"),
        TextPart("here"),
    ]


def test_bare_image_url_with_query_string():
    parts = parse_rich("https://x.com/a.webp?token=abc trailing")
    assert parts == [
        ImagePart("https://x.com/a.webp?token=abc"),
        TextPart("trailing"),
    ]


def test_image_alone():
    assert parse_rich("https://x.com/a.gif") == [ImagePart("https://x.com/a.gif")]


def test_non_image_url_stays_inline_text():
    reply = "check https://example.com/page for details"
    assert parse_rich(reply) == [TextPart(reply)]


def test_multiple_images_in_order():
    parts = parse_rich(
        "one ![a](https://x.com/1.png) two https://x.com/2.jpeg three"
    )
    assert parts == [
        TextPart("one"),
        ImagePart("https://x.com/1.png"),
        TextPart("two"),
        ImagePart("https://x.com/2.jpeg"),
        TextPart("three"),
    ]


# --- markdown links: image-extension URL inside a link must NOT be shredded ---

def test_markdown_link_with_image_ext_stays_intact():
    # A markdown LINK whose URL ends in an image extension must stay one opaque
    # TextPart, NOT be split into '[click](' + ImagePart + ')'.
    reply = "[click](https://example.com/banner.png)"
    assert parse_rich(reply) == [TextPart("[click](https://example.com/banner.png)")]


def test_markdown_link_inline_keeps_link_as_text():
    reply = "see [the docs](https://docs.example.com/guide.png) for info"
    assert parse_rich(reply) == [TextPart(reply)]


def test_markdown_image_still_parses_as_image():
    assert parse_rich("![alt](https://x/a.png)") == [ImagePart("https://x/a.png")]


def test_mixed_image_and_bare_url_still_splits():
    parts = parse_rich("one ![a](https://x/1.png) two https://x/2.jpeg three")
    assert parts == [
        TextPart("one"),
        ImagePart("https://x/1.png"),
        TextPart("two"),
        ImagePart("https://x/2.jpeg"),
        TextPart("three"),
    ]


# --- poll fence -------------------------------------------------------------

def test_poll_fence():
    reply = "```poll\nfavorite color?\nred\ngreen\nblue\n```"
    assert parse_rich(reply) == [
        PollPart("favorite color?", ("red", "green", "blue"))
    ]


def test_text_then_poll_then_text():
    reply = "vote now:\n```poll\npick one\na\nb\n```\nthanks!"
    assert parse_rich(reply) == [
        TextPart("vote now:"),
        PollPart("pick one", ("a", "b")),
        TextPart("thanks!"),
    ]


def test_malformed_poll_kept_as_text():
    # A fence with only a question (no options) is malformed -> not a PollPart.
    reply = "```poll\nlonely question\n```"
    parts = parse_rich(reply)
    assert not any(isinstance(p, PollPart) for p in parts)
    assert len(parts) == 1 and isinstance(parts[0], TextPart)


# --- ordering across all part kinds ----------------------------------------

def test_multiple_parts_in_order():
    reply = (
        "[[react:🔥]] here you go ![chart](https://x.com/c.png) "
        "and a quick poll:\n```poll\nship it?\nyes\nno\n```\ndone"
    )
    assert parse_rich(reply) == [
        ReactionPart("🔥"),
        TextPart("here you go"),
        ImagePart("https://x.com/c.png"),
        TextPart("and a quick poll:"),
        PollPart("ship it?", ("yes", "no")),
        TextPart("done"),
    ]


def test_whitespace_only_between_parts_dropped():
    # The whitespace between image and poll must NOT become an empty TextPart.
    reply = "![a](https://x.com/a.png)\n\n```poll\nq\no1\no2\n```"
    parts = parse_rich(reply)
    assert parts == [
        ImagePart("https://x.com/a.png"),
        PollPart("q", ("o1", "o2")),
    ]
    assert all(not (isinstance(p, TextPart) and not p.text.strip()) for p in parts)
