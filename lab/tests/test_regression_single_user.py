"""M0 golden-path canary — locks the operator's single-user round trip.

This MUST stay green across the entire multi-tenant migration. It encodes the
one behavior the operator depends on: an inbound message from the operator is
claimed, run through the agent, the reply is delivered to the operator's OWN
number, and the turn is marked complete.

It is deliberately written to survive the M2 keystone fix: after M2 the worker
routes by the claimed row's own `replyTarget`/`channel`. Here userNumber ==
reply_target == the operator number, so "the reply went to the operator" holds
BEFORE and AFTER the de-hardcode. If this canary ever goes red, the live
single-user path is at risk — stop and investigate.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import WorkerConfig, process_one  # noqa: E402

OPERATOR = "+79217818876"


def _cfg(**over):
    base = dict(
        convex_url="https://dep.convex.cloud", worker_secret="ws",
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target=OPERATOR, hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0,
        # deterministic: no fast lane / streaming / typing / history side-effects.
        fast_lane_enabled=False, multi_bubble_enabled=False,
        typing_enabled=False, streaming_enabled=False, history_enabled=False,
    )
    base.update(over)
    return WorkerConfig(**base)


@pytest.mark.unit
def test_operator_single_user_golden_path():
    convex = MagicMock()
    convex.query.return_value = []  # no conversation history
    convex.mutation.side_effect = [
        {"id": "m1", "handle": "h1", "userNumber": OPERATOR,
         "text": "what's up", "mediaUrl": None},   # claimNext
        None,                                       # complete
    ]
    sendblue = MagicMock()
    run_fn = MagicMock(return_value="all good 👌")

    did = process_one(convex, sendblue, _cfg(), run_fn=run_fn)

    assert did is True
    run_fn.assert_called_once()
    # the reply is delivered to the OPERATOR's own number (not leaked elsewhere)
    assert sendblue.send_message.call_args.kwargs["to_number"] == OPERATOR
    assert sendblue.send_message.call_args.kwargs["content"] == "all good 👌"
    # and the turn was marked complete with that reply
    complete = convex.mutation.call_args_list[1]
    assert complete.args[0] == "messages:complete"
    assert complete.args[1]["id"] == "m1"
    assert complete.args[1]["reply"] == "all good 👌"


@pytest.mark.unit
def test_operator_hermes_failure_sends_friendly_error_not_leak():
    """A hermes failure still replies to the operator, marks fail, leaks nothing."""
    convex = MagicMock()
    convex.query.return_value = []
    convex.mutation.side_effect = [
        {"id": "m2", "handle": "h2", "userNumber": OPERATOR,
         "text": "do a thing", "mediaUrl": None},   # claimNext
        None,                                        # fail
    ]
    sendblue = MagicMock()
    run_fn = MagicMock(side_effect=RuntimeError("hermes exited 1: secret-internal"))

    did = process_one(convex, sendblue, _cfg(), run_fn=run_fn)

    assert did is True
    assert convex.mutation.call_args_list[1].args[0] == "messages:fail"
    sent = sendblue.send_message.call_args.kwargs
    assert sent["to_number"] == OPERATOR
    assert "secret-internal" not in sent["content"]  # never leak internals
