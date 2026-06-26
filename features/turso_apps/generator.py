"""Minimal personalized-app generator.

Given a short spec, provision a Turso database, create the tables, and return an
app *manifest* — the token-free descriptor that the serving layer needs to find
and render the app. The data-plane token is returned SEPARATELY so it never lands
in the manifest (which is meant to be persisted/served).

Spec shape (only `name` + table list are required):
    {"name": "Habit Tracker", "schema": ["habits", "entries"]}

`schema` is either:
    - a list of table names           -> each table gets the default columns, or
    - {"table": ["col TYPE", ...]}     -> explicit column defs per table.

ponytail: v1 = manifest + provisioned DB + tables. No frontend, no per-row CRUD
routes — the Convex serving layer (see integration note) is the renderer. Default
table shape is a generic key/value/json row, enough for a habit tracker, a notes
app, a tiny CRM, etc. Upgrade path: let the spec carry typed columns + indexes
(the dict form already threads through here) and generate seed rows.
"""
from __future__ import annotations

import time
from typing import Any

from . import libsql_http
from .provisioner import TursoProvisioner, _normalize_slug

# A generic, useful default row for a personalized micro-app table.
DEFAULT_COLUMNS = [
    "id INTEGER PRIMARY KEY AUTOINCREMENT",
    "title TEXT NOT NULL",
    "data TEXT",                     # JSON blob for app-specific fields
    "created_at INTEGER NOT NULL",
]


def _tables_from_spec(schema: Any) -> dict[str, list[str]]:
    if isinstance(schema, dict):
        out = {}
        for name, cols in schema.items():
            if not isinstance(cols, (list, tuple)) or not cols:
                raise ValueError(f"table {name!r}: columns must be a non-empty list")
            out[_normalize_slug(name).replace("-", "_")] = list(cols)
        return out
    if isinstance(schema, (list, tuple)):
        return {_normalize_slug(t).replace("-", "_"): list(DEFAULT_COLUMNS) for t in schema}
    raise ValueError("spec['schema'] must be a list of names or a {table: [columns]} dict")


def generate_app(spec: dict, provisioner: TursoProvisioner | None = None) -> dict:
    """Provision + build an app from `spec`. Returns:
        {"manifest": {slug, name, db_hostname, db_name, group, tables, created_at},
         "db_token": "<full-access jwt>"}

    The manifest is token-free and safe to persist/serve; db_token is the secret
    the serving layer must store out-of-band (Convex env / secret store).
    """
    if not isinstance(spec, dict):
        raise ValueError("spec must be a dict")
    name = str(spec.get("name", "")).strip()
    if not name:
        raise ValueError("spec['name'] is required")
    if "schema" not in spec:
        raise ValueError("spec['schema'] is required")

    tables = _tables_from_spec(spec["schema"])
    if not tables:
        raise ValueError("spec['schema'] produced no tables")

    slug = _normalize_slug(spec.get("slug") or name)
    prov = provisioner or TursoProvisioner()

    db = prov.create_app_db(slug)

    # Create every table in one pipeline round-trip (fail-fast on a bad column def).
    stmts = [
        (f"CREATE TABLE IF NOT EXISTS {tname} ({', '.join(cols)});", None)
        for tname, cols in tables.items()
    ]
    libsql_http.execute_many(db["hostname"], db["db_token"], stmts)

    manifest = {
        "slug": slug,
        "name": name,
        "db_hostname": db["hostname"],
        "db_name": db["db_name"],
        "group": db["group"],
        "tables": [{"name": t, "columns": c} for t, c in tables.items()],
        "created_at": int(time.time() * 1000),
    }
    return {"manifest": manifest, "db_token": db["db_token"]}
