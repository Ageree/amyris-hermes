# lab/tests/test_pending.py
import json, sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCR = Path(__file__).parent.parent / "skills" / "connections" / "scripts"
sys.path.insert(0, str(SCR))
import pending  # noqa: E402


def test_add_calls_addintent(capsys, monkeypatch):
    monkeypatch.setenv("CONVEX_URL", "https://dep.convex.cloud")
    monkeypatch.setenv("WORKER_SECRET", "ws")
    fake = MagicMock(); fake.mutation.return_value = "intent_1"
    with patch.object(pending, "ConvexClient", return_value=fake):
        pending.main(["add", "--task", "разбери почту", "--toolkits", "gmail,googlecalendar", "--user-id", "+111"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    fake.mutation.assert_called_once_with("intents:addIntent", {
        "workerSecret": "ws", "userNumber": "+111", "taskText": "разбери почту",
        "requiredToolkits": ["gmail", "googlecalendar"],
    })


def test_missing_env_errors(capsys, monkeypatch):
    monkeypatch.delenv("CONVEX_URL", raising=False)
    rc = pending.main(["add", "--task", "x", "--toolkits", "gmail", "--user-id", "+1"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and rc == 1
