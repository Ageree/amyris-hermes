# lab/tests/test_connect.py
import json, sys, subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

SCR = Path(__file__).parent.parent / "skills" / "connections" / "scripts"
sys.path.insert(0, str(SCR))
import connect  # noqa: E402


def test_main_prints_redirect_url(capsys):
    fake = MagicMock()
    fake.create_link.return_value = {"redirect_url": "https://connect.composio.dev/link/lk_9",
                                     "connected_account_id": "ca_9", "expires_at": "2026"}
    with patch.object(connect, "ComposioClient", return_value=fake):
        connect.main(["gmail", "--user-id", "+111"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["toolkit"] == "gmail"
    assert out["redirect_url"].startswith("https://connect.composio.dev/link/")
    fake.create_link.assert_called_once_with("gmail", user_id="+111")


def test_main_reports_error_as_json(capsys):
    fake = MagicMock()
    fake.create_link.side_effect = RuntimeError("boom")
    with patch.object(connect, "ComposioClient", return_value=fake):
        rc = connect.main(["gmail"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "boom" in out["error"]
    assert rc == 1
