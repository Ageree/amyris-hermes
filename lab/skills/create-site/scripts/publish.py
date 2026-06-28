#!/usr/bin/env python3
"""Publish a generated site/app to the chat-sites control plane.

Called by the Hermes `create-site` skill via the agent's terminal tool. Reads
CONVEX_URL + SITES_PUBLISH_SECRET (+ optional USER_ID) from the environment,
POSTs the document to the `sites:publish` Convex action, and prints the live URL
on success (the agent then sends that URL back to the user).

Stdlib only — no third-party deps, so it runs in any agent container.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def build_payload(args: argparse.Namespace, secret: str) -> dict:
    """Assemble the action args from CLI flags + files (pure; unit-testable)."""
    with open(args.html_file, encoding="utf-8") as f:
        html = f.read()
    if not html.strip():
        raise ValueError("html file is empty")
    payload: dict = {"secret": secret, "handle": args.handle, "kind": args.kind, "html": html}
    if args.title:
        payload["title"] = args.title
    if args.kind == "app":
        if not args.schema_file:
            raise ValueError("--schema-file is required for kind=app")
        with open(args.schema_file, encoding="utf-8") as f:
            payload["schema"] = f.read()
    uid = os.environ.get("USER_ID")
    if uid:
        payload["userId"] = uid
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Publish a generated site/app.")
    ap.add_argument("--handle", required=True, help="public slug (a-z0-9-, 2..63)")
    ap.add_argument("--kind", required=True, choices=["static", "app"])
    ap.add_argument("--html-file", required=True, help="path to the single-file HTML document")
    ap.add_argument("--schema-file", help="path to CREATE TABLE ...; (required for kind=app)")
    ap.add_argument("--title")
    args = ap.parse_args(argv)

    base = os.environ.get("CONVEX_URL", "").rstrip("/")
    secret = os.environ.get("SITES_PUBLISH_SECRET", "")
    if not base or not secret:
        print("ERROR: CONVEX_URL / SITES_PUBLISH_SECRET not set in environment", file=sys.stderr)
        return 2

    try:
        payload = build_payload(args, secret)
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    body = json.dumps({"path": "sites:publish", "args": payload, "format": "json"}).encode()
    req = urllib.request.Request(
        f"{base}/api/action", data=body,
        headers={"content-type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"ERROR: HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"ERROR: network: {e}", file=sys.stderr)
        return 1

    if res.get("status") != "success":
        print(f"ERROR: {res.get('errorMessage', res)}", file=sys.stderr)
        return 1
    print(res["value"]["url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
