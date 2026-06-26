"""Served habit-tracker app, backed by a per-app Turso database.

A minimal stdlib `http.server` that renders one page and proxies three JSON
endpoints to the app's Turso data plane via the dependency-free `libsql_http`
client. The data-plane token lives ONLY in this process (env `APP_DB_TOKEN`);
it never reaches the browser — the client talks to /api/*, this server talks to
Turso.

Run (token + host come from `generate_app`, see provision_app.py / README):
    APP_DB_HOST=<db-hostname> APP_DB_TOKEN=<jwt> \
        python3 features/turso_apps/served/server.py --port 8771

ponytail: single-tenant localhost demo — no per-user auth on /api/* (the real
multi-tenant serving layer is Convex, which gates by signed-in user). Ceiling:
anyone who can reach 127.0.0.1:<port> can edit this one app's habits. Upgrade
path: front it with the tenant-auth middleware before exposing off-localhost.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Allow running as a plain script: put repo root on sys.path so the package imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from features.turso_apps import libsql_http  # noqa: E402
from features.turso_apps.libsql_http import LibsqlError  # noqa: E402

HERE = Path(__file__).resolve().parent
INDEX_HTML = HERE / "index.html"
MAX_TITLE_LEN = 200


def _today_start_ms() -> int:
    """Epoch-ms at local midnight today — the boundary for 'done today'."""
    now = datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1000)


class HabitStore:
    """Thin data-access layer over one app's Turso DB."""

    def __init__(self, host: str, token: str):
        if not host or not token:
            raise ValueError("HabitStore needs both host and token")
        self._host = host
        self._token = token

    def list_habits(self) -> list[dict]:
        """All habits, newest first, each annotated with today's + total check counts."""
        today = _today_start_ms()
        results = libsql_http.execute_many(
            self._host,
            self._token,
            [
                ("SELECT id, title, created_at FROM habits ORDER BY created_at DESC;", None),
                ("SELECT habit_id, COUNT(*) FROM entries WHERE created_at >= ? GROUP BY habit_id;", [today]),
                ("SELECT habit_id, COUNT(*) FROM entries GROUP BY habit_id;", None),
            ],
        )
        today_counts = {row[0]: row[1] for row in results[1]["rows"]}
        total_counts = {row[0]: row[1] for row in results[2]["rows"]}
        return [
            {
                "id": row[0],
                "title": row[1],
                "created_at": row[2],
                "done_today": today_counts.get(row[0], 0) > 0,
                "checks": total_counts.get(row[0], 0),
            }
            for row in results[0]["rows"]
        ]

    def add_habit(self, title: str) -> dict:
        now = int(time.time() * 1000)
        res = libsql_http.execute(
            self._host,
            self._token,
            "INSERT INTO habits (title, data, created_at) VALUES (?, ?, ?) RETURNING id;",
            [title, "{}", now],
        )
        new_id = res["rows"][0][0]
        return {"id": new_id, "title": title, "created_at": now, "done_today": False, "checks": 0}

    def check_today(self, habit_id: int) -> dict:
        """Mark a habit done today (idempotent — at most one check per day). Returns new state."""
        today = _today_start_ms()
        # Habit must exist (don't create orphan entries pointing at nothing).
        owner = libsql_http.execute(
            self._host, self._token, "SELECT id FROM habits WHERE id = ?;", [habit_id]
        )
        if not owner["rows"]:
            raise KeyError(habit_id)

        already = libsql_http.execute(
            self._host,
            self._token,
            "SELECT COUNT(*) FROM entries WHERE habit_id = ? AND created_at >= ?;",
            [habit_id, today],
        )
        if already["rows"][0][0] == 0:
            libsql_http.execute(
                self._host,
                self._token,
                "INSERT INTO entries (habit_id, note, created_at) VALUES (?, ?, ?);",
                [habit_id, "done", int(time.time() * 1000)],
            )
        total = libsql_http.execute(
            self._host, self._token, "SELECT COUNT(*) FROM entries WHERE habit_id = ?;", [habit_id]
        )
        return {"id": habit_id, "done_today": True, "checks": total["rows"][0][0]}


class Handler(BaseHTTPRequestHandler):
    store: HabitStore  # injected on the server instance

    # --- helpers ---------------------------------------------------------
    def _send_json(self, obj: dict | list, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise ValueError("body is not valid JSON")
        if not isinstance(parsed, dict):
            raise ValueError("body must be a JSON object")
        return parsed

    def log_message(self, *args) -> None:  # quieter default logging
        pass

    # --- routing ---------------------------------------------------------
    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            return self._serve_index()
        if self.path == "/api/habits":
            return self._get_habits()
        self._error(404, "not found")

    def do_POST(self) -> None:
        if self.path == "/api/habits":
            return self._post_habit()
        if self.path.startswith("/api/habits/") and self.path.endswith("/check"):
            return self._post_check(self.path[len("/api/habits/") : -len("/check")])
        self._error(404, "not found")

    # --- handlers --------------------------------------------------------
    def _serve_index(self) -> None:
        try:
            body = INDEX_HTML.read_bytes()
        except OSError:
            return self._error(500, "index.html missing")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_habits(self) -> None:
        try:
            self._send_json({"habits": self.store.list_habits()})
        except LibsqlError as e:
            self._error(502, f"database error: {e}")

    def _post_habit(self) -> None:
        try:
            data = self._read_json_body()
        except ValueError as e:
            return self._error(400, str(e))
        # Trust-boundary validation: title required, non-empty, bounded.
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            return self._error(400, "title is required and must be a non-empty string")
        title = title.strip()
        if len(title) > MAX_TITLE_LEN:
            return self._error(400, f"title too long (max {MAX_TITLE_LEN})")
        try:
            self._send_json(self.store.add_habit(title), status=201)
        except LibsqlError as e:
            self._error(502, f"database error: {e}")

    def _post_check(self, id_segment: str) -> None:
        # Trust-boundary validation: id must be a positive integer.
        try:
            habit_id = int(id_segment)
        except ValueError:
            return self._error(400, "habit id must be an integer")
        if habit_id <= 0:
            return self._error(400, "habit id must be positive")
        try:
            self._send_json(self.store.check_today(habit_id))
        except KeyError:
            self._error(404, "no such habit")
        except LibsqlError as e:
            self._error(502, f"database error: {e}")


def make_server(host: str, token: str, port: int) -> ThreadingHTTPServer:
    handler_cls = type("BoundHandler", (Handler,), {"store": HabitStore(host, token)})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    return httpd


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the Turso-backed habit tracker on localhost.")
    ap.add_argument("--port", type=int, default=8771)
    args = ap.parse_args()

    host = os.environ.get("APP_DB_HOST")
    token = os.environ.get("APP_DB_TOKEN")
    if not host or not token:
        print("ERROR: set APP_DB_HOST and APP_DB_TOKEN in the environment", file=sys.stderr)
        return 2

    httpd = make_server(host, token, args.port)
    print(f"serving habit tracker on http://127.0.0.1:{args.port}  (db host: {host})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
