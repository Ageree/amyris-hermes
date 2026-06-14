"""Channel layer unit tests (M2): Protocol conformance, registry, both adapters.

tg_format (render/split) lives in test_tg_format.py; the TelegramClient HTTP wiring
in test_telegram_client.py. This file covers OutboundResult, the Channel Protocol,
ChannelRegistry.from_config, and the Sendblue/Telegram channel ADAPTERS. Network-free.
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


# ---- TelegramChannel (adapter; tg_format/client tested in their own files) ----

def test_telegram_render_delegates_to_render_html():
    assert TelegramChannel(MagicMock()).render("**b** _i_ `c`") == "<b>b</b> <i>i</i> <code>c</code>"


def test_telegram_split_returns_chunks_under_cap():
    out = TelegramChannel(MagicMock()).split("y" * 9000)
    assert len(out) >= 3


def test_telegram_send_message_forwards_address_and_body():
    client = MagicMock()
    client.send_message.return_value = {"result": {"message_id": 77}}
    res = TelegramChannel(client).send_message("555", "<b>hi</b>")
    assert client.send_message.call_args.args == ("555", "<b>hi</b>")
    assert res.ok is True and res.provider_id == "77"


def test_telegram_send_message_empty_not_sent():
    client = MagicMock()
    res = TelegramChannel(client).send_message("555", "   ")
    assert res.ok is False
    client.send_message.assert_not_called()


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
