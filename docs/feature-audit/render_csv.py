#!/usr/bin/env python3
"""Render the canonical feature spreadsheet (feature-status.csv) from features.json.

features.json is the source of truth (a JSON list of feature objects). This script
writes feature-status.csv with correct CSV quoting via the stdlib csv module, so agents
never hand-escape commas/quotes. Run from anywhere: `python3 docs/feature-audit/render_csv.py`.

Exit non-zero if a row is missing a required Phase-1 field, so a broken catalog is caught.
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "features.json")
OUT = os.path.join(HERE, "feature-status.csv")

# Column order = lifecycle across the 4 phases.
COLUMNS = [
    "id",                 # WEB-01, CP-01, ASST-01, CTRL-01 ...
    "area",               # web | control-plane | assistant | fleet-controller
    "feature",
    "user_story",
    "expected_behavior",
    "source_refs",        # file:line; semicolon-separated
    "verify_method",      # how Phase 2 tests it (hermetic/test-seam)
    "p1_catalog",         # done
    "p2_test_status",     # pending | pass | fail | blocked
    "p2_evidence",
    "error_found",
    "severity",           # none | low | med | high | crit
    "error_type",         # none | logical | ux
    "p3_fix_status",      # n/a | pending | done | deferred
    "p3_fix_ref",
    "p4_retest_status",   # n/a | pending | pass | fail | blocked
    "notes",
]

REQUIRED_P1 = ["id", "area", "feature", "user_story", "expected_behavior",
               "source_refs", "verify_method"]

DEFAULTS = {
    "p1_catalog": "done",
    "p2_test_status": "pending",
    "p2_evidence": "",
    "error_found": "",
    "severity": "none",
    "error_type": "none",
    "p3_fix_status": "n/a",
    "p3_fix_ref": "",
    "p4_retest_status": "n/a",
    "notes": "",
}


def main() -> int:
    if not os.path.exists(SRC):
        print(f"ERROR: {SRC} not found", file=sys.stderr)
        return 2
    with open(SRC, encoding="utf-8") as fh:
        rows = json.load(fh)
    if not isinstance(rows, list):
        print("ERROR: features.json must be a JSON list", file=sys.stderr)
        return 2

    ids = set()
    problems = []
    for i, r in enumerate(rows):
        for k in REQUIRED_P1:
            if not str(r.get(k, "")).strip():
                problems.append(f"row {i} ({r.get('id', '?')}) missing required field '{k}'")
        rid = r.get("id", "")
        if rid in ids:
            problems.append(f"duplicate id '{rid}'")
        ids.add(rid)
    if problems:
        for p in problems:
            print("ERROR:", p, file=sys.stderr)
        return 1

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            merged = {**DEFAULTS, **r}
            w.writerow({c: merged.get(c, "") for c in COLUMNS})

    print(f"OK: wrote {len(rows)} rows -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
