"""Tests for the fast conversational lane (latency optimization).

The fast lane answers tool-free messages with ONE direct MiniMax-M3 call
(thinking disabled, SOUL voice) instead of cold-starting the ~515KB Hermes
`cli.py` subprocess (~2.7s) + a ~6s 17K-token reasoning turn. It is an
"answer-or-defer" router: if it can fully and correctly answer right now with no
tools, it returns the reply; otherwise it returns None and the caller falls back
to the full Hermes path. It is FAIL-SAFE: any error -> None (defer), never raise
(except for caller-contract violations: empty message / missing key).

All collaborators are injected (a fake requests.Session) — no network.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from fast_lane import fast_reply, contains_url, DEFER_SENTINEL  # noqa: E402


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeSession:
    """Mimics requests.Session.post(url, json=, headers=, timeout=)."""

    def __init__(self, resp=None, exc=None):
        self.resp = resp
        self.exc = exc
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return self.resp


def _ok(content):
    return {"choices": [{"message": {"content": content}}], "usage": {}}


# ---- happy path ----------------------------------------------------------

def test_answers_trivial_message_returns_text():
    s = FakeSession(FakeResp(payload=_ok("привет! чем могу помочь?")))
    out = fast_reply("привет", api_key="k", soul="voice", session=s)
    assert out == "привет! чем могу помочь?"


def test_strips_think_blocks_defensively():
    s = FakeSession(FakeResp(payload=_ok("<think>reasoning</think>привет")))
    assert fast_reply("привет", api_key="k", session=s) == "привет"


# ---- reasoning-off kill-switch is provider-aware -------------------------

def test_native_minimax_uses_thinking_kill_switch():
    """Default base_url (api.minimax.io) sends the MiniMax `thinking` kill-switch,
    NOT OpenRouter's `reasoning` field — the native path is byte-for-byte unchanged."""
    s = FakeSession(FakeResp(payload=_ok("ok")))
    fast_reply("привет", api_key="k", soul="voice", session=s)
    body = s.calls[0]["json"]
    assert body.get("thinking") == {"type": "disabled"}
    assert "reasoning" not in body


def test_openrouter_uses_reasoning_enabled_false():
    """When pointed at OpenRouter, the kill-switch becomes `reasoning:{enabled:false}`
    (OpenRouter rejects/ignores `thinking`) so the swapped M3 still answers fast."""
    s = FakeSession(FakeResp(payload=_ok("ok")))
    fast_reply(
        "привет", api_key="k", soul="voice", session=s,
        base_url="https://openrouter.ai/api/v1", model="minimax/minimax-m3",
    )
    body = s.calls[0]["json"]
    assert body.get("reasoning") == {"enabled": False}
    assert "thinking" not in body
    assert body["model"] == "minimax/minimax-m3"


# ---- defer (fall back to hermes) ----------------------------------------

def test_defer_sentinel_returns_none():
    s = FakeSession(FakeResp(payload=_ok(DEFER_SENTINEL)))
    assert fast_reply("summarize my latest email", api_key="k", session=s) is None


def test_defer_sentinel_embedded_returns_none():
    s = FakeSession(FakeResp(payload=_ok("hmm " + DEFER_SENTINEL + " ")))
    assert fast_reply("do x", api_key="k", session=s) is None


def test_empty_reply_defers():
    s = FakeSession(FakeResp(payload=_ok("   ")))
    assert fast_reply("привет", api_key="k", session=s) is None


def test_capability_refusal_reply_defers_to_hermes():
    # Safety net: if the fast lane "answers" by admitting it lacks access/real-time
    # data, that message actually needs a tool — defer so Hermes can really do it.
    for refusal in (
        "я не вижу данные о погоде в реальном времени",
        "не могу отправить — мне нужен доступ к мессенджеру",
        "I don't have access to your email",
        "I can't access real-time data right now",
    ):
        s = FakeSession(FakeResp(payload=_ok(refusal)))
        assert fast_reply("do something", api_key="k", session=s) is None, refusal


def test_normal_answer_not_falsely_flagged_as_refusal():
    s = FakeSession(FakeResp(payload=_ok("конечно, могу помочь — вот три идеи: ...")))
    assert fast_reply("придумай идеи", api_key="k", session=s) is not None


# ---- fail-safe: any transport/model error -> defer, never raise ----------

def test_http_error_returns_none():
    s = FakeSession(FakeResp(status=500, text="boom"))
    assert fast_reply("привет", api_key="k", session=s) is None


def test_network_exception_returns_none():
    s = FakeSession(exc=RuntimeError("connection reset"))
    assert fast_reply("привет", api_key="k", session=s) is None


def test_malformed_body_returns_none():
    s = FakeSession(FakeResp(payload={"base_resp": {"status_code": 1, "status_msg": "bad"}}))
    assert fast_reply("привет", api_key="k", session=s) is None


def test_non_json_body_returns_none():
    s = FakeSession(FakeResp(payload=None, text="<html>gateway</html>"))
    assert fast_reply("привет", api_key="k", session=s) is None


# ---- request shape: pinned model, thinking off, cache-friendly order -----

def test_request_pins_model_disables_thinking_and_orders_prefix():
    s = FakeSession(FakeResp(payload=_ok("hi")))
    fast_reply("привет", api_key="k", soul="SOULTEXT", model="MiniMax-M3", session=s)
    call = s.calls[0]
    body = call["json"]
    # pin the model — only M3 honors thinking-disabled (M2.x silently ignores it)
    assert body["model"] == "MiniMax-M3"
    assert body["thinking"] == {"type": "disabled"}
    # cache-friendly: static system FIRST (carries the SOUL voice), dynamic user LAST
    assert body["messages"][0]["role"] == "system"
    assert "SOULTEXT" in body["messages"][0]["content"]
    assert body["messages"][-1] == {"role": "user", "content": "привет"}
    # auth + endpoint
    assert call["headers"]["Authorization"] == "Bearer k"
    assert call["url"].endswith("/chat/completions")


def test_uses_custom_base_url():
    s = FakeSession(FakeResp(payload=_ok("hi")))
    fast_reply("привет", api_key="k", base_url="https://example.test/v1", session=s)
    assert s.calls[0]["url"] == "https://example.test/v1/chat/completions"


# ---- caller-contract violations DO raise ---------------------------------

def test_empty_message_raises():
    with pytest.raises(ValueError):
        fast_reply("   ", api_key="k", session=FakeSession())


def test_missing_api_key_raises():
    with pytest.raises(ValueError):
        fast_reply("привет", api_key="", session=FakeSession())


# ---- prefilter: obvious-heavy URL messages skip the probe entirely -------

def test_contains_url_detects_links():
    assert contains_url("сохрани https://instagram.com/p/abc")
    assert contains_url("youtube.com/watch?v=x")
    assert contains_url("www.foo.com")
    assert contains_url("check this http://a.b/c")


def test_contains_url_false_on_plain_chat():
    assert not contains_url("привет как дела")
    assert not contains_url("сколько будет 2 плюс 2")
    assert not contains_url("напомни мне завтра в 9")
    assert not contains_url("")
