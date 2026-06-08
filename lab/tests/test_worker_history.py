"""Worker-side conversation MEMORY + per-message observability.

The worker fetches the user's recent turns from Convex (messages:recentForUser),
builds an OpenAI-style history list, and threads it into BOTH the fast lane and
the Hermes fallback so follow-ups are understood. It also logs, per message,
which lane answered and the wall-clock latency (the worker previously logged only
failures — we were blind to whether the fast lane was even firing).
"""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import worker  # noqa: E402
from worker import WorkerConfig, process_one, _fetch_history  # noqa: E402


def _cfg(**over):
    base = dict(
        convex_url="https://dep.convex.cloud", worker_secret="wsecret",
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target="+1555", hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0,
    )
    base.update(over)
    return WorkerConfig(**base)


def _claim(**over):
    base = {"id": "m1", "handle": "h1", "userNumber": "+1555", "text": "я у тебя спросил", "mediaUrl": None}
    base.update(over)
    return base


# ---- _fetch_history: Convex rows -> OpenAI messages --------------------------

def test_fetch_history_builds_alternating_messages():
    convex = MagicMock()
    convex.query.return_value = [
        {"text": "как дела?", "reply": "норм, устал немного"},
        {"text": "почему устал?", "reply": "мало спал"},
    ]
    out = _fetch_history(convex, _cfg(), "+1555")
    assert out == [
        {"role": "user", "content": "как дела?"},
        {"role": "assistant", "content": "норм, устал немного"},
        {"role": "user", "content": "почему устал?"},
        {"role": "assistant", "content": "мало спал"},
    ]
    # queried the right function with the worker secret + user + limit
    args = convex.query.call_args
    assert args.args[0] == "messages:recentForUser"
    assert args.args[1]["userNumber"] == "+1555"
    assert args.args[1]["workerSecret"] == "wsecret"
    assert args.args[1]["limit"] == _cfg().history_turns


def test_fetch_history_skips_empty_and_caps_length():
    convex = MagicMock()
    convex.query.return_value = [
        {"text": "ok", "reply": ""},          # no reply -> skip whole turn
        {"text": "", "reply": "orphan"},      # no text -> skip
        {"text": "x" * 5000, "reply": "y" * 5000},
    ]
    out = _fetch_history(convex, _cfg(history_char_cap=100), "+1555")
    assert len(out) == 2  # only the third turn survived
    assert len(out[0]["content"]) == 100
    assert len(out[1]["content"]) == 100


def test_fetch_history_best_effort_returns_empty_on_error():
    convex = MagicMock()
    convex.query.side_effect = RuntimeError("convex down")
    assert _fetch_history(convex, _cfg(), "+1555") == []


def test_fetch_history_disabled_returns_empty_without_query():
    convex = MagicMock()
    assert _fetch_history(convex, _cfg(history_enabled=False), "+1555") == []
    convex.query.assert_not_called()


# ---- process_one threads history into the heavy (Hermes) lane ----------------

def test_process_one_passes_history_to_hermes():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]  # claimNext, complete
    convex.query.return_value = [{"text": "как дела?", "reply": "норм"}]
    run_fn = MagicMock(return_value="ответ")
    process_one(convex, MagicMock(), _cfg(), run_fn=run_fn)
    hist = run_fn.call_args.kwargs["history"]
    assert hist == [
        {"role": "user", "content": "как дела?"},
        {"role": "assistant", "content": "норм"},
    ]


# ---- _run_fast_lane forwards history to fast_reply ---------------------------

def test_run_fast_lane_forwards_history(monkeypatch):
    captured = {}
    monkeypatch.setattr(worker, "fast_reply", lambda text, **kw: captured.update(kw) or "ok")
    hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    out = worker._run_fast_lane("follow up", _cfg(minimax_api_key="mk"), history=hist)
    assert out == "ok"
    assert captured["history"] == hist


# ---- observability: per-message lane + latency log --------------------------

def test_process_one_logs_lane_and_latency_fast(caplog):
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    convex.query.return_value = []
    with caplog.at_level(logging.INFO, logger="worker"):
        process_one(convex, MagicMock(), _cfg(minimax_api_key="mk"),
                    run_fn=MagicMock(return_value="x"), fast_fn=lambda t: "fast answer")
    rec = " ".join(r.getMessage() for r in caplog.records)
    assert "lane=" in rec and "fast" in rec


def test_process_one_logs_lane_hermes_on_defer(caplog):
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    convex.query.return_value = []
    with caplog.at_level(logging.INFO, logger="worker"):
        process_one(convex, MagicMock(), _cfg(minimax_api_key="mk"),
                    run_fn=MagicMock(return_value="heavy"), fast_fn=lambda t: None)
    rec = " ".join(r.getMessage() for r in caplog.records)
    assert "lane=hermes" in rec
