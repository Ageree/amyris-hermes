"""Tests for the brain-side worker poller (P1C).

The worker replaces the throwaway FastAPI app.py: instead of being publicly
reachable, the brain POLLS the always-on Convex durable queue. One iteration:

    claimNext(workerSecret) -> {id, handle, userNumber, text, mediaUrl} | None
      -> run_hermes(text) -> reply        (or a friendly error on failure)
      -> sendblue.send_message(reply_target, reply)
      -> complete(id, reply)              (or fail(id, error))

Security model carried over from app.py: the reply target is ALWAYS the
config-derived operator number, never the inbound payload.

All collaborators (Convex, Sendblue, Hermes) are injected and mocked — no
network, no subprocess.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import WorkerConfig, process_one, run_loop  # noqa: E402


def _cfg(**over):
    base = dict(
        convex_url="https://dep.convex.cloud",
        worker_secret="wsecret",
        sendblue_key_id="k",
        sendblue_secret="s",
        sendblue_from="+1999",
        reply_target="+1555",
        hermes_home="/h",
        hermes_dir="/d",
        python_bin="/p",
        poll_interval=0.01,
        hermes_timeout=60.0,
    )
    base.update(over)
    return WorkerConfig(**base)


def _claim(**over):
    base = {"id": "msg1", "handle": "h1", "userNumber": "+1555",
            "text": "Open example.com and give its H1", "mediaUrl": None}
    base.update(over)
    return base


# ---- process_one ---------------------------------------------------------

def test_process_one_returns_false_and_does_nothing_when_queue_empty():
    convex = MagicMock()
    convex.mutation.return_value = None  # claimNext -> None
    sendblue = MagicMock()
    run_fn = MagicMock()
    did = process_one(convex, sendblue, _cfg(), run_fn=run_fn)
    assert did is False
    run_fn.assert_not_called()
    sendblue.send_message.assert_not_called()
    # only claimNext was attempted, no complete/fail
    assert convex.mutation.call_count == 1


def test_process_one_runs_hermes_completes_and_replies():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]  # claimNext, then complete
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="The H1 is Example Domain")
    did = process_one(convex, sendblue, _cfg(), run_fn=run_fn)
    assert did is True
    run_fn.assert_called_once()
    # reply sent to the config target with the hermes answer
    sendblue.send_message.assert_called_once()
    kw = sendblue.send_message.call_args.kwargs
    assert kw["to_number"] == "+1555"
    assert kw["content"] == "The H1 is Example Domain"
    # second mutation call was complete with id + reply
    complete_call = convex.mutation.call_args_list[1]
    assert complete_call.args[0] == "messages:complete"
    assert complete_call.args[1]["id"] == "msg1"
    assert complete_call.args[1]["reply"] == "The H1 is Example Domain"
    assert complete_call.args[1]["workerSecret"] == "wsecret"


def test_process_one_marks_fail_and_sends_friendly_error_on_hermes_exception():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]  # claimNext, then fail
    sendblue = MagicMock()
    run_fn = MagicMock(side_effect=RuntimeError("hermes exited 1: boom"))
    did = process_one(convex, sendblue, _cfg(), run_fn=run_fn)
    assert did is True
    fail_call = convex.mutation.call_args_list[1]
    assert fail_call.args[0] == "messages:fail"
    assert fail_call.args[1]["id"] == "msg1"
    assert "boom" in fail_call.args[1]["error"]
    # user still gets a (friendly, non-leaking) reply
    sendblue.send_message.assert_called_once()
    sent = sendblue.send_message.call_args.kwargs["content"]
    assert "boom" not in sent  # don't leak internals to the user


def test_process_one_replies_to_config_target_not_payload_number():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(userNumber="+1ATTACKER"), None]
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="ok")
    process_one(convex, sendblue, _cfg(reply_target="+1OWNER"), run_fn=run_fn)
    assert sendblue.send_message.call_args.kwargs["to_number"] == "+1OWNER"


def test_process_one_truncates_long_reply():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="x" * 5000)
    process_one(convex, sendblue, _cfg(), run_fn=run_fn)
    assert len(sendblue.send_message.call_args.kwargs["content"]) <= 1800


def test_process_one_still_completes_when_sendblue_send_fails():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    sendblue = MagicMock()
    sendblue.send_message.side_effect = RuntimeError("sendblue 500")
    run_fn = MagicMock(return_value="ok")
    # must not raise; must still have marked complete
    did = process_one(convex, sendblue, _cfg(), run_fn=run_fn)
    assert did is True
    assert convex.mutation.call_args_list[1].args[0] == "messages:complete"


def test_process_one_passes_hermes_paths_and_timeout():
    convex = MagicMock()
    convex.mutation.side_effect = [_claim(), None]
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="ok")
    process_one(convex, sendblue, _cfg(), run_fn=run_fn)
    kw = run_fn.call_args.kwargs
    assert kw["hermes_home"] == "/h"
    assert kw["hermes_dir"] == "/d"
    assert kw["python_bin"] == "/p"
    assert kw["timeout"] == 60.0


# ---- run_loop ------------------------------------------------------------

def test_run_loop_polls_then_sleeps_only_when_empty():
    process_fn = MagicMock(side_effect=[True, False])  # work, then empty
    sleep_fn = MagicMock()
    run_loop(_cfg(), convex=MagicMock(), sendblue=MagicMock(),
             process_fn=process_fn, sleep_fn=sleep_fn, max_iterations=2)
    assert process_fn.call_count == 2
    sleep_fn.assert_called_once_with(0.01)  # slept once, only after the empty poll


def test_run_loop_survives_a_process_exception():
    process_fn = MagicMock(side_effect=[RuntimeError("transient"), False])
    sleep_fn = MagicMock()
    # must not propagate the exception
    run_loop(_cfg(), convex=MagicMock(), sendblue=MagicMock(),
             process_fn=process_fn, sleep_fn=sleep_fn, max_iterations=2)
    assert process_fn.call_count == 2
    assert sleep_fn.call_count == 2  # both a crash and an empty poll back off


# ---- WorkerConfig.from_env ----------------------------------------------

def test_from_env_reads_required_vars(monkeypatch):
    env = {
        "CONVEX_URL": "https://dep.convex.cloud",
        "WORKER_SECRET": "ws",
        "SENDBLUE_API_KEY_ID": "kid",
        "SENDBLUE_API_SECRET_KEY": "sec",
        "SENDBLUE_FROM_NUMBER": "+1999",
        "ALLOWED_USER_NUMBER": "+1555",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cfg = WorkerConfig.from_env()
    assert cfg.convex_url == "https://dep.convex.cloud"
    assert cfg.worker_secret == "ws"
    assert cfg.reply_target == "+1555"
    assert cfg.sendblue_from == "+1999"


def test_from_env_raises_when_required_var_missing(monkeypatch):
    for k in ("CONVEX_URL", "WORKER_SECRET", "SENDBLUE_API_KEY_ID",
              "SENDBLUE_API_SECRET_KEY", "SENDBLUE_FROM_NUMBER", "ALLOWED_USER_NUMBER"):
        monkeypatch.delenv(k, raising=False)
    try:
        WorkerConfig.from_env()
        assert False, "expected KeyError"
    except KeyError:
        pass


# ---- process_intents -----------------------------------------------------

def test_process_intents_resolves_when_all_active():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "connections" / "scripts"))
    import worker as w
    cfg = _cfg()  # existing helper building a WorkerConfig; if absent, build inline
    convex = MagicMock()
    convex.query.return_value = [
        {"id": "i1", "userNumber": "+111", "taskText": "t",
         "requiredToolkits": ["gmail", "googlecalendar"], "connectedToolkits": [], "createdAt": 1.0},
    ]
    composio = MagicMock()
    composio.connection_status.side_effect = lambda tk, user_id=None: "ACTIVE"
    w.process_intents(convex, cfg, composio=composio, now=1000.0)
    # reports both ACTIVE to resolveIntent
    call = next(c for c in convex.mutation.call_args_list if c.args[0] == "intents:resolveIntent")
    assert sorted(call.args[1]["connectedToolkits"]) == ["gmail", "googlecalendar"]


def test_process_intents_expires_stale():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "connections" / "scripts"))
    import worker as w
    cfg = _cfg()
    convex = MagicMock()
    convex.query.return_value = [
        {"id": "old", "userNumber": "+1", "taskText": "t", "requiredToolkits": ["gmail"],
         "connectedToolkits": [], "createdAt": 0.0},
    ]
    composio = MagicMock(); composio.connection_status.return_value = "INITIATED"
    w.process_intents(convex, cfg, composio=composio, now=10_000.0)  # > TTL
    assert any(c.args[0] == "intents:expireIntent" for c in convex.mutation.call_args_list)
