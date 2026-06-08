"""Tests for the thin Convex HTTP API client (P1C worker side).

The control plane (durable queue) is plain Convex public functions gated by a
WORKER_SECRET argument — so the brain talks to it over Convex's stable HTTP API
(`POST /api/query|/api/mutation`) with no Convex auth token, no Node client.

API shape verified live against dev:zany-tapir-501 (2026-06-08):
  request  body: {"path": "messages:claimNext", "args": {...}, "format": "json"}
  success resp : {"status": "success", "value": <result>}
  error   resp : {"status": "error", "errorMessage": "..."}

Import convention matches the other lab tests: sys.path-insert the skeleton dir
and import the bare module name; requests is mocked (no network).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from convex_client import ConvexClient  # noqa: E402


def test_mutation_posts_path_args_format_and_returns_value():
    client = ConvexClient("https://dep.convex.cloud")
    with patch("convex_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "success", "value": {"id": "abc"}},
        )
        out = client.mutation("messages:claimNext", {"workerSecret": "s"})
    assert out == {"id": "abc"}
    args, kwargs = mock_post.call_args
    assert args[0] == "https://dep.convex.cloud/api/mutation"
    assert kwargs["json"] == {
        "path": "messages:claimNext",
        "args": {"workerSecret": "s"},
        "format": "json",
    }


def test_query_uses_query_endpoint_and_returns_value():
    client = ConvexClient("https://dep.convex.cloud")
    with patch("convex_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "success", "value": {"total": 0.0}},
        )
        out = client.query("messages:stats", {})
    assert out == {"total": 0.0}
    assert mock_post.call_args.args[0] == "https://dep.convex.cloud/api/query"


def test_raises_runtimeerror_on_convex_error_status():
    client = ConvexClient("https://dep.convex.cloud")
    with patch("convex_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": "error", "errorMessage": "unauthorized worker"},
        )
        try:
            client.mutation("messages:claimNext", {"workerSecret": "WRONG"})
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "unauthorized worker" in str(e)


def test_raises_runtimeerror_on_http_non_2xx():
    client = ConvexClient("https://dep.convex.cloud")
    with patch("convex_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=500, text="boom")
        try:
            client.query("messages:stats", {})
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "500" in str(e)


def test_strips_trailing_slash_from_base_url():
    client = ConvexClient("https://dep.convex.cloud/")
    with patch("convex_client.requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200, json=lambda: {"status": "success", "value": None}
        )
        client.query("messages:stats", {})
    assert mock_post.call_args.args[0] == "https://dep.convex.cloud/api/query"


def test_requires_base_url():
    try:
        ConvexClient("")
        assert False, "expected ValueError"
    except ValueError:
        pass
