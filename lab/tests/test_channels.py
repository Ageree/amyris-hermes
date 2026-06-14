"""Channel layer unit tests (M2): Protocol conformance, registry, both impls,
Telegram HTML formatting + client resilience.

Network-free: SendblueClient/TelegramClient construction does no I/O; the
TelegramClient HTTP tests monkeypatch `requests.post` with a fake response. The
LIVE Telegram round-trip + deep Bot API 10.1 conformance land in M3.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import WorkerConfig  # noqa: E402
from channels import (  # noqa: E402
    Channel, ChannelRegistry, OutboundResult, SendblueChannel, TelegramChannel,
)
from channels import tg_format  # noqa: E402
import channels.telegram_client as tc_mod  # noqa: E402
from channels.telegram_client import TelegramClient  # noqa: E402


def _cfg(**over):
    base = dict(
        convex_url="u", worker_secret="w", sendblue_key_id="kid", sendblue_secret="sec",
        sendblue_from="+1999", reply_target="+1555", hermes_home="/h", hermes_dir="/d",
        python_bin="/p", bubble_max_count=4, bubble_max_chars=1200,
    )
    base.update(over)
    return WorkerConfig(**base)


# ---- OutboundResult ----------------------------------------------------------

def test_outbound_result_fields_and_frozen():
    r = OutboundResult(ok=True, provider_id="pid")
    assert r.ok is True and r.provider_id == "pid" and r.error is None
    with pytest.raises(Exception):
        r.ok = False  # frozen


# ---- Protocol conformance (acceptance #3: both impls satisfy the Protocol) ----

def test_both_impls_satisfy_channel_protocol():
    sb = SendblueChannel(MagicMock())
    tg = TelegramChannel(MagicMock())
    assert isinstance(sb, Channel)
    assert isinstance(tg, Channel)
    assert sb.kind == "imessage"
    assert tg.kind == "telegram"


# ---- ChannelRegistry ---------------------------------------------------------

def test_registry_from_config_builds_only_credentialed_channels():
    # Sendblue creds only -> imessage; no telegram token -> no telegram.
    reg = ChannelRegistry.from_config(_cfg())
    assert "imessage" in reg
    assert "telegram" not in reg
    assert reg.kinds() == ["imessage"]


def test_registry_from_config_includes_telegram_when_token_set():
    reg = ChannelRegistry.from_config(_cfg(telegram_bot_token="123:abc"))
    assert "imessage" in reg and "telegram" in reg
    assert isinstance(reg.get("telegram"), TelegramChannel)


def test_registry_from_config_telegram_only_when_no_sendblue():
    reg = ChannelRegistry.from_config(
        _cfg(sendblue_key_id="", sendblue_secret="", sendblue_from="", telegram_bot_token="t")
    )
    assert reg.kinds() == ["telegram"]


def test_registry_get_raises_for_missing_kind():
    reg = ChannelRegistry({"imessage": SendblueChannel(MagicMock())})
    with pytest.raises(KeyError):
        reg.get("telegram")


def test_registry_len_and_contains():
    reg = ChannelRegistry({"imessage": SendblueChannel(MagicMock())})
    assert len(reg) == 1
    assert "imessage" in reg and "telegram" not in reg


# ---- SendblueChannel ---------------------------------------------------------

def test_sendblue_render_is_plain_strip():
    assert SendblueChannel(MagicMock()).render("  **hi** there  ") == "**hi** there"


def test_sendblue_split_uses_bubbles_with_caps():
    ch = SendblueChannel(MagicMock(), max_bubbles=2, max_chars=10)
    out = ch.split("a" * 35)  # no boundaries -> hard sliced, capped to 2 bubbles
    assert len(out) == 2


def test_sendblue_send_message_forwards_to_number_and_content():
    client = MagicMock()
    client.send_message.return_value = {"message_handle": "h9"}
    res = SendblueChannel(client).send_message("+1ABC", "привет")
    assert client.send_message.call_args.kwargs == {"to_number": "+1ABC", "content": "привет"}
    assert res.ok is True and res.provider_id == "h9"


def test_sendblue_send_message_clamps_long_body():
    client = MagicMock()
    SendblueChannel(client, max_reply_chars=50).send_message("+1", "x" * 500)
    assert len(client.send_message.call_args.kwargs["content"]) == 50


def test_sendblue_send_message_empty_is_not_sent():
    client = MagicMock()
    res = SendblueChannel(client).send_message("+1", "   ")
    assert res.ok is False
    client.send_message.assert_not_called()


def test_sendblue_send_message_swallows_provider_error():
    client = MagicMock()
    client.send_message.side_effect = RuntimeError("sendblue 500")
    res = SendblueChannel(client).send_message("+1", "hi")
    assert res.ok is False and "500" in (res.error or "")  # best-effort, never raised


def test_sendblue_send_typing_forwards_state_and_duration():
    client = MagicMock()
    SendblueChannel(client).send_typing("+1", state="start", max_duration_ms=8000)
    args, kwargs = client.send_typing.call_args
    assert args == ("+1",)
    assert kwargs == {"state": "start", "max_duration_ms": 8000}


def test_sendblue_send_typing_swallows_error():
    client = MagicMock()
    client.send_typing.side_effect = RuntimeError("nope")
    assert SendblueChannel(client).send_typing("+1").ok is False


# ---- TelegramChannel ---------------------------------------------------------

def test_telegram_render_html():
    assert TelegramChannel(MagicMock()).render("**b** _i_ `c`") == "<b>b</b> <i>i</i> <code>c</code>"


def test_telegram_split_returns_chunks_under_cap():
    out = TelegramChannel(MagicMock()).split("y" * 9000)
    assert len(out) >= 3
    assert all(len(c) <= tg_format.TG_HARD_CAP for c in out)


def test_telegram_send_message_forwards_address_and_body():
    client = MagicMock()
    client.send_message.return_value = {"result": {"message_id": 77}}
    res = TelegramChannel(client).send_message("555", "<b>hi</b>")
    assert client.send_message.call_args.args == ("555", "<b>hi</b>")
    assert res.ok is True and res.provider_id == "77"


def test_telegram_send_message_swallows_error():
    client = MagicMock()
    client.send_message.side_effect = RuntimeError("tg 400")
    assert TelegramChannel(client).send_message("555", "hi").ok is False


def test_telegram_typing_start_fires_chat_action_stop_is_noop():
    client = MagicMock()
    ch = TelegramChannel(client)
    ch.send_typing("555", state="start")
    client.send_chat_action.assert_called_once_with("555", "typing")
    client.send_chat_action.reset_mock()
    ch.send_typing("555", state="stop")
    client.send_chat_action.assert_not_called()  # TG auto-clears; stop is a no-op


# ---- tg_format.render_html ---------------------------------------------------

def test_render_html_escapes_specials_in_prose():
    assert tg_format.render_html("a < b & c > d") == "a &lt; b &amp; c &gt; d"


def test_render_html_escapes_inside_inline_code():
    assert tg_format.render_html("use `a<b && c>d`") == "use <code>a&lt;b &amp;&amp; c&gt;d</code>"


def test_render_html_fenced_code_with_language():
    out = tg_format.render_html("```python\nprint(1<2)\n```")
    assert out == '<pre><code class="language-python">print(1&lt;2)</code></pre>'


def test_render_html_does_not_touch_emphasis_inside_code():
    assert tg_format.render_html("`**not bold**`") == "<code>**not bold**</code>"


def test_render_html_bold_and_italic():
    assert tg_format.render_html("**bold** and *italic*") == "<b>bold</b> and <i>italic</i>"


# ---- tg_format.split_html_safe ----------------------------------------------

def test_split_html_safe_short_is_single():
    assert tg_format.split_html_safe("hello") == ["hello"]


def test_split_html_safe_splits_long_under_cap():
    chunks = tg_format.split_html_safe("para\n\n" * 2000)
    assert len(chunks) >= 2
    assert all(len(c) <= tg_format.TG_HARD_CAP for c in chunks)


def test_split_html_safe_does_not_cut_inside_a_tag():
    # A long run with a tag straddling the soft boundary must not be cut mid-tag.
    text = ("x" * 3790) + "<b>boundarytag</b>" + ("y" * 3000)
    chunks = tg_format.split_html_safe(text, max_chars=3800)
    for c in chunks:
        # no chunk ends with a half-open tag
        assert c.count("<") == c.count(">")


# ---- TelegramClient (HTTP wiring; live round-trip is M3) ---------------------

class _Resp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_telegram_client_send_message_html_payload(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return _Resp(200, {"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(tc_mod.requests, "post", fake_post)
    TelegramClient("123:abc").send_message("555", "<b>hi</b>")
    url, payload = calls[0]
    assert url.endswith("/bot123:abc/sendMessage")
    assert payload["chat_id"] == "555"
    assert payload["parse_mode"] == "HTML"
    assert payload["link_preview_options"] == {"is_disabled": True}


def test_telegram_client_400_retries_without_parse_mode(monkeypatch):
    seq = [_Resp(400, text="bad entity"), _Resp(200, {"ok": True})]
    sent = []

    def fake_post(url, json=None, timeout=None):
        sent.append(json)
        return seq.pop(0)

    monkeypatch.setattr(tc_mod.requests, "post", fake_post)
    TelegramClient("t").send_message("555", "<b>broken")
    assert len(sent) == 2
    assert "parse_mode" in sent[0]
    assert "parse_mode" not in sent[1]  # plain-text retry


def test_telegram_client_429_honors_retry_after(monkeypatch):
    seq = [_Resp(429, {"parameters": {"retry_after": 2}}), _Resp(200, {"ok": True})]
    slept = []

    def fake_post(url, json=None, timeout=None):
        return seq.pop(0)

    monkeypatch.setattr(tc_mod.requests, "post", fake_post)
    TelegramClient("t", sleep_fn=lambda s: slept.append(s)).send_message("555", "hi")
    assert slept == [2.0]


def test_telegram_client_non_2xx_raises(monkeypatch):
    monkeypatch.setattr(tc_mod.requests, "post", lambda url, json=None, timeout=None: _Resp(500, text="boom"))
    with pytest.raises(RuntimeError):
        TelegramClient("t").send_message("555", "hi")


def test_telegram_client_send_chat_action(monkeypatch):
    calls = []
    monkeypatch.setattr(tc_mod.requests, "post",
                        lambda url, json=None, timeout=None: calls.append((url, json)) or _Resp(200, {"ok": True}))
    TelegramClient("t").send_chat_action("555", "typing")
    url, payload = calls[0]
    assert url.endswith("/sendChatAction")
    assert payload == {"chat_id": "555", "action": "typing"}


def test_telegram_client_requires_token():
    with pytest.raises(ValueError):
        TelegramClient("")
