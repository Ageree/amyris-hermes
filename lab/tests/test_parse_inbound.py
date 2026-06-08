"""Tests for the Sendblue inbound webhook parser (Task 3).

Import convention matches the existing lab tests: sys.path-insert the skeleton
source dir, then import the bare module name.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from sendblue_client import parse_inbound, InboundMessage

SAMPLE = {
    "content": "what is the H1 of example.com?",
    "number": "+15557654321",          # end-user (operator iPhone)
    "from_number": "+15557654321",
    "is_outbound": False,
    "message_handle": "abc-123",
    "media_url": "",
    "opted_out": False,
    "service": "iMessage",
    "sendblue_number": "+15550001111",
}


def test_parse_inbound_extracts_fields():
    msg = parse_inbound(SAMPLE)
    assert isinstance(msg, InboundMessage)
    assert msg.text == "what is the H1 of example.com?"
    assert msg.user_number == "+15557654321"
    assert msg.handle == "abc-123"
    assert msg.opted_out is False


def test_parse_inbound_rejects_outbound_echo():
    assert parse_inbound({**SAMPLE, "is_outbound": True}) is None


def test_parse_inbound_rejects_empty_text_and_optout():
    assert parse_inbound({**SAMPLE, "content": ""}) is None
    assert parse_inbound({**SAMPLE, "opted_out": True}) is None


def test_parse_inbound_rejects_missing_number():
    assert parse_inbound({**SAMPLE, "number": ""}) is None
    assert parse_inbound({**SAMPLE, "number": None}) is None


def test_parse_inbound_rejects_non_dict():
    assert parse_inbound(None) is None
    assert parse_inbound("not a dict") is None


def test_parse_inbound_carries_media_url():
    msg = parse_inbound({**SAMPLE, "media_url": "https://cdn/x.jpg"})
    assert msg is not None
    assert msg.media_url == "https://cdn/x.jpg"
