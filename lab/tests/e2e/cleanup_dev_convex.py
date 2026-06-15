#!/usr/bin/env python3
"""Reap two throwaway tenants on the dev Convex deployment (M7 e2e helper).

Wraps the double-gated testing:cleanupTenants seam. SAFE: that mutation only ever
deletes users whose email matches tt-*@test.invalid, so a wrong/foreign id (incl.
the operator) is silently skipped — this can never nuke a real tenant.

Env: CONVEX_URL + WORKER_SECRET (dev must have ALLOW_TEST_SEED=1).
Usage:  python3 lab/tests/e2e/cleanup_dev_convex.py --userA <id> --userB <id>
   or:  python3 lab/tests/e2e/cleanup_dev_convex.py --seed-json seed.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skeleton"))
from convex_client import ConvexClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Reap two throwaway dev tenants.")
    ap.add_argument("--userA")
    ap.add_argument("--userB")
    ap.add_argument("--seed-json", help="path to a seed JSON from seed_dev_convex.py")
    args = ap.parse_args()

    user_a, user_b = args.userA, args.userB
    if args.seed_json:
        seed = json.loads(Path(args.seed_json).read_text())
        user_a, user_b = seed["userA"], seed["userB"]
    if not user_a or not user_b:
        print("provide --userA/--userB or --seed-json", file=sys.stderr)
        return 2

    url = os.environ.get("CONVEX_URL")
    ws = os.environ.get("WORKER_SECRET")
    if not url or not ws:
        print("CONVEX_URL and WORKER_SECRET are required", file=sys.stderr)
        return 2

    convex = ConvexClient(url)
    convex.mutation("testing:cleanupTenants",
                    {"workerSecret": ws, "userA": user_a, "userB": user_b})
    print(f"reaped {user_a} and {user_b} (throwaway-only; real users skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
