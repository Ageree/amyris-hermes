"""M3: process_one routes a claimed channel='telegram' row through TelegramChannel.

Proves the worker renders the reply as Bot API HTML, sends via the Telegram client
(NEVER Sendblue), routes to the claimed chat.id, and does NOT use the streaming
fast lane for Telegram (one batch message — the per-chat ~1/s limit). Network-free:
the TelegramClient is a MagicMock; TelegramChannel is the real adapter.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import worker  # noqa: E402
from worker import WorkerConfig, process_one  # noqa: E402
from channels import ChannelRegistry, TelegramChannel  # noqa: E402
from channels.sendblue_channel import SendblueChannel  # noqa: E402


def _cfg(**over):
    base = dict(
        convex_url="https://dep.convex.cloud", worker_secret="wsecret",
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target="+1OPERATOR", hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0, typing_enabled=False,
        quota_enabled=False,  # orthogonal to channel routing; see test_worker_quota
    )
    base.update(over)
    return WorkerConfig(**base)


def _cfg_fast(**over):
    base = dict(minimax_api_key="mmkey", fast_lane_enabled=True)
    base.update(over)
    return _cfg(**base)


def _tg_claim(**over):
    base = {"id": "m1", "handle": "tg:42", "userNumber": "999", "text": "привет",
            "mediaUrl": None, "channel": "telegram", "replyTarget": "555", "userId": "u1"}
    base.update(over)
    return base


def _registry():
    tg_client = MagicMock()
    tg_client.send_message.return_value = {"ok": True, "result": {"message_id": 1}}
    sb_client = MagicMock()
    # Pin classic mode: these tests assert the WORKER's render->split->send_message
    # routing (HTML via sendMessage), which is orthogonal to the rich-markdown
    # feature (covered in test_telegram_rich_markdown.py). worker.py is unchanged.
    reg = ChannelRegistry({
        "telegram": TelegramChannel(tg_client, rich_markdown=False),
        "imessage": SendblueChannel(sb_client),
    })
    return reg, tg_client, sb_client


def _convex(claim):
    convex = MagicMock()
    convex.mutation.side_effect = [claim, None]
    convex.query.return_value = []
    return convex


def test_telegram_row_replies_via_telegram_client_rendered_html():
    reg, tg_client, sb_client = _registry()
    convex = _convex(_tg_claim())
    process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value="**bold** and `code`"))
    # rendered to HTML and sent to the claimed chat.id via Telegram, NOT Sendblue
    tg_client.send_message.assert_called_once()
    addr, body = tg_client.send_message.call_args.args
    assert addr == "555"
    assert body == "<b>bold</b> and <code>code</code>"
    sb_client.send_message.assert_not_called()


def test_telegram_row_does_not_use_streaming_fast_lane(monkeypatch):
    # Even with streaming + fast lane enabled, a telegram row must use the
    # non-streaming (batch) path. Prove stream_fast_reply is never called.
    called = []
    monkeypatch.setattr(worker, "stream_fast_reply", lambda *a, **k: called.append(1))
    monkeypatch.setattr(worker, "fast_reply", lambda text, **kw: "fast batch ответ")
    reg, tg_client, sb_client = _registry()
    convex = _convex(_tg_claim())
    process_one(convex, reg, _cfg_fast(streaming_enabled=True), run_fn=MagicMock())
    assert called == [], "telegram must NOT use the streaming fast lane"
    tg_client.send_message.assert_called_once()
    assert tg_client.send_message.call_args.args == ("555", "fast batch ответ")


def test_telegram_send_failure_does_not_crash_loop():
    reg, tg_client, sb_client = _registry()
    tg_client.send_message.side_effect = RuntimeError("telegram 500")
    convex = _convex(_tg_claim())
    did = process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value="ok"))
    assert did is True  # best-effort: provider error swallowed, loop survives
    # still marked complete (the send is best-effort, the work is done)
    assert convex.mutation.call_args_list[1].args[0] == "messages:complete"


def test_telegram_typing_uses_chat_action(monkeypatch):
    reg, tg_client, sb_client = _registry()
    convex = _convex(_tg_claim())
    process_one(convex, reg, _cfg(typing_enabled=True), run_fn=MagicMock(return_value="ok"))
    # the typing keepalive fired a chat action against the claimed chat.id
    actions = [c.args for c in tg_client.send_chat_action.call_args_list]
    assert ("555", "typing") in actions
