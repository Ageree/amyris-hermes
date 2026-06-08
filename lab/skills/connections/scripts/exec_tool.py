#!/usr/bin/env python3
"""Execute a Composio tool for the user, or list a toolkit's tool slugs.

Usage:
  exec_tool.py --list gmail
  exec_tool.py GMAIL_FETCH_EMAILS '{"max_results":3}' [--user-id +111]
"""
import argparse, json, sys
from composio_api import ComposioClient, NotConnected


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Execute or list Composio tools.")
    ap.add_argument("slug", nargs="?", help="tool slug, e.g. GMAIL_FETCH_EMAILS")
    ap.add_argument("args", nargs="?", default="{}", help="JSON object of arguments")
    ap.add_argument("--list", dest="list_toolkit", default=None, help="list tools for a toolkit")
    ap.add_argument("--user-id", default=None)
    a = ap.parse_args(argv)
    try:
        client = ComposioClient(user_id=a.user_id)
        if a.list_toolkit:
            print(json.dumps({"ok": True, "toolkit": a.list_toolkit, "tools": client.list_tools(a.list_toolkit)}))
            return 0
        if not a.slug:
            print(json.dumps({"ok": False, "error": "slug required (or use --list <toolkit>)"})); return 1
        try:
            arguments = json.loads(a.args)
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"bad --args JSON: {e}"})); return 1
        result = client.execute(a.slug, arguments, user_id=a.user_id)
        print(json.dumps({"ok": True, "slug": a.slug, "result": result}))
        return 0
    except NotConnected as e:
        print(json.dumps({"ok": False, "not_connected": True, "error": str(e)}))
        return 2
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
