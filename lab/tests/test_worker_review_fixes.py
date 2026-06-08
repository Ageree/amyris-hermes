"""Regression tests for the adversarial-review findings on the fast-lane change.

Covers: (1) fast-lane complete-mutation failure must degrade to `messages:fail`
not leave the message stuck; (2) a missing fast_lane module disables the lane
instead of crashing; (3) adaptive polling (fast when active, back off when idle);
(5) the fast-lane probe uses a tight timeout, not the 20s requests default;
(6) intents poll on a wall-clock interval, not every-N-iterations; (7) a non-M3
model is flagged (silently re-enables reasoning).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import worker  # noqa: E402
from worker import WorkerConfig, process_one, run_loop, ERROR_REPLY  # noqa: E402


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


# ---- Finding 1: fast-lane complete failure must not strand the message --------

def test_fast_lane_complete_failure_marks_fail_and_replies():
    convex = MagicMock()
    # claimNext -> claim ; complete -> RAISES ; fail -> ok
    convex.mutation.side_effect = [_claim(), RuntimeError("convex 500 on complete"), None]
    sendblue = MagicMock()
    run_fn = MagicMock()  # heavy lane must NOT run (message already answered once)
    fast_fn = MagicMock(return_value="answer")
    did = process_one(convex, sendblue, _cfg_fast(), run_fn=run_fn, fast_fn=fast_fn)
    assert did is True  # never raises out of process_one
    calls = [c.args[0] for c in convex.mutation.call_args_list]
    assert calls == ["messages:claimNext", "messages:complete", "messages:fail"]
    run_fn.assert_not_called()  # do NOT double-process via Hermes
    sendblue.send_message.assert_called_once()
    assert sendblue.send_message.call_args.kwargs["content"] == ERROR_REPLY


def test_fast_lane_complete_and_fail_both_down_does_not_raise():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), RuntimeError("complete down"), RuntimeError("fail down")]
    sendblue = MagicMock()
    fast_fn = MagicMock(return_value="answer")
    did = process_one(convex, sendblue, _cfg_fast(), run_fn=MagicMock(), fast_fn=fast_fn)
    assert did is True
    sendblue.send_message.assert_called_once()


# ---- Finding 2: unavailable fast_lane import disables the lane ----------------

def test_fast_lane_disabled_when_fast_reply_unavailable(monkeypatch):
    monkeypatch.setattr(worker, "fast_reply", None)
    assert worker._fast_lane_allowed(_cfg_fast(), "привет", None) is False
    # an explicitly injected fast_fn still works (tests / alternative callers)
    assert worker._fast_lane_allowed(_cfg_fast(), "привет", lambda t: "x") is True


# ---- Finding 5: tight, configurable probe timeout ----------------------------

def test_run_fast_lane_passes_probe_timeout(monkeypatch):
    captured = {}
    monkeypatch.setattr(worker, "fast_reply", lambda text, **kw: captured.update(kw) or "ok")
    out = worker._run_fast_lane("привет", _cfg_fast(fast_probe_timeout=4.0))
    assert out == "ok"
    assert captured["timeout"] == 4.0


def test_fast_probe_timeout_default_is_tight():
    assert _cfg_fast().fast_probe_timeout <= 8.0  # not the 20s requests default


# ---- Finding 3: adaptive polling ---------------------------------------------

def test_run_loop_backs_off_to_idle_after_consecutive_empties():
    cfg = _cfg(poll_interval=0.5, idle_poll_interval=3.0, idle_after=2)
    sleeps = []
    run_loop(cfg, convex=MagicMock(), sendblue=MagicMock(),
             process_fn=MagicMock(return_value=False), intent_fn=None,
             sleep_fn=lambda s: sleeps.append(s), max_iterations=4)
    assert sleeps == [0.5, 0.5, 3.0, 3.0]


def test_run_loop_resets_to_active_after_work():
    cfg = _cfg(poll_interval=0.5, idle_poll_interval=3.0, idle_after=1)
    sleeps = []
    run_loop(cfg, convex=MagicMock(), sendblue=MagicMock(),
             process_fn=MagicMock(side_effect=[False, False, True, False]), intent_fn=None,
             sleep_fn=lambda s: sleeps.append(s), max_iterations=4)
    assert sleeps == [0.5, 3.0, 0.5]


# ---- Finding 6: intents poll on a wall clock, not every-N-iterations ----------

def test_run_loop_polls_intents_on_wall_clock():
    cfg = _cfg(poll_interval=1.0, idle_after=99, intent_interval=5.0)
    clock = [0.0]
    intent_fn = MagicMock()
    run_loop(cfg, convex=MagicMock(), sendblue=MagicMock(),
             process_fn=MagicMock(return_value=False), intent_fn=intent_fn,
             sleep_fn=lambda s: clock.__setitem__(0, clock[0] + s),
             time_fn=lambda: clock[0], max_iterations=8)
    # fires at t=0 (first) and again once t>=5 is reached -> exactly 2 calls
    assert intent_fn.call_count == 2


# ---- Finding 7: non-M3 model flagged -----------------------------------------

def test_fast_lane_model_ok_only_for_m3():
    assert worker._fast_lane_model_ok(_cfg_fast(minimax_model="MiniMax-M3")) is True
    assert worker._fast_lane_model_ok(_cfg_fast(minimax_model="MiniMax-M2.7")) is False


# ---- Medium lane: worker forwards the think params to fast_reply --------------

def test_run_fast_lane_passes_medium_params(monkeypatch):
    captured = {}
    monkeypatch.setattr(worker, "fast_reply", lambda text, **kw: captured.update(kw) or "ok")
    worker._run_fast_lane("x", _cfg_fast(
        fast_probe_timeout=6.0, medium_lane_enabled=True,
        medium_timeout=25.0, medium_max_tokens=2048,
    ))
    assert captured["timeout"] == 6.0
    assert captured["medium"] is True
    assert captured["think_timeout"] == 25.0
    assert captured["think_max_tokens"] == 2048


def test_config_from_env_medium_defaults(monkeypatch):
    for k in ("MEDIUM_LANE_ENABLED", "MEDIUM_TIMEOUT", "MEDIUM_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in {
        "CONVEX_URL": "u", "WORKER_SECRET": "w", "SENDBLUE_API_KEY_ID": "k",
        "SENDBLUE_API_SECRET_KEY": "s", "SENDBLUE_FROM_NUMBER": "+1",
        "ALLOWED_USER_NUMBER": "+1",
    }.items():
        monkeypatch.setenv(k, v)
    cfg = WorkerConfig.from_env()
    assert cfg.medium_lane_enabled is True
    assert cfg.medium_timeout == 25.0
    assert cfg.medium_max_tokens == 2048
