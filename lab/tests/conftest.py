"""Shared fixtures + tiered-test gating for the lab suite.

Introduced in M0 of the multi-tenancy build. Three test tiers:
  - (default/unit): network-free, mocked collaborators. Always run.
  - convex_e2e: hits a REAL dev Convex deployment. Skipped unless RUN_CONVEX_E2E=1.
  - live_channel: sends over a REAL channel (Sendblue/Telegram). Skipped unless
    RUN_LIVE_CHANNEL=1.

This keeps `pytest`/CI fast and side-effect-free while letting the operator opt
into the live tiers explicitly. Skipping is automatic via the markers below — a
test just decorates with @pytest.mark.convex_e2e / @pytest.mark.live_channel.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make the worker/skeleton modules importable from any test without per-file
# sys.path hacks (existing tests still do their own insert — harmless).
_SKELETON = Path(__file__).parent.parent / "skeleton"
if str(_SKELETON) not in sys.path:
    sys.path.insert(0, str(_SKELETON))


def pytest_collection_modifyitems(config, items):
    """Auto-skip the live tiers unless their opt-in env var is set."""
    run_convex = os.environ.get("RUN_CONVEX_E2E") == "1"
    run_live = os.environ.get("RUN_LIVE_CHANNEL") == "1"
    skip_convex = pytest.mark.skip(reason="needs RUN_CONVEX_E2E=1 (real dev Convex)")
    skip_live = pytest.mark.skip(reason="needs RUN_LIVE_CHANNEL=1 (real channel send)")
    for item in items:
        if "convex_e2e" in item.keywords and not run_convex:
            item.add_marker(skip_convex)
        if "live_channel" in item.keywords and not run_live:
            item.add_marker(skip_live)


class RecordingChannel:
    """A fake Channel that records sends instead of hitting a provider.

    Duck-types BOTH the new worker Channel surface (send_message(address, text),
    send_typing(address, state=...)) AND the legacy SendblueClient surface
    (send_message(to_number=, content=)), so it can stand in for either across
    the M2 transition. Inspect `.sends` (list of (address, text)) to assert what
    the worker delivered and WHERE.
    """

    def __init__(self, kind: str = "imessage"):
        self.kind = kind
        self.sends: list = []     # (address, text) tuples
        self.typings: list = []   # (address, state) tuples

    def send_message(self, address=None, text=None, *, to_number=None, content=None):
        addr = address if address is not None else to_number
        body = text if text is not None else content
        self.sends.append((addr, body))
        return {"ok": True, "provider_id": f"rec-{len(self.sends)}"}

    def send_typing(self, address=None, *, state="start", to_number=None, max_duration_ms=None):
        addr = address if address is not None else to_number
        self.typings.append((addr, state))
        return {"ok": True}

    def split(self, text):
        t = (text or "").strip()
        return [t] if t else []

    def render(self, text):
        return text


@pytest.fixture
def fake_channel():
    """A single recording channel (default kind=imessage)."""
    return RecordingChannel()


@pytest.fixture
def make_fake_channel():
    """Factory for recording channels of a given kind (for multi-channel tests)."""
    return lambda kind="imessage": RecordingChannel(kind)
