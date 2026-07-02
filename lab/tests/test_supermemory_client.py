from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from supermemory_client import SupermemoryClient, tenant_tag


class _Resp:
    def __init__(self, data: object) -> None:
        self._data = json.dumps(data).encode()

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


def test_tenant_tag_is_stable_and_scoped() -> None:
    assert tenant_tag("user/../x y") == "hermes:user:user-..-x-y"


def test_recall_parses_common_supermemory_result_shapes() -> None:
    seen = {}

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode())
        return _Resp(
            {"results": [{"memory": "любит суши"}, {"document": {"content": "Москва"}}]}
        )

    with patch("supermemory_client.urllib.request.urlopen", fake_urlopen):
        out = SupermemoryClient("k").recall("u1", "еда", limit=2)

    assert out == ["любит суши", "Москва"]
    assert seen["url"].endswith("/v4/search")
    assert seen["body"]["containerTag"] == "hermes:user:u1"
    assert seen["body"]["searchMode"] == "hybrid"


def test_remember_text_uses_tenant_container_tag() -> None:
    bodies = []

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        bodies.append(json.loads(req.data.decode()))
        return _Resp({"ok": True})

    with patch("supermemory_client.urllib.request.urlopen", fake_urlopen):
        ok = SupermemoryClient("k").remember_text("u1", "любит пиццу", kind="fact")

    assert ok is True
    assert bodies[0]["containerTag"] == "hermes:user:u1"
    assert bodies[0]["memories"][0]["metadata"]["kind"] == "fact"


@pytest.mark.live_channel
def test_supermemory_live_roundtrip() -> None:
    key = os.environ.get("SUPERMEMORY_API_KEY")
    if not key:
        pytest.skip("SUPERMEMORY_API_KEY not set")
    # Short marker — v4/search returns truncated snippets, not full content.
    marker = uuid.uuid4().hex[:12]
    user_key = f"live-{uuid.uuid4()}"
    client = SupermemoryClient(key, timeout=20.0)
    assert client.remember_text(user_key, f"fact marker {marker}", kind="live_e2e")
    deadline = time.time() + 90
    while time.time() < deadline:
        facts = client.recall(user_key, marker, limit=5)
        if any(marker in fact for fact in facts):
            return
        time.sleep(3)
    raise AssertionError("Supermemory live roundtrip did not return the written fact")
