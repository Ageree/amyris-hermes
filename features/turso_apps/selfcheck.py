"""Runnable self-check for the Turso app generator.

Offline part : asserts the pure helpers (slug normalize, value codec, spec->tables).
Online  part : provisions a THROWAWAY db 'qa-overnight-test' via generate_app,
               writes + reads a row, asserts it round-trips, then DELETES the db
               (verified gone). Requires TURSO_TOKEN / TURSO_PLATFORM_TOKEN in env.

Run from the repo root:
    TURSO_TOKEN=... python3 -m features.turso_apps.selfcheck
or directly:
    TURSO_TOKEN=... python3 features/turso_apps/selfcheck.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Allow running as a plain script (not just `-m`): put repo root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from features.turso_apps import libsql_http  # noqa: E402
from features.turso_apps.generator import _tables_from_spec, generate_app  # noqa: E402
from features.turso_apps.provisioner import TursoProvisioner, TursoError, _normalize_slug  # noqa: E402

TEST_SLUG = "qa-overnight-test"


def offline_checks() -> None:
    # slug normalization (trust boundary)
    assert _normalize_slug("Habit Tracker!!") == "habit-tracker"
    assert _normalize_slug("  --Foo__Bar--  ") == "foo-bar", _normalize_slug("  --Foo__Bar--  ")
    try:
        _normalize_slug("***")
        raise AssertionError("expected empty-slug rejection")
    except ValueError:
        pass

    # value codec round-trips
    for v in ["hi", 42, True, 3.5, None, b"\x00\x01"]:
        enc = libsql_http._encode_arg(v)
        if v is None:
            assert enc == {"type": "null"}
        elif isinstance(v, bool):
            assert enc["type"] == "integer" and enc["value"] in ("0", "1")
    assert libsql_http._decode_cell({"type": "integer", "value": "7"}) == 7
    assert libsql_http._decode_cell({"type": "null"}) is None
    assert libsql_http._decode_cell({"type": "text", "value": "x"}) == "x"

    # spec -> tables (both list and dict forms)
    t = _tables_from_spec(["habits", "entries"])
    assert set(t) == {"habits", "entries"} and all(t.values()), t
    t2 = _tables_from_spec({"notes": ["id INTEGER PRIMARY KEY", "body TEXT"]})
    assert t2 == {"notes": ["id INTEGER PRIMARY KEY", "body TEXT"]}, t2
    print("[offline] helper asserts PASSED")


def online_check() -> None:
    prov = TursoProvisioner()
    print(f"[online] org={prov.org} location={prov.location}")

    grp = prov.ensure_group()
    print(f"[online] group ensured: {grp}")

    # Pre-clean: a prior aborted run may have left the throwaway db.
    try:
        prov.delete_app_db(TEST_SLUG)
        print(f"[online] pre-existing {TEST_SLUG} removed")
    except TursoError:
        pass

    res = generate_app(
        {"name": "Habit Tracker", "slug": TEST_SLUG, "schema": ["habits", "entries"]},
        prov,
    )
    manifest = res["manifest"]
    token = res["db_token"]
    host = manifest["db_hostname"]
    print(f"[online] provisioned db={manifest['db_name']} host={host}")
    print(f"[online] manifest tables={[x['name'] for x in manifest['tables']]}")
    assert {x["name"] for x in manifest["tables"]} == {"habits", "entries"}
    assert len(token) > 20  # got a real jwt, not echoing it

    try:
        now = int(time.time() * 1000)
        libsql_http.execute(
            host, token,
            "INSERT INTO habits (title, data, created_at) VALUES (?, ?, ?);",
            ["drink water", '{"streak":3}', now],
        )
        read = libsql_http.execute(
            host, token,
            "SELECT id, title, data, created_at FROM habits WHERE title = ?;",
            ["drink water"],
        )
        print(f"[online] read back: columns={read['columns']} rows={read['rows']}")
        assert len(read["rows"]) == 1, read
        row = read["rows"][0]
        assert row[1] == "drink water", row
        assert row[2] == '{"streak":3}', row
        assert row[3] == now, row
        assert isinstance(row[0], int), row  # autoincrement id

        # second table really exists and is empty
        cnt = libsql_http.execute(host, token, "SELECT COUNT(*) FROM entries;")
        assert cnt["rows"][0][0] == 0, cnt
        print("[online] row round-trip + entries table PASSED")
    finally:
        prov.delete_app_db(TEST_SLUG)
        remaining = [d["db_name"] for d in prov.list_app_dbs()]
        assert TEST_SLUG not in remaining, f"cleanup failed; still present: {remaining}"
        print(f"[online] {TEST_SLUG} deleted; remaining dbs={remaining}")


def main() -> int:
    offline_checks()
    if not (os.environ.get("TURSO_TOKEN") or os.environ.get("TURSO_PLATFORM_TOKEN")):
        print("[skip] no TURSO_TOKEN in env — offline checks only")
        return 0
    online_check()
    print("\nSELF-CHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
