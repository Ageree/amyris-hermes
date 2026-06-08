"""Worker integration tests for the fast conversational lane.

process_one tries the fast lane FIRST (when enabled, keyed, and the message is
not obvious-heavy); on a real answer it completes without ever cold-starting
Hermes. On a deferral (None) or any fast-lane error it falls back to the
unchanged Hermes path — so heavy/tool work is never broken by the optimization.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import WorkerConfig, process_one  # noqa: E402


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
    base = {"id": "msg1", "handle": "h1", "userNumber": "+1555",
            "text": "привет", "mediaUrl": None}
    base.update(over)
    return base


def test_fast_lane_short_circuits_hermes():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]  # claimNext, complete
    sendblue = MagicMock()
    run_fn = MagicMock()  # Hermes must NOT run
    fast_fn = MagicMock(return_value="привет! чем могу помочь?")
    did = process_one(convex, sendblue, _cfg_fast(), run_fn=run_fn, fast_fn=fast_fn)
    assert did is True
    fast_fn.assert_called_once()
    run_fn.assert_not_called()
    complete = convex.mutation.call_args_list[1]
    assert complete.args[0] == "messages:complete"
    assert complete.args[1]["reply"] == "привет! чем могу помочь?"
    assert sendblue.send_message.call_args.kwargs["content"] == "привет! чем могу помочь?"


def test_defers_to_hermes_when_fast_returns_none():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(text="summarize my latest email"), None]
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="hermes did the work")
    fast_fn = MagicMock(return_value=None)
    process_one(convex, sendblue, _cfg_fast(), run_fn=run_fn, fast_fn=fast_fn)
    fast_fn.assert_called_once()
    run_fn.assert_called_once()
    assert convex.mutation.call_args_list[1].args[0] == "messages:complete"
    assert sendblue.send_message.call_args.kwargs["content"] == "hermes did the work"


def test_fast_lane_exception_falls_back_to_hermes_without_failing():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="hermes fallback")
    fast_fn = MagicMock(side_effect=RuntimeError("fast lane blew up"))
    did = process_one(convex, sendblue, _cfg_fast(), run_fn=run_fn, fast_fn=fast_fn)
    assert did is True
    run_fn.assert_called_once()
    # a fast-lane crash is non-fatal: the message is completed by Hermes, not failed
    assert convex.mutation.call_args_list[1].args[0] == "messages:complete"
    assert sendblue.send_message.call_args.kwargs["content"] == "hermes fallback"


def test_url_message_skips_fast_lane_and_uses_hermes():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(text="сохрани https://youtube.com/watch?v=x"), None]
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="saved it")
    fast_fn = MagicMock()  # obvious-heavy -> must NOT be probed
    process_one(convex, sendblue, _cfg_fast(), run_fn=run_fn, fast_fn=fast_fn)
    fast_fn.assert_not_called()
    run_fn.assert_called_once()


def test_no_api_key_keeps_hermes_only_path():
    # production default (fast_fn=None) with no key configured: lane stays off
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="hermes")
    process_one(convex, sendblue, _cfg(), run_fn=run_fn)  # _cfg has no minimax key
    run_fn.assert_called_once()
    assert sendblue.send_message.call_args.kwargs["content"] == "hermes"


def test_disabled_flag_keeps_hermes_only_even_with_injected_fast_fn():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="hermes")
    fast_fn = MagicMock()
    process_one(convex, sendblue, _cfg_fast(fast_lane_enabled=False),
                run_fn=run_fn, fast_fn=fast_fn)
    fast_fn.assert_not_called()
    run_fn.assert_called_once()


def test_config_from_env_reads_fast_lane_settings(monkeypatch):
    for k in ("MINIMAX_API_KEY", "MINIMAX_BASE_URL", "MINIMAX_MODEL",
              "FAST_LANE_ENABLED", "POLL_INTERVAL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CONVEX_URL", "https://c.convex.cloud")
    monkeypatch.setenv("WORKER_SECRET", "ws")
    monkeypatch.setenv("SENDBLUE_API_KEY_ID", "ki")
    monkeypatch.setenv("SENDBLUE_API_SECRET_KEY", "sk")
    monkeypatch.setenv("SENDBLUE_FROM_NUMBER", "+1999")
    monkeypatch.setenv("ALLOWED_USER_NUMBER", "+1555")
    monkeypatch.setenv("MINIMAX_API_KEY", "envkey")
    cfg = WorkerConfig.from_env()
    assert cfg.minimax_api_key == "envkey"
    assert cfg.minimax_model == "MiniMax-M3"
    assert cfg.fast_lane_enabled is True
    # adaptive polling: fast active pickup, back off to a larger idle interval
    assert cfg.poll_interval == 0.5
    assert cfg.idle_poll_interval == 3.0


def test_config_from_env_fast_lane_can_be_disabled(monkeypatch):
    for k, v in {
        "CONVEX_URL": "https://c.convex.cloud", "WORKER_SECRET": "ws",
        "SENDBLUE_API_KEY_ID": "ki", "SENDBLUE_API_SECRET_KEY": "sk",
        "SENDBLUE_FROM_NUMBER": "+1999", "ALLOWED_USER_NUMBER": "+1555",
        "FAST_LANE_ENABLED": "0",
    }.items():
        monkeypatch.setenv(k, v)
    assert WorkerConfig.from_env().fast_lane_enabled is False
