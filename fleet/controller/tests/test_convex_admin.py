"""Tests for convex_admin.py — HTTP client for Convex fleet admin API."""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from convex_admin import ConvexAdminClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class MockHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for simulating Convex API responses."""

    response_body = None  # Set by tests
    response_status = 200

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        # Store the request for assertions
        self.server.last_request = json.loads(body) if body else None
        self.server.last_path = self.path

        self.send_response(self.server.response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.server.response_body).encode())

    def log_message(self, format, *args):
        pass  # Suppress request logs


@pytest.fixture()
def mock_server():
    server = HTTPServer(("127.0.0.1", 0), MockHandler)
    server.response_body = {"status": "success", "value": []}
    server.response_status = 200
    server.last_request = None
    server.last_path = None
    thread = Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield server
    server.shutdown()


@pytest.fixture()
def client(mock_server, monkeypatch):
    monkeypatch.setenv("WORKER_SECRET", "test-secret")
    port = mock_server.server_address[1]
    return ConvexAdminClient(f"http://127.0.0.1:{port}", timeout=5.0)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_raises_on_empty_url(self):
        with pytest.raises(ValueError, match="base_url"):
            ConvexAdminClient("")

    def test_accepts_valid_url(self, monkeypatch):
        monkeypatch.setenv("WORKER_SECRET", "x")
        client = ConvexAdminClient("https://example.convex.cloud")
        assert client._base == "https://example.convex.cloud"

    def test_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("WORKER_SECRET", "x")
        client = ConvexAdminClient("https://example.convex.cloud/")
        assert client._base == "https://example.convex.cloud"


# ---------------------------------------------------------------------------
# list_reconcile (FAIL-SOFT)
# ---------------------------------------------------------------------------

class TestListReconcile:
    def test_returns_list_on_success(self, mock_server, client):
        instances = [{"userId": "u1", "desired": "running", "status": "stopped"}]
        mock_server.response_body = {"status": "success", "value": instances}
        result = client.list_reconcile()
        assert result == instances

    def test_returns_empty_on_non_list_response(self, mock_server, client):
        mock_server.response_body = {"status": "success", "value": "not a list"}
        result = client.list_reconcile()
        assert result == []

    def test_returns_empty_on_http_error(self, mock_server, client):
        mock_server.response_status = 500
        mock_server.response_body = {"error": "internal"}
        result = client.list_reconcile()
        assert result == []

    def test_sends_worker_secret_in_args(self, mock_server, client):
        mock_server.response_body = {"status": "success", "value": []}
        client.list_reconcile()
        assert mock_server.last_request["args"]["workerSecret"] == "test-secret"


# ---------------------------------------------------------------------------
# claim_for_launch
# ---------------------------------------------------------------------------

class TestClaimForLaunch:
    def test_sends_correct_args(self, mock_server, client):
        mock_server.response_body = {"status": "success", "value": {"claimed": True}}
        result = client.claim_for_launch("u1", "host-a", "cid123")
        assert result == {"claimed": True}
        req = mock_server.last_request
        assert req["args"]["userId"] == "u1"
        assert req["args"]["hostVm"] == "host-a"
        assert req["args"]["containerId"] == "cid123"

    def test_includes_worker_secret_ref_when_provided(self, mock_server, client):
        mock_server.response_body = {"status": "success", "value": {"claimed": True}}
        client.claim_for_launch("u1", "host-a", "cid", worker_secret_ref="ref-1")
        req = mock_server.last_request
        assert req["args"]["workerSecretRef"] == "ref-1"


# ---------------------------------------------------------------------------
# mark_stopped
# ---------------------------------------------------------------------------

class TestMarkStopped:
    def test_sends_correct_mutation(self, mock_server, client):
        mock_server.response_body = {"status": "success", "value": None}
        client.mark_stopped("u1")
        req = mock_server.last_request
        assert req["path"] == "fleet:markStopped"
        assert req["args"]["userId"] == "u1"


# ---------------------------------------------------------------------------
# mark_error
# ---------------------------------------------------------------------------

class TestMarkError:
    def test_sends_error_string(self, mock_server, client):
        mock_server.response_body = {"status": "success", "value": {"errorCount": 3}}
        result = client.mark_error("u1", "crash happened")
        assert result == {"errorCount": 3}
        req = mock_server.last_request
        assert req["args"]["error"] == "crash happened"


# ---------------------------------------------------------------------------
# set_desired
# ---------------------------------------------------------------------------

class TestSetDesired:
    def test_valid_desired_running(self, mock_server, client):
        mock_server.response_body = {"status": "success", "value": None}
        client.set_desired("u1", "running")
        req = mock_server.last_request
        assert req["args"]["desired"] == "running"

    def test_valid_desired_stopped(self, mock_server, client):
        mock_server.response_body = {"status": "success", "value": None}
        client.set_desired("u1", "stopped")
        req = mock_server.last_request
        assert req["args"]["desired"] == "stopped"

    def test_invalid_desired_raises(self, client):
        with pytest.raises(ValueError, match="running.*stopped"):
            client.set_desired("u1", "invalid")


# ---------------------------------------------------------------------------
# _auth_args
# ---------------------------------------------------------------------------

class TestAuthArgs:
    def test_raises_when_worker_secret_missing(self, monkeypatch):
        monkeypatch.delenv("WORKER_SECRET", raising=False)
        client = ConvexAdminClient("http://localhost:1234")
        with pytest.raises(RuntimeError, match="WORKER_SECRET"):
            client._auth_args()
