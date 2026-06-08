#!/usr/bin/env python3
"""Generate a Composio connect-link (the Poke "tap to grant access" link)."""
import argparse, json, sys
from composio_api import ComposioClient


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Create a Composio OAuth connect-link.")
    ap.add_argument("toolkit", help="toolkit slug, e.g. gmail, googlecalendar, notion")
    ap.add_argument("--user-id", default=None, help="E.164 number; default COMPOSIO_USER_ID")
    args = ap.parse_args(argv)
    try:
        client = ComposioClient(user_id=args.user_id)
        res = client.create_link(args.toolkit, user_id=args.user_id)
        print(json.dumps({"ok": True, "toolkit": args.toolkit, **res}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "toolkit": args.toolkit, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
