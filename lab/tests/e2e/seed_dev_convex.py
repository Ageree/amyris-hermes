#!/usr/bin/env python3
"""Seed two THROWAWAY tenants on the dev Convex deployment (M7 e2e helper).

Wraps the double-gated testing:seedTwoTenants seam so an operator can stand up a
two-tenant fixture by hand for a live smoke. Throwaway users use the
tt-*@test.invalid pattern and are reaped by cleanup_dev_convex.py — this NEVER
touches the operator's real rows.

Env: CONVEX_URL + WORKER_SECRET (dev must have ALLOW_TEST_SEED=1).
Usage:  python3 lab/tests/e2e/seed_dev_convex.py [--tag mytag]
Prints the seed JSON (userA/userB/msgA/msgB ids) so cleanup can reap them.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skeleton"))
from convex_client import ConvexClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed two throwaway dev tenants.")
    ap.add_argument("--tag", default=f"smoke-{uuid.uuid4().hex[:8]}")
    args = ap.parse_args()

    url = os.environ.get("CONVEX_URL")
    ws = os.environ.get("WORKER_SECRET")
    if not url or not ws:
        print("CONVEX_URL and WORKER_SECRET are required", file=sys.stderr)
        return 2

    convex = ConvexClient(url)
    try:
        seed = convex.mutation("testing:seedTwoTenants", {"workerSecret": ws, "tag": args.tag})
    except RuntimeError as e:
        if "test seeding disabled" in str(e):
            print("dev deployment must set ALLOW_TEST_SEED=1", file=sys.stderr)
            return 3
        raise
    print(json.dumps(seed, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
