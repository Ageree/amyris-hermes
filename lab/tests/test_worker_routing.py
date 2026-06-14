"""M2 keystone: the worker routes each reply to the CLAIMED message's own channel
+ address, NOT a single hardcoded config target.

Before M2 every reply was pinned to cfg.reply_target (= the operator number). These
tests prove the de-hardcode: a ChannelRegistry is selected by the claimed row's
`channel`, and the reply is delivered to the claimed row's `replyTarget`. Uses the
conftest RecordingChannel fakes (no network).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import WorkerConfig, process_one  # noqa: E402
from channels import ChannelRegistry  # noqa: E402

from conftest import RecordingChannel  # noqa: E402


def _cfg(**over):
    base = dict(
        convex_url="https://dep.convex.cloud", worker_secret="wsecret",
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target="+1OPERATOR", hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0,
        typing_enabled=False,  # routing tests don't care about the typing thread
    )
    base.update(over)
    return WorkerConfig(**base)


def _claim(**over):
    base = {"id": "m1", "handle": "h1", "userNumber": "+1USER", "text": "привет",
            "mediaUrl": None, "channel": "imessage", "replyTarget": "+1USER", "userId": "u1"}
    base.update(over)
    return base


def _convex_for(claim):
    convex = MagicMock()
    convex.mutation.side_effect = [claim, None]  # claimNext, complete
    convex.query.return_value = []               # no history
    return convex


# ---- the keystone: reply goes to the claimed address, not the config target ----

def test_replies_to_claimed_channel_not_config_target():
    convex = _convex_for(_claim(replyTarget="+1NEWUSER", userNumber="+1NEWUSER"))
    rec = RecordingChannel("imessage")
    registry = ChannelRegistry({"imessage": rec})
    run_fn = MagicMock(return_value="ответ")
    process_one(convex, registry, _cfg(reply_target="+1OPERATOR"), run_fn=run_fn)
    assert rec.sends, "a reply should have been sent"
    addr, body = rec.sends[0]
    assert addr == "+1NEWUSER", "must reply to the CLAIMED address, not cfg.reply_target"
    assert body == "ответ"


def test_outbound_client_selected_by_channel():
    rec_im = RecordingChannel("imessage")
    rec_tg = RecordingChannel("telegram")
    registry = ChannelRegistry({"imessage": rec_im, "telegram": rec_tg})

    # telegram row -> telegram channel only
    convex = _convex_for(_claim(channel="telegram", replyTarget="555123", userNumber="555123"))
    process_one(convex, registry, _cfg(), run_fn=MagicMock(return_value="tg ответ"))
    assert rec_tg.sends == [("555123", "tg ответ")]
    assert rec_im.sends == []

    # imessage row -> imessage channel only
    rec_im.sends.clear(); rec_tg.sends.clear()
    convex = _convex_for(_claim(channel="imessage", replyTarget="+1A", userNumber="+1A"))
    process_one(convex, registry, _cfg(), run_fn=MagicMock(return_value="im ответ"))
    assert rec_im.sends == [("+1A", "im ответ")]
    assert rec_tg.sends == []

    # null channel -> defaults to imessage (legacy rows keep working)
    rec_im.sends.clear(); rec_tg.sends.clear()
    convex = _convex_for(_claim(channel=None, replyTarget="+1B", userNumber="+1B"))
    process_one(convex, registry, _cfg(), run_fn=MagicMock(return_value="legacy ответ"))
    assert rec_im.sends == [("+1B", "legacy ответ")]
    assert rec_tg.sends == []


def test_legacy_fallback_to_config_target_when_no_address_on_claim():
    # A LEGACY row (no userId) predating replyTarget AND userNumber falls back to
    # cfg.reply_target so the operator's pre-migration rows are never dropped.
    convex = _convex_for(_claim(replyTarget=None, userNumber="", userId=None))
    rec = RecordingChannel("imessage")
    registry = ChannelRegistry({"imessage": rec})
    process_one(convex, registry, _cfg(reply_target="+1OPERATOR"), run_fn=MagicMock(return_value="ok"))
    assert rec.sends and rec.sends[0][0] == "+1OPERATOR"


def test_tenant_row_without_address_is_failed_not_leaked_to_operator():
    # A2 defense-in-depth: a TENANT row (userId set) with no replyTarget/userNumber
    # must NEVER fall back to the operator number — that would leak one tenant's
    # answer. It is marked failed and nothing is sent.
    convex = _convex_for(_claim(replyTarget=None, userNumber="", userId="u_tenant"))
    rec = RecordingChannel("imessage")
    registry = ChannelRegistry({"imessage": rec})
    run_fn = MagicMock(return_value="secret answer")
    did = process_one(convex, registry, _cfg(reply_target="+1OPERATOR"), run_fn=run_fn)
    assert did is True
    assert rec.sends == [], "must not send a tenant reply to the operator number"
    run_fn.assert_not_called()  # never even runs Hermes — bailed before processing
    calls = [c.args[0] for c in convex.mutation.call_args_list]
    assert calls == ["messages:claimNext", "messages:fail"]


def test_unconfigured_channel_kind_does_not_crash_loop():
    # A telegram row claimed on an iMessage-only worker: get() raises, but
    # process_one must NOT propagate (it returns True, having handled the message),
    # so one misrouted row can't kill the always-on loop.
    convex = _convex_for(_claim(channel="telegram", replyTarget="555", userNumber="555"))
    registry = ChannelRegistry({"imessage": RecordingChannel("imessage")})  # no telegram
    did = process_one(convex, registry, _cfg(), run_fn=MagicMock(return_value="x"))
    assert did is True  # handled (did not raise out of the loop)


def test_back_compat_single_client_is_wrapped_as_imessage():
    # A raw Sendblue-like client (legacy callers / the 200+ unit tests) is wrapped
    # as the sole imessage channel; the underlying client still sees to_number/content.
    convex = _convex_for(_claim())
    client = MagicMock()
    process_one(convex, client, _cfg(), run_fn=MagicMock(return_value="ok"))
    assert client.send_message.call_args.kwargs["to_number"] == "+1USER"
    assert client.send_message.call_args.kwargs["content"] == "ok"


def test_scoped_worker_claims_per_user():
    # When USER_ID is configured (a fleet container), the worker claims via the
    # tenant-scoped claimNextForUser, not the global claimNext.
    convex = _convex_for(_claim())
    registry = ChannelRegistry({"imessage": RecordingChannel("imessage")})
    process_one(convex, registry, _cfg(scoped_user_id="u_abc"), run_fn=MagicMock(return_value="ok"))
    first = convex.mutation.call_args_list[0]
    assert first.args[0] == "messages:claimNextForUser"
    assert first.args[1]["userId"] == "u_abc"
