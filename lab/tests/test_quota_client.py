"""Unit tests for the thin quota-gate client (M5, design §6).

Network-free: a MagicMock stands in for the Convex client. Proves the two failure
philosophies — FAIL OPEN on a transport error, pass through a clean verdict — plus
the synthetic-skip helper and the lowercase upsell copy.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import quota_client  # noqa: E402


def test_check_and_reserve_returns_verdict_on_success():
    convex = MagicMock()
    convex.mutation.return_value = {
        "allowed": True, "tier": "free", "remaining": 99, "msgQuota": 100, "periodEnd": 123,
    }
    out = quota_client.check_and_reserve(convex, "ws", "u1")
    assert out["allowed"] is True
    assert out["remaining"] == 99
    path, args = convex.mutation.call_args.args
    assert path == "quota:checkAndReserve"
    assert args == {"workerSecret": "ws", "userId": "u1"}


def test_check_and_reserve_passes_through_clean_deny():
    convex = MagicMock()
    convex.mutation.return_value = {
        "allowed": False, "tier": "free", "remaining": 0, "msgQuota": 100,
        "periodEnd": 1, "reason": "over_quota",
    }
    out = quota_client.check_and_reserve(convex, "ws", "u1")
    assert out["allowed"] is False
    assert out["reason"] == "over_quota"
    assert out.get("fail_open") is not True


def test_check_and_reserve_fails_open_on_exception():
    convex = MagicMock()
    convex.mutation.side_effect = RuntimeError("convex down")
    out = quota_client.check_and_reserve(convex, "ws", "u1")
    assert out["allowed"] is True
    assert out["fail_open"] is True


def test_check_and_reserve_fails_open_on_malformed_response():
    convex = MagicMock()
    convex.mutation.return_value = "not a dict"
    out = quota_client.check_and_reserve(convex, "ws", "u1")
    assert out["allowed"] is True
    assert out["fail_open"] is True


def test_is_synthetic():
    assert quota_client.is_synthetic("resume:abc") is True
    assert quota_client.is_synthetic("e2e-123") is True
    assert quota_client.is_synthetic("tg:99") is False
    assert quota_client.is_synthetic("h1") is False
    assert quota_client.is_synthetic("") is False


def test_record_usage_calls_convex_with_args():
    convex = MagicMock()
    quota_client.record_usage(
        convex, "ws", "u1", message_id="m1", lane="hermes", channel="imessage", units=1,
    )
    path, args = convex.mutation.call_args.args
    assert path == "quota:recordUsage"
    assert args["userId"] == "u1"
    assert args["messageId"] == "m1"
    assert args["lane"] == "hermes"
    assert args["channel"] == "imessage"
    assert args["units"] == 1


def test_record_usage_swallows_errors():
    convex = MagicMock()
    convex.mutation.side_effect = RuntimeError("boom")
    # Must not raise — a missing audit row can't fail a delivered turn.
    quota_client.record_usage(convex, "ws", "u1")


def test_release_reserve_calls_convex_and_swallows_errors():
    convex = MagicMock()
    quota_client.release_reserve(convex, "ws", "u1")
    path, args = convex.mutation.call_args.args
    assert path == "quota:releaseReserve"
    assert args == {"workerSecret": "ws", "userId": "u1"}
    convex.mutation.side_effect = RuntimeError("boom")
    quota_client.release_reserve(convex, "ws", "u1")  # no raise


def test_upsell_text_lowercase_with_and_without_url():
    with_url = quota_client.upsell_text("free", "https://x.test/upgrade")
    assert "https://x.test/upgrade" in with_url
    assert with_url == with_url.lower()
    no_url = quota_client.upsell_text("free", "")
    assert "https://" not in no_url
    assert "limit" in no_url
    assert no_url == no_url.lower()
