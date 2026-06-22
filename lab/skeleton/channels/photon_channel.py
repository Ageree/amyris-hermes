"""iMessage rich transport via the Photon Spectrum sidecar (loopback HTTP).

PhotonChannel is the channel-layer counterpart to SendblueChannel: same duck-typed
Channel Protocol (render/split/send_message/send_typing) PLUS send_rich, but the
wire is the Hermes-shipped MIT Photon sidecar (`photon-sidecar/index.mjs`) instead
of the Sendblue REST API. The sidecar holds the project's Spectrum gRPC stream and
exposes a loopback control API; this class is a thin HTTP client to it (bearer auth
via `X-Hermes-Sidecar-Token`) plus the sidecar's process lifecycle.

Mapping (sidecar routes — see index.mjs / photon-sidecar/RUN.md):
  * send_message(addr, text)   -> POST /send           {spaceId, text, format:"markdown"}
  * send_typing(addr, state)   -> POST /typing         {spaceId, state}
  * send_rich(addr, part):
      TextPart    -> /send
      ImagePart   -> /send-attachment {kind: attachment}
      FilePart    -> /send-attachment {kind: attachment, name?}
      VoicePart   -> /send-attachment {kind: voice}
      ReactionPart-> /react {messageId: reply_to, emoji}; reply_to=None -> ok=False
      PollPart    -> degrade to a numbered text list via /send (iMessage has no poll)

Sends are BEST-EFFORT: any transport hiccup (or an unsupported part) returns
OutboundResult(ok=False) and is logged — it NEVER raises into the always-on loop.

Lifecycle (ensure_sidecar) mirrors Hermes' adapter.py: probe /healthz; if down,
reap a stale listener squatting the port, then spawn `node index.mjs` and poll
/healthz until ready. Modeled on adapter.py::_start_sidecar / _reap_stale_sidecar /
_find_listener_pids, but synchronous (the worker is a sync poll loop) and using
`requests` (the repo's existing HTTP client, see sendblue_client.py).

ponytail: one sidecar + one PhotonChannel per project (the gRPC stream already
carries every sender). The ceiling is "single in-process sidecar handle" — for a
multi-host fleet the sidecar is co-located with the reply worker (see design doc
§Deployment topology), not sharded here.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

import requests

from bubbles import split_into_bubbles
from channels.base import OutboundResult
from channels.rich import (
    FilePart,
    ImagePart,
    PollPart,
    ReactionPart,
    TextPart,
    VoicePart,
)
from channels._channel_utils import is_remote as _is_remote, poll_to_text as _poll_to_text

log = logging.getLogger("worker.channels.photon")

MAX_REPLY_CHARS = 8000  # matches the sidecar's iMessage practical cap (_MAX_MESSAGE_LENGTH)

# Default vendored sidecar entry point (lab/photon-sidecar/index.mjs).
_DEFAULT_SIDECAR_DIR = Path(__file__).resolve().parent.parent.parent / "photon-sidecar"

_TOKEN_HEADER = "X-Hermes-Sidecar-Token"

# Content-Types we treat as "no useful MIME": an HTML redirect/error page, or an
# unhelpful catch-all. For these we omit mimeType and let the sidecar's
# extension-inference stand (today's behavior).
_GENERIC_MIMES = frozenset({
    "text/html",
    "application/octet-stream",
    "binary/octet-stream",
})


def _default_poster(url: str, *, json: dict, headers: dict, timeout: float):
    """Real HTTP POST (requests). Injected so tests fake the wire (no real sidecar)."""
    return requests.post(url, json=json, headers=headers, timeout=timeout)


def _default_head(url: str, *, timeout: float):
    """Real HTTP HEAD (requests, follows redirects). Injected so tests fake it.

    Used only on the already-allowlisted http(s) media src to sniff Content-Type
    for extensionless URLs — the sidecar fetches this exact URL anyway, so HEAD
    adds no SSRF surface.
    """
    return requests.head(url, allow_redirects=True, timeout=timeout)


class PhotonChannel:
    """Outbound iMessage via the Photon sidecar. One instance serves all iMessage tenants."""

    kind = "imessage"

    def __init__(
        self,
        sidecar_base: str,
        bearer: str,
        *,
        timeout: float = 20.0,
        node_bin: Optional[str] = None,
        sidecar_dir: Optional[str] = None,
        project_id: Optional[str] = None,
        project_secret: Optional[str] = None,
        max_bubbles: int = 4,
        max_chars: int = 1200,
        max_reply_chars: int = MAX_REPLY_CHARS,
        poster: Optional[Callable] = None,
        head_fn: Optional[Callable] = None,
    ):
        self._base = (sidecar_base or "").rstrip("/")
        self._bearer = bearer or ""
        self._timeout = float(timeout)
        self._node_bin = node_bin or os.getenv("PHOTON_NODE_BIN") or "node"
        self._sidecar_dir = Path(sidecar_dir) if sidecar_dir else _DEFAULT_SIDECAR_DIR
        self._project_id = project_id or ""
        self._project_secret = project_secret or ""
        self._max_bubbles = int(max_bubbles)
        self._max_chars = int(max_chars)
        self._max_reply_chars = int(max_reply_chars)
        # Injected HTTP poster keeps the wire fakeable in tests (no real sidecar).
        self._post = poster or _default_poster
        # Injected HEAD fetcher (same testability seam as poster) — used to sniff
        # Content-Type for extensionless media URLs (see _sniff_mime).
        self._head = head_fn or _default_head
        self._proc: Optional[subprocess.Popen] = None

    # -- wire format (parity seam) ----------------------------------------

    def render(self, text: str) -> str:
        """iMessage renders markdown natively — just trim (send_message tags format=markdown)."""
        return (text or "").strip()

    def split(self, text: str) -> list:
        """Poke-style bubble split with this channel's caps (same as SendblueChannel)."""
        return split_into_bubbles(text, max_bubbles=self._max_bubbles, max_chars=self._max_chars)

    # -- loopback HTTP helper ---------------------------------------------

    def _call(self, path: str, body: dict) -> dict:
        """POST to a sidecar route; raise on transport/HTTP/sidecar-reported error.

        Callers wrap this in try/except and convert any failure to ok=False — the
        loop never sees an exception (best-effort send contract).
        """
        url = f"{self._base}{path}"
        headers = {_TOKEN_HEADER: self._bearer}
        resp = self._post(url, json=body, headers=headers, timeout=self._timeout)
        status = getattr(resp, "status_code", None)
        if status != 200:
            text = (getattr(resp, "text", "") or "")[:200]
            raise RuntimeError(f"sidecar {path} returned {status}: {text}")
        data = resp.json() or {}
        if not data.get("ok"):
            raise RuntimeError(f"sidecar {path} reported error: {data.get('error')}")
        return data

    @staticmethod
    def _provider_id(data: dict) -> Optional[str]:
        return data.get("messageId") or data.get("reactionId") or None

    def _sniff_mime(self, src: str) -> Optional[str]:
        """Best-effort: HEAD an http(s) `src` and return a concrete media MIME.

        spectrum-ts infers MIME from the URL EXTENSION, so extensionless URLs
        (CDN/signed, e.g. picsum) fail with "Unable to resolve MIME type". We
        sniff Content-Type and pass it as `mimeType` so the sidecar overrides the
        extension guess. NEVER raises: any HEAD failure/timeout or a
        missing/generic Content-Type returns None → today's behavior (no mimeType).

        ponytail: HEAD-only + a single generic blocklist (octet-stream/text-html).
        Ceiling = "trusts the origin's Content-Type"; upgrade path = sniff the
        first bytes (magic numbers) if a CDN mislabels media.
        """
        try:
            resp = self._head(src, timeout=min(self._timeout, 5.0))
        except Exception as e:  # network/timeout — fall back to extension inference
            log.debug("photon: HEAD %r failed, no mimeType: %s", src, e)
            return None
        headers = getattr(resp, "headers", None) or {}
        ctype = (headers.get("Content-Type") or headers.get("content-type") or "")
        # Strip parameters: "image/jpeg; charset=binary" -> "image/jpeg".
        mime = ctype.split(";", 1)[0].strip().lower()
        # Reject empty + useless-generic types (an HTML redirect/error page, or an
        # unhelpful catch-all) — better to let the sidecar's extension guess stand.
        if not mime or mime in _GENERIC_MIMES:
            return None
        return mime

    def _add_mime(self, body: dict, src: str, *, set_name: bool = True) -> None:
        """Mutate `body` to add a sniffed `mimeType` (and best-effort `name`).

        Best-effort & additive: if no concrete MIME can be sniffed, `body` is left
        byte-identical (today's behavior). When the URL also lacks a file extension
        AND `set_name` is True (no caller-supplied name), attach a synthetic name
        with the MIME's canonical extension so the sidecar names the file sensibly.
        """
        mime = self._sniff_mime(src)
        if not mime:
            return
        body["mimeType"] = mime
        if set_name and not _url_has_extension(src):
            ext = _ext_for_mime(mime)
            if ext:
                body["name"] = f"attachment{ext}"

    # -- plain text + typing ----------------------------------------------

    def send_message(self, address: str, text: str) -> OutboundResult:
        body = (text or "")[: self._max_reply_chars]
        if not body.strip():
            return OutboundResult(ok=False, error="empty body")
        try:
            # format=markdown: the sidecar's spectrum builder renders markdown on
            # iMessage and degrades to readable plain text on platforms that don't.
            data = self._call("/send", {"spaceId": address, "text": body, "format": "markdown"})
            return OutboundResult(ok=True, provider_id=self._provider_id(data))
        except Exception as e:  # best-effort: never raise into the loop
            log.warning("photon send failed for %s: %s", address, e)
            return OutboundResult(ok=False, error=str(e)[:200])

    def send_typing(
        self, address: str, *, state: str = "start", max_duration_ms: Optional[int] = None
    ) -> OutboundResult:
        try:
            self._call("/typing", {"spaceId": address, "state": state})
            return OutboundResult(ok=True)
        except Exception as e:  # cosmetic — never let typing break the reply
            log.debug("photon typing %s failed for %s: %s", state, address, e)
            return OutboundResult(ok=False, error=str(e)[:200])

    # -- rich parts -------------------------------------------------------

    def send_rich(self, address: str, part, *, reply_to: Optional[str] = None) -> OutboundResult:
        """Send one RichPart to `address`, best-effort (never raises).

        Image/File/Voice -> /send-attachment ; Reaction -> /react (needs reply_to) ;
        Poll -> degrade to a numbered text list via /send (iMessage has no poll).
        """
        try:
            if isinstance(part, TextPart):
                return self.send_message(address, part.text)

            if isinstance(part, (ImagePart, FilePart, VoicePart)):
                # File-exfil guard: the sidecar readFile()s a string `path` and
                # texts the bytes to the sender, so a non-remote src (e.g.
                # /Users/.../.env, ../secret) would exfiltrate arbitrary local
                # files via prompt injection. Only http(s) URLs are allowed.
                # ponytail: local generated files unsupported in v1; ceiling is
                # "remote-only media" — upgrade path = confine local srcs to a
                # realpath-canonicalized sandbox dir before allowing them.
                if not _is_remote(part.src):
                    log.warning("photon: refusing non-remote media src %r", part.src)
                    return OutboundResult(ok=False, error="non-remote media src refused")

            if isinstance(part, ImagePart):
                body = {"spaceId": address, "path": part.src, "kind": "attachment"}
                self._add_mime(body, part.src)
                data = self._call("/send-attachment", body)
            elif isinstance(part, FilePart):
                body = {"spaceId": address, "path": part.src, "kind": "attachment"}
                if part.name:
                    body["name"] = part.name
                # mimeType is additive — never drop an existing name. _add_mime
                # only fills `name` when one is absent AND the URL has no extension.
                self._add_mime(body, part.src, set_name=not part.name)
                data = self._call("/send-attachment", body)
            elif isinstance(part, VoicePart):
                body = {"spaceId": address, "path": part.src, "kind": "voice"}
                self._add_mime(body, part.src)
                data = self._call("/send-attachment", body)
            elif isinstance(part, ReactionPart):
                if not reply_to:
                    # No target message id → can't tapback; degrade (no raise).
                    log.info("photon reaction skipped for %s: no reply_to target", address)
                    return OutboundResult(ok=False, error="reaction needs reply_to target")
                data = self._call(
                    "/react",
                    {"spaceId": address, "messageId": reply_to, "emoji": part.emoji},
                )
            elif isinstance(part, PollPart):
                # iMessage has no native poll — degrade to a numbered text list.
                return self.send_message(address, _poll_to_text(part))
            else:
                log.warning("photon send_rich: unsupported part %r", type(part).__name__)
                return OutboundResult(ok=False, error=f"unsupported part {type(part).__name__}")

            return OutboundResult(ok=True, provider_id=self._provider_id(data))
        except Exception as e:  # best-effort: never raise into the loop
            log.warning(
                "photon send_rich (%s) failed for %s: %s",
                type(part).__name__, address, e,
            )
            return OutboundResult(ok=False, error=str(e)[:200])

    # -- sidecar lifecycle (spawn + /healthz + reap-stale-on-port) --------

    def _healthy(self) -> bool:
        """True if a sidecar is answering /healthz on our base with our token."""
        try:
            resp = self._post(
                f"{self._base}/healthz", json={}, headers={_TOKEN_HEADER: self._bearer},
                timeout=min(self._timeout, 3.0),
            )
            return getattr(resp, "status_code", None) == 200
        except Exception:
            return False

    def ensure_sidecar(self, *, port: Optional[int] = None, ready_timeout: float = 15.0) -> bool:
        """Make sure a sidecar is up on our base; spawn one if not.

        Returns True when /healthz is green. Best-effort lifecycle modeled on
        adapter.py: probe -> reap a STALE sidecar squatting the port -> spawn
        `node index.mjs` -> poll /healthz. Never raises; on any failure logs and
        returns False so the caller can fall back (e.g. kill-switch to Sendblue).
        """
        if self._healthy():
            return True
        if not (self._project_id and self._project_secret):
            log.warning("photon ensure_sidecar: missing project_id/secret — cannot spawn")
            return False
        port = port if port is not None else _port_from_base(self._base)
        if port is None:
            log.warning("photon ensure_sidecar: cannot derive port from base %r", self._base)
            return False
        index = self._sidecar_dir / "index.mjs"
        if not index.exists():
            log.warning("photon ensure_sidecar: sidecar not found at %s", index)
            return False
        self._reap_stale_sidecar(port)

        env = os.environ.copy()
        env["PHOTON_PROJECT_ID"] = self._project_id
        env["PHOTON_PROJECT_SECRET"] = self._project_secret
        env["PHOTON_SIDECAR_PORT"] = str(port)
        env["PHOTON_SIDECAR_TOKEN"] = self._bearer
        # Parent-death detection: the sidecar exits on stdin EOF, so it can't
        # orphan itself on the port when this supervisor dies (any way).
        env["PHOTON_SIDECAR_WATCH_STDIN"] = "1"
        try:
            self._proc = subprocess.Popen(  # noqa: S603
                [self._node_bin, str(index)],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=(sys.platform != "win32"),
            )
        except Exception as e:
            log.warning("photon ensure_sidecar: spawn failed: %s", e)
            return False

        deadline = time.time() + ready_timeout
        while time.time() < deadline:
            if self._proc.poll() is not None:
                log.warning(
                    "photon sidecar exited (code %s) before becoming ready",
                    self._proc.returncode,
                )
                return False
            if self._healthy():
                return True
            time.sleep(0.2)
        log.warning("photon sidecar did not become ready within %.0fs", ready_timeout)
        return False

    def _reap_stale_sidecar(self, port: int) -> None:
        """Kill an orphaned Photon sidecar squatting `port` before we spawn ours.

        POSIX-only (lsof/ps). Only signals listeners whose command line is a
        photon sidecar — a foreign process on the port is left alone (and the
        spawn will then fail loudly on EADDRINUSE, surfaced as not-ready).
        """
        if sys.platform == "win32":
            return
        if not self._healthy():
            return  # nothing answering → no stale sidecar to reap
        stale = [p for p in _find_listener_pids(port) if _pid_is_sidecar(p)]
        for pid in stale:
            log.warning("photon: reaping orphaned sidecar (pid %d) on port %d", pid, port)
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.time() + 3.0
        while time.time() < deadline and any(_pid_alive(p) for p in stale):
            time.sleep(0.1)
        for pid in stale:
            if _pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        if stale:
            time.sleep(0.2)  # let the OS release the listening socket


# ---------------------------------------------------------------------------
# Module helpers (also useful standalone / in tests)


def _url_has_extension(src: str) -> bool:
    """True if the URL PATH's last segment has a file extension (e.g. '/cat.png').

    Query/fragment are ignored (that's where the extension-inference fails). A
    segment like '300' or a signed-URL path without a dot → False.
    """
    if not isinstance(src, str):
        return False
    last = urlsplit(src).path.rsplit("/", 1)[-1]
    return "." in last and not last.endswith(".")


def _ext_for_mime(mime: str) -> Optional[str]:
    """Canonical file extension for a MIME type (stdlib mimetypes), or None.

    ponytail: rung-2 reuse — the stdlib maps the common media types; an unknown
    type just yields None and we skip the synthetic name (no hand-rolled table).
    """
    return mimetypes.guess_extension(mime) or None


def _port_from_base(base: str) -> Optional[int]:
    """Extract the TCP port from a sidecar base like 'http://127.0.0.1:8790'."""
    tail = (base or "").rsplit(":", 1)
    if len(tail) != 2:
        return None
    digits = "".join(c for c in tail[1] if c.isdigit())
    return int(digits) if digits else None


def _find_listener_pids(port: int) -> list:
    """PIDs listening on a local TCP port (empty if none/undeterminable)."""
    try:
        out = subprocess.run(  # noqa: S603,S607
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=5.0, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(tok) for tok in out.stdout.split() if tok.strip().isdigit()]


def _pid_is_sidecar(pid: int) -> bool:
    """True if `pid`'s command line is a Photon sidecar process."""
    try:
        out = subprocess.run(  # noqa: S603,S607
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=5.0, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "photon-sidecar/index.mjs" in out.stdout or "photon/sidecar/index.mjs" in out.stdout


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
