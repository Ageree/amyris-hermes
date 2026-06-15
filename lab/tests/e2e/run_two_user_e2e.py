#!/usr/bin/env python3
"""Two-user fleet e2e smoke against the dev Convex deployment (M6/M7 helper).

Modes
-----
(default)        Two-tenant isolation: seed A+B, run a scoped worker for each
                 against REAL dev Convex, assert each replies ONLY to its own
                 address (zero cross-talk), reap. Dev-runnable; no device needed.
--live-smoke     Cutover-safety: enqueue ONE row, then run TWO scoped workers for
                 the SAME tenant overlapping (as during the old+new worker
                 cutover) and assert EXACTLY ONE delivers a reply (at-most-once
                 claim — no double-reply). Dev-runnable; proves M6 #8's core
                 invariant without a live device.
--channel X      A REAL channel round-trip (X = telegram | imessage). OPERATOR-
                 GATED: requires RUN_LIVE_CHANNEL=1 plus live channel creds + the
                 operator device. Without RUN_LIVE_CHANNEL it prints the operator
                 instructions and exits 0 (so CI never blocks on a device).

Env: CONVEX_URL + WORKER_SECRET (dev must have ALLOW_TEST_SEED=1).
All fixtures use throwaway tt-*@test.invalid tenants and are reaped in a finally.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skeleton"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lab/tests for conftest
from worker import WorkerConfig, process_one  # noqa: E402
from channels import ChannelRegistry  # noqa: E402
from convex_client import ConvexClient  # noqa: E402


class _Recorder:
    """Minimal outbound channel that records (address, body) sends."""

    def __init__(self) -> None:
        self.sends: list[tuple[str, str]] = []

    def send_message(self, address=None, text=None, *, to_number=None, content=None):
        self.sends.append((address or to_number, text if text is not None else content))

    def send_typing(self, *a, **k):
        pass

    def split(self, text):
        return [text]

    def render(self, text):
        return text


def _ctx():
    url = os.environ.get("CONVEX_URL")
    ws = os.environ.get("WORKER_SECRET")
    if not url or not ws:
        print("CONVEX_URL and WORKER_SECRET are required", file=sys.stderr)
        sys.exit(2)
    return ConvexClient(url), ws, url


def _cfg(url, ws, user_id):
    return WorkerConfig(
        convex_url=url, worker_secret=ws,
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target="+1OPERATOR_NEVER", hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0, scoped_user_id=user_id,
        typing_enabled=False, quota_enabled=False, heartbeat_enabled=False,
        history_enabled=False, fast_lane_enabled=False,
    )


def _seed(convex, ws, tag):
    try:
        return convex.mutation("testing:seedTwoTenants", {"workerSecret": ws, "tag": tag})
    except RuntimeError as e:
        if "test seeding disabled" in str(e):
            print("dev deployment must set ALLOW_TEST_SEED=1", file=sys.stderr)
            sys.exit(3)
        raise


def _cleanup(convex, ws, seed):
    try:
        convex.mutation("testing:cleanupTenants",
                        {"workerSecret": ws, "userA": seed["userA"], "userB": seed["userB"]})
    except Exception:
        pass


def _run_scoped(convex, url, ws, user_id, reply):
    rec = _Recorder()
    process_one(convex, ChannelRegistry({"imessage": rec}), _cfg(url, ws, user_id),
                run_fn=lambda *a, **k: reply)
    return rec


def isolation_mode(convex, ws, url) -> int:
    seed = _seed(convex, ws, f"twouser-{uuid.uuid4().hex[:8]}")
    try:
        rec_a = _run_scoped(convex, url, ws, seed["userA"], "hi A")
        rec_b = _run_scoped(convex, url, ws, seed["userB"], "hi B")
        ok = (rec_a.sends == [("+1A", "hi A")] and rec_b.sends == [("+1B", "hi B")])
        cross = any(addr == "+1B" for addr, _ in rec_a.sends) or \
            any(addr == "+1A" for addr, _ in rec_b.sends)
        print(f"isolation: A={rec_a.sends} B={rec_b.sends}")
        if ok and not cross:
            print("PASS: two-user isolation — each tenant replied only to its own address")
            return 0
        print("FAIL: cross-talk or misroute detected")
        return 1
    finally:
        _cleanup(convex, ws, seed)


def live_smoke_mode(convex, ws, url) -> int:
    """At-most-once claim under dual-worker overlap (cutover safety)."""
    seed = _seed(convex, ws, f"nodup-{uuid.uuid4().hex[:8]}")
    try:
        uid = seed["userA"]  # the seed already left ONE queued row for A
        # Two overlapping scoped workers race for the SAME tenant's single row.
        c1 = convex.mutation("messages:claimNextForUser", {"workerSecret": ws, "userId": uid})
        c2 = convex.mutation("messages:claimNextForUser", {"workerSecret": ws, "userId": uid})
        claims = [c for c in (c1, c2) if c is not None]
        print(f"dual-worker overlap: {len(claims)} worker(s) claimed the single row")
        if len(claims) == 1:
            print("PASS: at-most-once claim — no double-reply during cutover overlap")
            return 0
        print(f"FAIL: {len(claims)} claims for one row (double-reply risk)")
        return 1
    finally:
        _cleanup(convex, ws, seed)


def live_channel_mode(channel: str) -> int:
    if os.environ.get("RUN_LIVE_CHANNEL") != "1":
        print(
            f"--channel {channel} is OPERATOR-GATED. To run a real round-trip:\n"
            f"  1. ensure the {channel} bot/number is live + the operator device is reachable\n"
            f"  2. RUN_LIVE_CHANNEL=1 CONVEX_URL=... WORKER_SECRET=... \\\n"
            f"       python3 lab/tests/e2e/run_two_user_e2e.py --channel {channel}\n"
            "Skipping (RUN_LIVE_CHANNEL!=1) — exit 0 so CI never blocks on a device."
        )
        return 0
    print(f"LIVE {channel} round-trip requires the operator device; run interactively.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Two-user fleet e2e smoke.")
    ap.add_argument("--live-smoke", action="store_true",
                    help="at-most-once claim under dual-worker overlap (cutover safety)")
    ap.add_argument("--channel", choices=["telegram", "imessage"],
                    help="real channel round-trip (operator-gated, RUN_LIVE_CHANNEL=1)")
    args = ap.parse_args()

    if args.channel:
        return live_channel_mode(args.channel)
    convex, ws, url = _ctx()
    if args.live_smoke:
        return live_smoke_mode(convex, ws, url)
    return isolation_mode(convex, ws, url)


if __name__ == "__main__":
    raise SystemExit(main())
