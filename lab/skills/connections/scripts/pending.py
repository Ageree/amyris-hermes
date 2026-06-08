#!/usr/bin/env python3
"""Record a connect-intent in Convex so the worker can auto-resume the task
once the user connects. Run BEFORE replying with connect-link(s)."""
import argparse, json, os, sys
from pathlib import Path

# Reuse the skeleton's Convex HTTP client (repo layout) or a co-located copy (deployed).
# From lab/skills/connections/scripts/pending.py:
#   parents[0] = scripts dir
#   parents[1] = connections dir
#   parents[2] = skills dir
#   parents[3] = lab dir  ->  lab/skeleton/convex_client.py
for _cand in (Path(__file__).resolve().parent,
              Path(__file__).resolve().parents[3] / "skeleton"):
    if (_cand / "convex_client.py").exists():
        sys.path.insert(0, str(_cand)); break
from convex_client import ConvexClient  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Record/resolve a connect intent.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("--task", required=True, help="the user's verbatim request")
    add.add_argument("--toolkits", required=True, help="comma-separated slugs needed")
    add.add_argument("--user-id", default=None, help="E.164; default COMPOSIO_USER_ID")
    a = ap.parse_args(argv)
    try:
        convex_url = os.environ["CONVEX_URL"]
        worker_secret = os.environ["WORKER_SECRET"]
        user_id = a.user_id or os.environ.get("COMPOSIO_USER_ID", "")
        if not user_id:
            raise ValueError("user_id required (pass --user-id or set COMPOSIO_USER_ID)")
        toolkits = [t.strip() for t in a.toolkits.split(",") if t.strip()]
        client = ConvexClient(convex_url)
        intent_id = client.mutation("intents:addIntent", {
            "workerSecret": worker_secret, "userNumber": user_id,
            "taskText": a.task, "requiredToolkits": toolkits,
        })
        print(json.dumps({"ok": True, "intent_id": intent_id, "toolkits": toolkits}))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
