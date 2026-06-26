"""Turso platform-API provisioner for per-app databases.

One personalized AI "app" == one Turso database. This module is the control-plane
side: create / list / delete the database and mint a data-plane auth token for it.

Platform API base: https://api.turso.tech/v1
Auth:              Authorization: Bearer <TURSO_PLATFORM_TOKEN>   (org-scoped)
Org slug:          ageree   (overridable)

A database must live in a *group* (the compute/replica unit). The `ageree` org
starts with zero groups, so `create_app_db` lazily ensures one exists
(`ensure_group`) — discovering the named/first existing group, or creating it.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

API_BASE = "https://api.turso.tech/v1"
DEFAULT_ORG = "ageree"
DEFAULT_GROUP = "default"
# AWS US-East (Virginia) — the closest Turso edge to the US AgentPhone numbers this
# stack uses. Override per-app if a tenant is region-pinned.
DEFAULT_LOCATION = "aws-us-east-1"
DEFAULT_TIMEOUT = 30


class TursoError(RuntimeError):
    """A Turso platform-API call returned a non-success status."""


class TursoProvisioner:
    def __init__(
        self,
        token: str | None = None,
        org: str = DEFAULT_ORG,
        location: str = DEFAULT_LOCATION,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        token = token or os.environ.get("TURSO_PLATFORM_TOKEN") or os.environ.get("TURSO_TOKEN")
        if not token:
            raise ValueError(
                "Turso token missing: pass token= or set TURSO_PLATFORM_TOKEN / TURSO_TOKEN"
            )
        self._token = token
        self.org = org
        self.location = location
        self.timeout = timeout
        self._s = requests.Session()
        self._s.headers.update({"Authorization": f"Bearer {token}"})

    # ---- low-level ---------------------------------------------------------
    def _call(self, method: str, path: str, **kw) -> Any:
        url = f"{API_BASE}/organizations/{self.org}/{path}".rstrip("/")
        resp = self._s.request(method, url, timeout=self.timeout, **kw)
        if resp.status_code >= 300:
            raise TursoError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.text:
            return resp.json()
        return {}

    # ---- groups ------------------------------------------------------------
    def list_groups(self) -> list[dict]:
        return self._call("GET", "groups").get("groups", [])

    def ensure_group(self, name: str = DEFAULT_GROUP) -> str:
        """Return a ready group name, creating `name` if the org has none.

        Preference: the group named `name` if it exists, else the first existing
        group, else create `name` in self.location and wait until its primary is up.
        """
        groups = self.list_groups()
        for g in groups:
            if g.get("name") == name:
                return name
        if groups:
            return groups[0]["name"]

        self._call("POST", "groups", json={"name": name, "location": self.location})
        # Group provisioning is async; the database create will 4xx until the
        # primary replica is assigned. Poll briefly.
        for _ in range(30):
            for g in self.list_groups():
                if g.get("name") == name and g.get("primary"):
                    return name
            time.sleep(1)
        raise TursoError(f"group {name!r} did not become ready in time")

    # ---- databases ---------------------------------------------------------
    def create_app_db(self, app_slug: str, group: str | None = None) -> dict:
        """Provision a database for an app and mint a full-access token for it.

        Returns {db_name, hostname, db_token, group}. db_token is a long-lived
        full-access JWT for the *data plane* (used by libsql_http) — distinct from
        the org platform token.
        """
        db_name = _normalize_slug(app_slug)
        grp = group or self.ensure_group()
        created = self._call(
            "POST", "databases", json={"name": db_name, "group": grp}
        ).get("database", {})
        # Create echoes capitalized keys (Name/Hostname); list uses lowercase.
        hostname = created.get("Hostname") or created.get("hostname")
        name = created.get("Name") or created.get("name") or db_name
        if not hostname:
            raise TursoError(f"create returned no hostname: {created}")
        token = self.mint_db_token(name)
        return {"db_name": name, "hostname": hostname, "db_token": token, "group": grp}

    def mint_db_token(self, db_name: str, authorization: str = "full-access") -> str:
        body = self._call(
            "POST",
            f"databases/{db_name}/auth/tokens",
            params={"authorization": authorization},
        )
        token = body.get("jwt")
        if not token:
            raise TursoError(f"token mint returned no jwt: {body}")
        return token

    def list_app_dbs(self) -> list[dict]:
        """List databases as [{db_name, hostname, group}, ...]."""
        dbs = self._call("GET", "databases").get("databases", [])
        return [
            {
                "db_name": d.get("Name") or d.get("name"),
                "hostname": d.get("Hostname") or d.get("hostname"),
                "group": d.get("group"),
            }
            for d in dbs
        ]

    def delete_app_db(self, name: str) -> dict:
        return self._call("DELETE", f"databases/{_normalize_slug(name)}")


def _normalize_slug(slug: str) -> str:
    """Turso db names: lowercase, [a-z0-9-], no leading/trailing dash. Be strict at
    this trust boundary so a bad app name can't smuggle a path segment."""
    s = "".join(c if (c.isalnum() or c == "-") else "-" for c in slug.strip().lower())
    s = "-".join(part for part in s.split("-") if part)  # collapse runs / trim
    if not s:
        raise ValueError(f"app_slug {slug!r} normalizes to empty")
    return s[:58]  # Turso caps db names well under this
