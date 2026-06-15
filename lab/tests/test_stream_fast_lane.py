"""Tests for the STREAMING fast lane (incremental Poke-style bubble emit).

A fake session yields SSE lines from `iter_lines()`; bubbles are captured via the
on_bubble sink. Covers: direct answer, multi-paragraph early emit, [[DEFER]] and
[[THINK]] routing, refusal-defer, HTTP error, deadline, and cache-friendly body.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from fast_lane import stream_fast_reply, DEFER_SENTINEL, THINK_SENTINEL  # noqa: E402


def _sse(content_pieces):
    """Build SSE 'data:' lines (bytes) for a sequence of content deltas + [DONE]."""
    import json as _json
    lines = []
    for p in content_pieces:
        lines.append(("data: " + _json.dumps({"choices": [{"delta": {"content": p}}]})).encode())
    lines.append(b"data: [DONE]")
    return lines


class StreamResp:
    def __init__(self, lines, status=200):
        self.status_code = status
        self._lines = lines
        self.closed = False

    def iter_lines(self):
        for ln in self._lines:
            yield ln

    def close(self):
        self.closed = True


class FakeStreamSession:
    """Queues responses; records each post (incl. the stream kwarg)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None, stream=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout, "stream": stream})
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


def _collect():
    got = []
    return got, got.append


# ---- direct answer ----------------------------------------------------------

def test_streaming_direct_answer_emits_one_bubble():
    s = FakeStreamSession([StreamResp(_sse(["прив", "ет! ", "чем помочь?"]))])
    bubbles, sink = _collect()
    res = stream_fast_reply("привет", on_bubble=sink, api_key="k", soul="voice", session=s)
    assert bubbles == ["привет! чем помочь?"]
    assert res.emitted == 1
    assert res.reply == "привет! чем помочь?"
    assert res.deferred is False and res.errored is False
    # stage-1 streams with thinking disabled + stream true + cache-friendly order
    body = s.calls[0]["json"]
    assert body["stream"] is True
    assert body["thinking"] == {"type": "disabled"}
    assert body["messages"][-1] == {"role": "user", "content": "привет"}
    assert "voice" in body["messages"][0]["content"]
    assert s.calls[0]["stream"] is True


def test_streaming_openrouter_uses_reasoning_enabled_false():
    """LIVE PROD PATH: streaming stage-1 against OpenRouter sends the gateway's own
    kill-switch `reasoning:{enabled:false}` — NOT MiniMax's native `thinking` (which
    OpenRouter ignores, tripling reasoning tokens). Guards _apply_reasoning_off on the
    streaming branch (prod runs STREAMING_ENABLED=True over openrouter.ai)."""
    s = FakeStreamSession([StreamResp(_sse(["прив", "ет!"]))])
    bubbles, sink = _collect()
    res = stream_fast_reply(
        "привет", on_bubble=sink, api_key="k", soul="voice",
        base_url="https://openrouter.ai/api/v1", model="minimax/minimax-m3", session=s,
    )
    assert bubbles == ["привет!"]
    assert res.deferred is False and res.errored is False
    body = s.calls[0]["json"]
    assert body["stream"] is True
    assert body["reasoning"] == {"enabled": False}
    assert "thinking" not in body


def test_streaming_multiparagraph_emits_each_paragraph_as_a_bubble():
    pieces = ["первое сообщение", "\n\n", "второе ", "сообщение", "\n\n", "третье"]
    s = FakeStreamSession([StreamResp(_sse(pieces))])
    bubbles, sink = _collect()
    res = stream_fast_reply("x", on_bubble=sink, api_key="k", session=s)
    assert bubbles == ["первое сообщение", "второе сообщение", "третье"]
    assert res.emitted == 3
    assert res.reply == "первое сообщение\n\nвторое сообщение\n\nтретье"


def test_streaming_first_paragraph_emitted_before_stream_ends():
    # the first bubble must be emitted as soon as its boundary closes, not at end
    emitted_order = []
    pieces = ["перв", "ое", "\n\n", "втор", "ое"]
    s = FakeStreamSession([StreamResp(_sse(pieces))])
    stream_fast_reply("x", on_bubble=lambda b: emitted_order.append(b), api_key="k", session=s)
    assert emitted_order == ["первое", "второе"]


# ---- routing ----------------------------------------------------------------

def test_streaming_defer_sentinel_returns_deferred_no_emit():
    s = FakeStreamSession([StreamResp(_sse(["[[", "DEFER", "]]"]))])
    bubbles, sink = _collect()
    res = stream_fast_reply("какая погода сейчас", on_bubble=sink, api_key="k", session=s)
    assert bubbles == []
    assert res.deferred is True
    assert res.reply is None
    assert res.emitted == 0


def test_streaming_think_sentinel_runs_medium_and_emits():
    # stage-1 streams [[THINK]]; medium (non-stream) returns the answer
    import json as _json
    medium = StreamResp([("data: " + _json.dumps(
        {"choices": [{"delta": {}}]})).encode()])  # unused shape; medium uses .post().json()

    class MixedSession:
        def __init__(self):
            self.calls = []
            self._stage1 = StreamResp(_sse(["[[THINK]]"]))

        def post(self, url, json=None, headers=None, timeout=None, stream=None):
            self.calls.append({"json": json, "stream": stream})
            if stream:
                return self._stage1

            class R:
                status_code = 200

                def json(self_inner):
                    return {"choices": [{"message": {"content": "вот решение: x=2"}}]}
            return R()

    s = MixedSession()
    bubbles, sink = _collect()
    res = stream_fast_reply("реши уравнение", on_bubble=sink, api_key="k", session=s, medium=True)
    assert bubbles == ["вот решение: x=2"]
    assert res.emitted == 1
    assert res.reply == "вот решение: x=2"
    # medium call had thinking ON (no kill-switch) and was NOT a stream
    medium_call = next(c for c in s.calls if not c["stream"])
    assert "thinking" not in medium_call["json"]


def test_streaming_think_with_medium_disabled_defers():
    s = FakeStreamSession([StreamResp(_sse(["[[THINK]]"]))])
    bubbles, sink = _collect()
    res = stream_fast_reply("x", on_bubble=sink, api_key="k", session=s, medium=False)
    assert res.deferred is True
    assert bubbles == []


# ---- safety -----------------------------------------------------------------

def test_streaming_refusal_only_defers_with_nothing_sent():
    s = FakeStreamSession([StreamResp(_sse(["у меня нет доступа к интернету"]))])
    bubbles, sink = _collect()
    res = stream_fast_reply("какая погода", on_bubble=sink, api_key="k", session=s)
    assert bubbles == []
    assert res.deferred is True


def test_streaming_http_error_returns_errored():
    s = FakeStreamSession([StreamResp([], status=429)])
    bubbles, sink = _collect()
    res = stream_fast_reply("x", on_bubble=sink, api_key="k", session=s)
    assert res.errored is True
    assert res.emitted == 0
    assert bubbles == []


def test_streaming_empty_stream_defers():
    s = FakeStreamSession([StreamResp([b"data: [DONE]"])])
    bubbles, sink = _collect()
    res = stream_fast_reply("x", on_bubble=sink, api_key="k", session=s)
    assert res.deferred is True
    assert bubbles == []


def test_streaming_response_is_closed():
    resp = StreamResp(_sse(["ок"]))
    s = FakeStreamSession([resp])
    _, sink = _collect()
    stream_fast_reply("x", on_bubble=sink, api_key="k", session=s)
    assert resp.closed is True


def test_streaming_deadline_stops_without_emitting_partial_paragraph():
    # a single long paragraph still streaming when the deadline hits -> defer,
    # nothing sent (no truncated bubble)
    ticks = iter([0.0, 0.0, 100.0, 100.0, 100.0])

    def clock():
        try:
            return next(ticks)
        except StopIteration:
            return 100.0

    s = FakeStreamSession([StreamResp(_sse(["это длинный ответ ", "который не успел"]))])
    bubbles, sink = _collect()
    res = stream_fast_reply("x", on_bubble=sink, api_key="k", session=s, clock=clock, timeout=10.0)
    assert bubbles == []
    assert res.deferred is True


def test_streaming_answer_starting_with_bracket_is_not_mistaken_for_sentinel():
    s = FakeStreamSession([StreamResp(_sse(["[", "смотри", "] вот тут"]))])
    bubbles, sink = _collect()
    res = stream_fast_reply("x", on_bubble=sink, api_key="k", session=s)
    assert bubbles == ["[смотри] вот тут"]
    assert res.emitted == 1


def test_streaming_caps_total_bubbles_across_paragraphs():
    # a model that blank-lines every line: 6 paragraphs, budget 4 -> exactly 4
    # bubbles (first 3 streamed, paragraphs 4-6 combined into the last).
    pieces = []
    for i in range(1, 7):
        pieces.append(f"строка {i}")
        if i < 6:
            pieces.append("\n\n")
    s = FakeStreamSession([StreamResp(_sse(pieces))])
    bubbles, sink = _collect()
    res = stream_fast_reply("x", on_bubble=sink, api_key="k", session=s, max_bubbles=4)
    assert res.emitted == 4
    assert len(bubbles) == 4
    assert bubbles[:3] == ["строка 1", "строка 2", "строка 3"]
    # the tail paragraphs are combined into the final bubble (nothing dropped)
    for i in (4, 5, 6):
        assert f"строка {i}" in bubbles[3]


def test_streaming_budget_one_sends_single_message():
    pieces = ["часть один", "\n\n", "часть два", "\n\n", "часть три"]
    s = FakeStreamSession([StreamResp(_sse(pieces))])
    bubbles, sink = _collect()
    res = stream_fast_reply("x", on_bubble=sink, api_key="k", session=s, max_bubbles=1)
    assert res.emitted == 1
    assert "часть один" in bubbles[0] and "часть три" in bubbles[0]


def test_streaming_raises_on_empty_message_or_missing_key():
    _, sink = _collect()
    for kwargs in ({"message": "", "api_key": "k"}, {"message": "hi", "api_key": ""}):
        try:
            stream_fast_reply(on_bubble=sink, session=FakeStreamSession([StreamResp([])]), **kwargs)
            assert False, "expected ValueError"
        except ValueError:
            pass
