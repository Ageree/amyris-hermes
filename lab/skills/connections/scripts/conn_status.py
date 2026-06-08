#!/usr/bin/env python3
"""Report Composio connection status for a toolkit/user."""
import argparse, json, sys
from composio_api import ComposioClient


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check Composio connection status.")
    ap.add_argument("toolkit")
    ap.add_argument("--user-id", default=None)
    args = ap.parse_args(argv)
    try:
        client = ComposioClient(user_id=args.user_id)
        status = client.connection_status(args.toolkit, user_id=args.user_id)
        print(json.dumps({"ok": True, "toolkit": args.toolkit, "status": status}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "toolkit": args.toolkit, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
