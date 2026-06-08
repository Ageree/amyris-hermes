"""Tests for the MEDIUM lane: tool-free messages that need reasoning.

The stage-1 fast probe (thinking OFF) can route three ways:
  - answer directly                  -> fast lane (1 call, ~2s)
  - "[[THINK]]"  needs reasoning      -> medium lane: a 2nd M3 call with thinking
                                          ON but NO tools (faster than Hermes,
                                          better quality than thinking-off)
  - "[[DEFER]]"  needs tools/data/act -> None -> Hermes heavy lane

fast_reply() orchestrates all of this and still returns str|None (None = defer
to Hermes), so the worker integration is unchanged.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from fast_lane import fast_reply, DEFER_SENTINEL, THINK_SENTINEL  # noqa: E402


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class SeqSession:
    """Returns queued responses in order, repeating the last one."""

    def __init__(self, resps):
        self.resps = list(resps)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.resps.pop(0) if len(self.resps) > 1 else self.resps[0]


def _ok(content):
    return {"choices": [{"message": {"content": content}}], "usage": {}}


def test_think_sentinel_triggers_second_thinking_call():
    s = SeqSession([_r(THINK_SENTINEL), _r("вот решение: x = 2 или x = 3")])
    out = fast_reply("реши x^2-5x+6=0 и объясни", api_key="k", soul="voice", session=s)
    assert out == "вот решение: x = 2 или x = 3"
    assert len(s.calls) == 2
    # stage 1 has thinking DISABLED; stage 2 (medium) has thinking ON (no key)
    assert s.calls[0]["json"]["thinking"] == {"type": "disabled"}
    assert "thinking" not in s.calls[1]["json"]
    # both stages carry the user message + SOUL voice
    assert s.calls[1]["json"]["messages"][-1] == {"role": "user", "content": "реши x^2-5x+6=0 и объясни"}
    assert "voice" in s.calls[1]["json"]["messages"][0]["content"]


def test_think_then_defer_returns_none():
    s = SeqSession([_r(THINK_SENTINEL), _r(DEFER_SENTINEL)])
    assert fast_reply("x", api_key="k", session=s) is None
    assert len(s.calls) == 2


def test_think_then_capability_refusal_returns_none():
    s = SeqSession([_r(THINK_SENTINEL), _r("у меня нет доступа к интернету")])
    assert fast_reply("x", api_key="k", session=s) is None


def test_medium_disabled_makes_think_defer_to_hermes():
    s = SeqSession([_r(THINK_SENTINEL)])
    assert fast_reply("x", api_key="k", session=s, medium=False) is None
    assert len(s.calls) == 1  # no second call


def test_medium_call_uses_think_timeout_and_tokens():
    s = SeqSession([_r(THINK_SENTINEL), _r("ok")])
    fast_reply("x", api_key="k", session=s, timeout=6.0, think_timeout=25.0, think_max_tokens=2048)
    assert s.calls[0]["timeout"] == 6.0
    assert s.calls[1]["timeout"] == 25.0
    assert s.calls[1]["json"]["max_tokens"] == 2048


def test_dangling_unterminated_think_block_does_not_leak():
    # truncated reasoning (no closing tag) must be stripped, not returned as answer
    s = SeqSession([_r("<think>reasoning that got cut off mid")])
    assert fast_reply("x", api_key="k", session=s) is None


def test_plain_answer_still_one_call():
    s = SeqSession([_r("привет! чем помочь?")])
    assert fast_reply("привет", api_key="k", session=s) == "привет! чем помочь?"
    assert len(s.calls) == 1


def _r(content):
    return FakeResp(payload=_ok(content))
