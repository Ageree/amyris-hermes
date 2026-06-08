# lab/tests/test_exec_tool.py
import json, sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCR = Path(__file__).parent.parent / "skills" / "connections" / "scripts"
sys.path.insert(0, str(SCR))
import exec_tool  # noqa: E402
import composio_api as ca  # noqa: E402


def test_list_mode(capsys):
    fake = MagicMock(); fake.list_tools.return_value = ["GMAIL_FETCH_EMAILS"]
    with patch.object(exec_tool, "ComposioClient", return_value=fake):
        exec_tool.main(["--list", "gmail"])
    out = json.loads(capsys.readouterr().out)
    assert out == {"ok": True, "toolkit": "gmail", "tools": ["GMAIL_FETCH_EMAILS"]}


def test_execute_passes_parsed_args(capsys):
    fake = MagicMock(); fake.execute.return_value = {"data": {"x": 1}}
    with patch.object(exec_tool, "ComposioClient", return_value=fake):
        exec_tool.main(["GMAIL_FETCH_EMAILS", '{"max_results": 2}', "--user-id", "+111"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["result"] == {"data": {"x": 1}}
    fake.execute.assert_called_once_with("GMAIL_FETCH_EMAILS", {"max_results": 2}, user_id="+111")


def test_not_connected_signal(capsys):
    fake = MagicMock(); fake.execute.side_effect = ca.NotConnected("no acct", slug="ActionExecute_ConnectedAccountNotFound")
    with patch.object(exec_tool, "ComposioClient", return_value=fake):
        rc = exec_tool.main(["GMAIL_FETCH_EMAILS", "{}"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["not_connected"] is True and rc == 2


def test_bad_json_args(capsys):
    rc = exec_tool.main(["GMAIL_FETCH_EMAILS", "{not json}"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and rc == 1
