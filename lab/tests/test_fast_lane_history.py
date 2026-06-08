"""Tests for conversation MEMORY in the fast lane.

The assistant was stateless — every inbound iMessage was a fresh call with only
[SOUL + this message], so follow-ups ("я у тебя спросил", "почему?") couldn't be
understood and fell through to the slow Hermes path (22-37s, often still wrong).
`fast_reply(history=[...])` splices prior turns BETWEEN the static system prompt
(cache prefix) and the current user message, so the lane can answer follow-ups
itself (~2s). History is a list of OpenAI-style {role, content} dicts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from fast_lane import fast_reply, THINK_SENTINEL  # noqa: E402


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
    def __init__(self, resps):
        self.resps = list(resps)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.resps.pop(0) if len(self.resps) > 1 else self.resps[0]


def _ok(content):
    return {"choices": [{"message": {"content": content}}], "usage": {}}


def _r(content):
    return FakeResp(payload=_ok(content))


HIST = [
    {"role": "user", "content": "как дела?"},
    {"role": "assistant", "content": "норм, устал немного. ты как?"},
]


def test_history_spliced_between_system_and_current_message():
    s = SeqSession([_r("ты спрашивал как у меня дела 🙂")])
    out = fast_reply("я у тебя спросил", api_key="k", soul="voice", history=HIST, session=s)
    assert out == "ты спрашивал как у меня дела 🙂"
    msgs = s.calls[0]["json"]["messages"]
    # system FIRST (cache prefix), then history in order, then current user LAST
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": "как дела?"}
    assert msgs[2] == {"role": "assistant", "content": "норм, устал немного. ты как?"}
    assert msgs[-1] == {"role": "user", "content": "я у тебя спросил"}
    assert len(msgs) == 4


def test_no_history_is_unchanged_two_message_shape():
    s = SeqSession([_r("привет!")])
    fast_reply("привет", api_key="k", soul="voice", session=s)
    msgs = s.calls[0]["json"]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user"]


def test_empty_history_list_is_unchanged():
    s = SeqSession([_r("привет!")])
    fast_reply("привет", api_key="k", soul="voice", history=[], session=s)
    assert [m["role"] for m in s.calls[0]["json"]["messages"]] == ["system", "user"]


def test_history_carried_into_medium_lane_call():
    # stage-1 routes [[THINK]] -> medium call must ALSO carry the history
    s = SeqSession([_r(THINK_SENTINEL), _r("вот подробный разбор...")])
    out = fast_reply("а почему так?", api_key="k", soul="voice", history=HIST, session=s)
    assert out == "вот подробный разбор..."
    msgs2 = s.calls[1]["json"]["messages"]
    assert msgs2[1] == {"role": "user", "content": "как дела?"}
    assert msgs2[-1] == {"role": "user", "content": "а почему так?"}
