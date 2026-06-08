"""Unit tests for the thin Composio v3 REST client. requests is mocked (no network)."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "connections" / "scripts"))
import composio_api as ca  # noqa: E402


def _resp(status=200, body=None):
    m = MagicMock(status_code=status)
    m.json = lambda: (body if body is not None else {})
    m.text = str(body)
    return m


def test_create_link_returns_redirect_url():
    c = ca.ComposioClient(api_key="ak_x", user_id="+111")
    with patch.object(ca.requests, "get") as g, patch.object(ca.requests, "post") as p:
        g.return_value = _resp(200, {"items": [{"id": "ac_gmail", "toolkit": {"slug": "gmail"}, "is_composio_managed": True}]})
        p.return_value = _resp(201, {"redirect_url": "https://connect.composio.dev/link/lk_1", "connected_account_id": "ca_1"})
        out = c.create_link("gmail")
    assert out["redirect_url"].startswith("https://connect.composio.dev/link/")
    assert p.call_args.kwargs["json"] == {"auth_config_id": "ac_gmail", "user_id": "+111"}
    assert p.call_args.kwargs["headers"]["x-api-key"] == "ak_x"


def test_connection_status_active_when_any_item_active():
    c = ca.ComposioClient(api_key="ak_x", user_id="+111")
    with patch.object(ca.requests, "get") as g:
        g.return_value = _resp(200, {"items": [{"status": "EXPIRED", "toolkit": {"slug": "gmail"}}, {"status": "ACTIVE", "toolkit": {"slug": "gmail"}}]})
        assert c.connection_status("gmail") == "ACTIVE"
        # uses plural query params + the user_id
        assert g.call_args.kwargs["params"] == {"user_ids": "+111", "toolkit_slugs": "gmail"}


def test_connection_status_none_when_no_items():
    c = ca.ComposioClient(api_key="ak_x", user_id="+111")
    with patch.object(ca.requests, "get") as g:
        g.return_value = _resp(200, {"items": []})
        assert c.connection_status("gmail") == "none"


def test_list_tools_returns_slugs_with_singular_param():
    c = ca.ComposioClient(api_key="ak_x", user_id="+111")
    with patch.object(ca.requests, "get") as g:
        g.return_value = _resp(200, {"items": [{"slug": "GMAIL_FETCH_EMAILS"}, {"slug": "GMAIL_SEND_EMAIL"}]})
        slugs = c.list_tools("gmail")
        assert slugs == ["GMAIL_FETCH_EMAILS", "GMAIL_SEND_EMAIL"]
        assert g.call_args.kwargs["params"]["toolkit_slug"] == "gmail"


def test_execute_raises_not_connected_on_connectedaccountnotfound():
    c = ca.ComposioClient(api_key="ak_x", user_id="+111")
    with patch.object(ca.requests, "post") as p:
        p.return_value = _resp(400, {"error": {"slug": "ActionExecute_ConnectedAccountNotFound", "message": "no acct"}})
        try:
            c.execute("GMAIL_FETCH_EMAILS", {"max_results": 1})
            assert False, "expected NotConnected"
        except ca.NotConnected:
            pass


def test_execute_passes_user_id_and_arguments():
    c = ca.ComposioClient(api_key="ak_x", user_id="+111")
    with patch.object(ca.requests, "post") as p:
        p.return_value = _resp(200, {"data": {"messages": []}})
        c.execute("GMAIL_FETCH_EMAILS", {"max_results": 2})
        assert p.call_args.args[0].endswith("/api/v3/tools/execute/GMAIL_FETCH_EMAILS")
        assert p.call_args.kwargs["json"] == {"user_id": "+111", "arguments": {"max_results": 2}}


def test_missing_api_key_raises():
    try:
        ca.ComposioClient(api_key="", user_id="+111")
        assert False, "expected ValueError"
    except ValueError:
        pass
