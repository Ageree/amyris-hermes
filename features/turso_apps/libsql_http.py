"""Minimal libSQL/Turso HTTP client (Hrana-over-HTTP v2 "pipeline" protocol).

We talk to a Turso database's data plane directly over HTTPS instead of pulling
in the `libsql-client` package — the pipeline endpoint is a single POST and the
wire format is small, so a hand-rolled client is the lazy, dependency-free choice.

Endpoint:  POST https://<db-hostname>/v2/pipeline
Auth:      Authorization: Bearer <db-auth-token>
Docs:      https://docs.turso.tech/sdk/http/reference

ponytail: only the value types this feature uses (text/int/float/null/blob) are
encoded/decoded. The pipeline protocol supports more (e.g. per-request batons for
interactive transactions) — not needed for table-create + insert + read, which is
all the app generator does. Upgrade path: add a `baton` round-trip if you ever need
a multi-request interactive transaction.
"""
from __future__ import annotations

import base64
from typing import Any, Iterable

import requests

DEFAULT_TIMEOUT = 30


class LibsqlError(RuntimeError):
    """A statement (or the pipeline itself) failed on the libSQL server."""


def _encode_arg(v: Any) -> dict:
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):  # bool is a subclass of int — check first
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _decode_cell(cell: dict) -> Any:
    t = cell.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(cell["value"])
    if t == "float":
        return float(cell["value"])
    if t == "blob":
        return base64.b64decode(cell["base64"])
    return cell.get("value")  # text


def _stmt(sql: str, args: Iterable[Any] | None) -> dict:
    out: dict = {"sql": sql, "want_rows": True}
    if args:
        out["args"] = [_encode_arg(a) for a in args]
    return out


def execute_many(
    hostname: str,
    token: str,
    statements: list[tuple[str, list[Any] | None]],
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict]:
    """Run statements in order over one pipeline call. Returns one decoded result
    dict per statement: {"columns": [...], "rows": [[...], ...], "affected": int}.

    Raises LibsqlError on the first failing statement (fail-fast — we don't want a
    half-created schema reported as success).
    """
    if not hostname:
        raise ValueError("hostname is required")
    if not token:
        raise ValueError("token is required")

    requests_body = [{"type": "execute", "stmt": _stmt(sql, args)} for sql, args in statements]
    requests_body.append({"type": "close"})

    url = f"https://{hostname}/v2/pipeline"
    resp = requests.post(
        url,
        json={"requests": requests_body},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise LibsqlError(f"pipeline HTTP {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    decoded: list[dict] = []
    for item in body.get("results", []):
        if item.get("type") == "error":
            err = item.get("error", {})
            raise LibsqlError(f"libsql error: {err.get('message', err)}")
        response = item.get("response", {})
        if response.get("type") != "execute":
            continue  # the trailing close
        result = response.get("result", {})
        cols = [c.get("name") for c in result.get("cols", [])]
        rows = [[_decode_cell(cell) for cell in row] for row in result.get("rows", [])]
        decoded.append(
            {
                "columns": cols,
                "rows": rows,
                "affected": result.get("affected_row_count", 0),
            }
        )
    return decoded


def execute(
    hostname: str,
    token: str,
    sql: str,
    args: list[Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Convenience: run one statement, return its decoded result dict."""
    return execute_many(hostname, token, [(sql, args)], timeout=timeout)[0]
