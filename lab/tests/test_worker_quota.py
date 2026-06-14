"""Worker quota integration (M5, design §6). Network-free.

Proves process_one's quota behaviour: a clean over-quota verdict short-circuits to
a friendly upsell + complete with NO lane (zero model spend); an allowed turn
reserves then runs the lane then records usage; a hard failure refunds the reserve;
synthetic / legacy-userless turns are unmetered; a Convex error fails OPEN.

A name-dispatching FakeConvex is used (instead of side_effect ordering) because the
quota gate adds calls — dispatch-by-name keeps the tests robust to call order.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import WorkerConfig, process_one  # noqa: E402


def _cfg(**over):
    base = dict(
        convex_url="https://dep.convex.cloud", worker_secret="ws",
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target="+1555", hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0,
        history_enabled=False,  # isolate the quota path from the history fetch
    )
    base.update(over)
    return WorkerConfig(**base)


def _claim(**over):
    base = {"id": "m1", "handle": "h1", "userNumber": "+1U", "userId": "u1",
            "channel": "imessage", "replyTarget": "+1U", "text": "hello", "mediaUrl": None}
    base.update(over)
    return base


class FakeConvex:
    """Routes mutation/query by function name. `reserve` is the checkAndReserve
    verdict dict, or an Exception to raise (to exercise fail-open)."""

    def __init__(self, claim, reserve=None):
        self.calls = []
        self._claim = claim
        self._reserve = reserve

    def mutation(self, path, args):
        self.calls.append((path, args))
        if path in ("messages:claimNext", "messages:claimNextForUser"):
            return self._claim
        if path == "quota:checkAndReserve":
            if isinstance(self._reserve, BaseException):
                raise self._reserve
            return self._reserve
        return None

    def query(self, path, args):
        self.calls.append((path, args))
        return []

    def names(self):
        return [p for p, _ in self.calls]

    def arg(self, path):
        return next(a for p, a in self.calls if p == path)


_ALLOW = {"allowed": True, "tier": "free", "remaining": 99, "msgQuota": 100, "periodEnd": 1}
_DENY = {"allowed": False, "tier": "free", "remaining": 0, "msgQuota": 100,
         "periodEnd": 1, "reason": "over_quota"}


def test_over_quota_sends_upsell_completes_and_runs_no_lane():
    convex = FakeConvex(_claim(), reserve=_DENY)
    client = MagicMock()
    run_fn = MagicMock()
    did = process_one(convex, client, _cfg(upsell_url="https://x.test/up"), run_fn=run_fn)
    assert did is True
    run_fn.assert_not_called()  # zero model spend
    names = convex.names()
    assert "quota:checkAndReserve" in names
    assert "messages:complete" in names
    assert "messages:fail" not in names
    assert "quota:recordUsage" not in names
    client.send_message.assert_called()  # upsell delivered to the claimed address
    assert "https://x.test/up" in convex.arg("messages:complete")["reply"]


def test_allowed_reserves_runs_lane_and_records_usage():
    convex = FakeConvex(_claim(), reserve=_ALLOW)
    client = MagicMock()
    run_fn = MagicMock(return_value="the answer")
    did = process_one(convex, client, _cfg(), run_fn=run_fn)
    assert did is True
    run_fn.assert_called_once()
    names = convex.names()
    assert "quota:checkAndReserve" in names
    assert "messages:complete" in names
    assert "quota:recordUsage" in names
    assert "quota:releaseReserve" not in names
    rec = convex.arg("quota:recordUsage")
    assert rec["userId"] == "u1"
    assert rec["channel"] == "imessage"


def test_hard_failure_releases_reserve_and_records_no_usage():
    convex = FakeConvex(_claim(), reserve=_ALLOW)
    client = MagicMock()

    def boom(*a, **k):
        raise RuntimeError("hermes died")

    did = process_one(convex, client, _cfg(), run_fn=boom)
    assert did is True
    names = convex.names()
    assert "messages:fail" in names
    assert "quota:releaseReserve" in names
    assert "quota:recordUsage" not in names


def test_synthetic_resume_is_unmetered():
    convex = FakeConvex(_claim(handle="resume:abc"), reserve=_DENY)
    client = MagicMock()
    run_fn = MagicMock(return_value="resumed")
    process_one(convex, client, _cfg(), run_fn=run_fn)
    assert "quota:checkAndReserve" not in convex.names()  # never metered
    run_fn.assert_called_once()  # runs despite the would-be deny


def test_legacy_userless_row_is_unmetered():
    convex = FakeConvex(_claim(userId=None), reserve=_DENY)
    client = MagicMock()
    run_fn = MagicMock(return_value="ok")
    process_one(convex, client, _cfg(), run_fn=run_fn)
    assert "quota:checkAndReserve" not in convex.names()
    run_fn.assert_called_once()


def test_convex_error_fails_open_without_metering():
    convex = FakeConvex(_claim(), reserve=RuntimeError("convex down"))
    client = MagicMock()
    run_fn = MagicMock(return_value="ok")
    process_one(convex, client, _cfg(), run_fn=run_fn)
    names = convex.names()
    assert "quota:checkAndReserve" in names  # attempted
    run_fn.assert_called_once()              # proceeded (fail open)
    assert "quota:recordUsage" not in names  # reserved nothing -> nothing to record
    assert "quota:releaseReserve" not in names


def test_quota_disabled_bypasses_the_gate():
    convex = FakeConvex(_claim(), reserve=_DENY)
    client = MagicMock()
    run_fn = MagicMock(return_value="ok")
    process_one(convex, client, _cfg(quota_enabled=False), run_fn=run_fn)
    assert "quota:checkAndReserve" not in convex.names()
    run_fn.assert_called_once()
