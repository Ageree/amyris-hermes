"""Provision (or delete) the habit-tracker app DB for the served demo.

provision: create a Turso DB + tables via generate_app, print the token-free
manifest to stdout, and write the data-plane secrets (APP_DB_HOST, APP_DB_TOKEN)
to a file you can `source` to run server.py. The token is SECRET — write it only
to a chmod-600 file outside the repo, never commit it.

    TURSO_TOKEN=... python3 features/turso_apps/served/provision_app.py \
        --slug qa-habit-tracker --env-out /path/to/app.env
    source /path/to/app.env && python3 features/turso_apps/served/server.py

delete (cleanup — leave the org as found):
    TURSO_TOKEN=... python3 features/turso_apps/served/provision_app.py \
        --delete --slug qa-habit-tracker
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from features.turso_apps.generator import generate_app  # noqa: E402
from features.turso_apps.provisioner import TursoProvisioner, TursoError  # noqa: E402

# habit tracker: habits + entries (entries has its own columns, so use the dict spec form)
SPEC = {
    "name": "трекер привычек",
    "schema": {
        "habits": [
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            "title TEXT NOT NULL",
            "data TEXT",
            "created_at INTEGER NOT NULL",
        ],
        "entries": [
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            "habit_id INTEGER NOT NULL",
            "note TEXT",
            "created_at INTEGER NOT NULL",
        ],
    },
}


def provision(slug: str, env_out: str | None) -> int:
    prov = TursoProvisioner()
    spec = dict(SPEC, slug=slug)
    res = generate_app(spec, prov)
    manifest = res["manifest"]
    token = res["db_token"]

    # manifest is token-free → safe to print
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    if env_out:
        out = Path(env_out)
        out.write_text(
            f"export APP_DB_HOST={manifest['db_hostname']}\n"
            f"export APP_DB_TOKEN={token}\n"
        )
        out.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600 — secret token on disk
        print(f"\n[secrets written to {out} — mode 600; do not commit]", file=sys.stderr)
    return 0


def delete(slug: str) -> int:
    prov = TursoProvisioner()
    try:
        prov.delete_app_db(slug)
    except TursoError as e:
        print(f"delete failed (maybe already gone): {e}", file=sys.stderr)
    remaining = [d["db_name"] for d in prov.list_app_dbs()]
    if slug in remaining:
        print(f"FAIL: {slug} still present: {remaining}", file=sys.stderr)
        return 1
    print(f"deleted {slug}; remaining dbs: {remaining}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="qa-habit-tracker")
    ap.add_argument("--env-out", default=None, help="write APP_DB_HOST/APP_DB_TOKEN here (chmod 600)")
    ap.add_argument("--delete", action="store_true", help="delete the DB instead of creating it")
    args = ap.parse_args()

    if not (os.environ.get("TURSO_TOKEN") or os.environ.get("TURSO_PLATFORM_TOKEN")):
        print("ERROR: set TURSO_TOKEN (or TURSO_PLATFORM_TOKEN) in env", file=sys.stderr)
        return 2

    return delete(args.slug) if args.delete else provision(args.slug, args.env_out)


if __name__ == "__main__":
    raise SystemExit(main())
