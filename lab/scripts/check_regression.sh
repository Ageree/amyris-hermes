#!/usr/bin/env bash
# CI / regression gate for the multi-tenancy build.
#
# Runs the single-user golden-path canary + the full network-free suite. This is
# the non-decreasing floor at every phase boundary — if it fails, the live
# operator path may be at risk, so STOP and investigate before proceeding.
#
# Usage: bash lab/scripts/check_regression.sh
set -euo pipefail
cd "$(dirname "$0")/.."   # -> lab/

echo "== single-user golden-path canary =="
python3 -m pytest -q tests/test_regression_single_user.py

echo "== full network-free suite (excludes convex_e2e + live_channel) =="
python3 -m pytest -q -m "not convex_e2e and not live_channel"

echo "REGRESSION_OK"
