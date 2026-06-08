"""Worker integration: streaming fast lane, Poke-style multi-bubble, typing.

Exercises the PRODUCTION paths the older worker tests don't: the streaming fast
lane (bubbles emitted as generated, complete AFTER send), multi-bubble splitting
of a Hermes reply, the typing indicator lifecycle, pacing, and the kill-switches.
The streaming model call itself is covered in test_stream_fast_lane.py; here we
monkeypatch worker.stream_fast_reply to a fake to test the wiring.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import worker  # noqa: E402
from worker import WorkerConfig, process_one  # noqa: E402
from fast_lane import StreamResult  # noqa: E402


def _cfg(**over):
    base = dict(
        convex_url="https://dep.convex.cloud", worker_secret="wsecret",
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target="+1555", hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0,
    )
    base.update(over)
    return WorkerConfig(**base)


def _cfg_fast(**over):
    base = dict(minimax_api_key="mmkey", fast_lane_enabled=True)
    base.update(over)
    return _cfg(**base)


def _claim(**over):
    base = {"id": "msg1", "handle": "h1", "userNumber": "+1555", "text": "привет", "mediaUrl": None}
    base.update(over)
    return base


def _contents(sendblue):
    return [c.kwargs["content"] for c in sendblue.send_message.call_args_list]


def _typing_states(sendblue):
    return [c.kwargs.get("state") for c in sendblue.send_typing.call_args_list]


# ---- streaming fast lane -----------------------------------------------------

def test_streaming_path_sends_bubbles_and_completes_after(monkeypatch):
    def fake_stream(text, *, on_bubble, **kw):
        on_bubble("первое")
        on_bubble("второе")
        return StreamResult("первое\n\nвторое", emitted=2)

    monkeypatch.setattr(worker, "stream_fast_reply", fake_stream)
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]  # claim, complete (after send)
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock()  # Hermes must NOT run
    did = process_one(convex, sendblue, _cfg_fast(), run_fn=run_fn)
    assert did is True
    run_fn.assert_not_called()
    assert _contents(sendblue) == ["первое", "второе"]  # bubbles, in order
    complete = convex.mutation.call_args_list[1]
    assert complete.args[0] == "messages:complete"
    assert complete.args[1]["reply"] == "первое\n\nвторое"  # joined for history


def test_streaming_defer_falls_back_to_hermes(monkeypatch):
    monkeypatch.setattr(
        worker, "stream_fast_reply",
        lambda text, *, on_bubble, **kw: StreamResult(None, emitted=0, deferred=True),
    )
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(text="какая погода сейчас"), None]
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="hermes ответ")
    process_one(convex, sendblue, _cfg_fast(), run_fn=run_fn)
    run_fn.assert_called_once()
    assert _contents(sendblue) == ["hermes ответ"]


def test_streaming_complete_failure_keeps_bubbles_no_error_reply(monkeypatch):
    # complete fails AFTER bubbles were already sent: mark fail, but do NOT send
    # a second ERROR_REPLY (the user already has the real answer).
    def fake_stream(text, *, on_bubble, **kw):
        on_bubble("ответ")
        return StreamResult("ответ", emitted=1)

    monkeypatch.setattr(worker, "stream_fast_reply", fake_stream)
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), RuntimeError("complete down"), None]
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock()
    process_one(convex, sendblue, _cfg_fast(), run_fn=run_fn)
    assert _contents(sendblue) == ["ответ"]  # exactly one — no ERROR_REPLY
    calls = [c.args[0] for c in convex.mutation.call_args_list]
    assert calls == ["messages:claimNext", "messages:complete", "messages:fail"]
    run_fn.assert_not_called()


def test_streaming_error_with_nothing_sent_retries_nonstream(monkeypatch):
    monkeypatch.setattr(
        worker, "stream_fast_reply",
        lambda text, *, on_bubble, **kw: StreamResult(None, emitted=0, errored=True),
    )
    monkeypatch.setattr(worker, "fast_reply", lambda text, **kw: "non-stream спас")
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock()
    process_one(convex, sendblue, _cfg_fast(), run_fn=run_fn)
    run_fn.assert_not_called()  # cheap fast retry answered, no Hermes
    assert _contents(sendblue) == ["non-stream спас"]


# ---- multi-bubble (Hermes path) ----------------------------------------------

def test_hermes_reply_splits_into_bubbles():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="первая часть\n\nвторая часть")
    process_one(convex, sendblue, _cfg(), run_fn=run_fn)  # no key -> Hermes
    assert _contents(sendblue) == ["первая часть", "вторая часть"]


def test_multi_bubble_disabled_sends_single_message():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="часть1\n\nчасть2")
    process_one(convex, sendblue, _cfg(multi_bubble_enabled=False), run_fn=run_fn)
    sendblue.send_message.assert_called_once()
    assert sendblue.send_message.call_args.kwargs["content"] == "часть1\n\nчасть2"


def test_bubbles_are_paced_with_sleep_between():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="a\n\nb\n\nc")
    sleeps = []
    process_one(convex, sendblue, _cfg(bubble_delay=0.5), run_fn=run_fn,
                sleep_fn=lambda s: sleeps.append(s))
    assert _contents(sendblue) == ["a", "b", "c"]
    assert sleeps == [0.5, 0.5]  # 3 bubbles -> 2 inter-bubble pauses


def test_streaming_disabled_uses_nonstreaming_fast_lane(monkeypatch):
    monkeypatch.setattr(worker, "fast_reply", lambda text, **kw: "из non-stream")
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock()
    process_one(convex, sendblue, _cfg_fast(streaming_enabled=False), run_fn=run_fn)
    run_fn.assert_not_called()
    assert _contents(sendblue) == ["из non-stream"]


# ---- typing indicator --------------------------------------------------------

def test_typing_started_and_stopped_around_processing():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="ок")
    process_one(convex, sendblue, _cfg(), run_fn=run_fn)
    states = _typing_states(sendblue)
    assert states, "typing indicator should fire"
    assert states[0] == "start"
    assert states[-1] == "stop"


def test_typing_disabled_fires_no_typing():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    convex.query.return_value = []
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="ок")
    process_one(convex, sendblue, _cfg(typing_enabled=False), run_fn=run_fn)
    sendblue.send_typing.assert_not_called()


def test_empty_queue_starts_no_typing():
    convex = MagicMock()
    convex.mutation.return_value = None  # claimNext -> None
    sendblue = MagicMock()
    did = process_one(convex, sendblue, _cfg(), run_fn=MagicMock())
    assert did is False
    sendblue.send_typing.assert_not_called()
    sendblue.send_message.assert_not_called()


def test_config_from_env_reads_new_knobs(monkeypatch):
    for k in ("MULTI_BUBBLE_ENABLED", "BUBBLE_MAX_COUNT", "BUBBLE_DELAY",
              "TYPING_ENABLED", "STREAMING_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    for k, v in {
        "CONVEX_URL": "u", "WORKER_SECRET": "w", "SENDBLUE_API_KEY_ID": "k",
        "SENDBLUE_API_SECRET_KEY": "s", "SENDBLUE_FROM_NUMBER": "+1",
        "ALLOWED_USER_NUMBER": "+1",
    }.items():
        monkeypatch.setenv(k, v)
    cfg = WorkerConfig.from_env()
    assert cfg.multi_bubble_enabled is True
    assert cfg.typing_enabled is True
    assert cfg.streaming_enabled is True
    assert cfg.bubble_delay == 0.4  # batch-path human pacing (dataclass default is 0.0; streaming path never paces)
    assert cfg.bubble_max_count == 4


def test_kill_switches_can_disable_features(monkeypatch):
    for k, v in {
        "CONVEX_URL": "u", "WORKER_SECRET": "w", "SENDBLUE_API_KEY_ID": "k",
        "SENDBLUE_API_SECRET_KEY": "s", "SENDBLUE_FROM_NUMBER": "+1",
        "ALLOWED_USER_NUMBER": "+1", "MULTI_BUBBLE_ENABLED": "0",
        "TYPING_ENABLED": "0", "STREAMING_ENABLED": "0",
    }.items():
        monkeypatch.setenv(k, v)
    cfg = WorkerConfig.from_env()
    assert cfg.multi_bubble_enabled is False
    assert cfg.typing_enabled is False
    assert cfg.streaming_enabled is False
