# lab/tests/test_conn_status.py
import json, sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCR = Path(__file__).parent.parent / "skills" / "connections" / "scripts"
sys.path.insert(0, str(SCR))
import conn_status  # noqa: E402


def test_prints_status(capsys):
    fake = MagicMock(); fake.connection_status.return_value = "ACTIVE"
    with patch.object(conn_status, "ComposioClient", return_value=fake):
        conn_status.main(["gmail", "--user-id", "+111"])
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": True, "toolkit": "gmail", "status": "ACTIVE"}
    fake.connection_status.assert_called_once_with("gmail", user_id="+111")


def test_error_json(capsys):
    fake = MagicMock(); fake.connection_status.side_effect = RuntimeError("nope")
    with patch.object(conn_status, "ComposioClient", return_value=fake):
        rc = conn_status.main(["gmail"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and rc == 1
