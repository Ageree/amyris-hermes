"""Throwaway single-user webhook bridge: Sendblue inbound -> Hermes -> Sendblue reply.

Idempotency is in-memory (process-local) — fine for the Phase-1A skeleton; P1C
uses Convex for durable idempotency + multi-user identity. The endpoint NEVER
returns a 5xx to Sendblue for PROCESSING errors (Sendblue retries on 5xx) — it
absorbs every error, logs it, and replies to the user with a friendly message.
AUTH failures are the one exception: they return 401 (not 5xx) BEFORE any body
is processed.

[SECURITY] hardening (3 findings):
  1. Unauthenticated relay → (a) secret URL path token compared constant-time,
     (b) reply-target allowlist so we only ever act for / reply to the operator.
  2. Idempotency bypass → empty handle is hard-rejected; the dedup store is a
     bounded LRU (see _dedup.BoundedDedup) so it can't be flooded into OOM.
  3. Blocking subprocess → run_hermes runs via asyncio.to_thread under an
     asyncio.Semaphore concurrency cap, with an explicit timeout.
"""
from __future__ import annotations

import asyncio
import hmac
import logging

from fastapi import FastAPI, HTTPException, Request

from _dedup import BoundedDedup
from hermes_bridge import run_hermes
from sendblue_client import SendblueClient, parse_inbound

log = logging.getLogger("skeleton")

MAX_REPLY_CHARS = 1800
ERROR_REPLY = "Sorry — I hit an error processing that. Try again in a moment."
HERMES_TIMEOUT = 60  # explicit per-request cap; do NOT rely on the bridge default


def create_app(cfg) -> FastAPI:
    app = FastAPI()
    client = SendblueClient(cfg.sendblue_key_id, cfg.sendblue_secret, cfg.sendblue_from)
    seen = BoundedDedup()
    # Cap concurrent (blocking) Hermes runs. Default 1 for single-user P1A.
    sem = asyncio.Semaphore(getattr(cfg, "max_concurrency", 1))

    @app.get("/healthz")
    def healthz():
        # Unauthenticated by design (liveness probe; reveals nothing sensitive).
        return {"ok": True}

    @app.post("/sendblue/inbound/{token}")
    async def inbound(token: str, request: Request):
        # --- Finding 1a: secret path token (primary auth gate) ------------------
        # Sendblue does NOT offer HMAC request signing (only an undocumented
        # shared-secret header echoed back), and the webhook URL is fully
        # operator-controlled in the dashboard — so a high-entropy URL path token
        # is the reliable gate. Compare constant-time and reject BEFORE reading
        # the body. 401 (not 5xx) so Sendblue does not retry an auth failure.
        # FUTURE: once Sendblue's echoed secret-header name is captured live,
        # also verify that header here as defence-in-depth.
        if not hmac.compare_digest(token, cfg.webhook_secret):
            log.warning("inbound: bad webhook token")
            raise HTTPException(status_code=401)

        # Never trust external data: malformed JSON must not 500 back to Sendblue.
        try:
            payload = await request.json()
        except Exception:
            log.warning("inbound: invalid JSON body")
            return {"ignored": True}

        msg = parse_inbound(payload)
        if msg is None:
            return {"ignored": True}

        # --- Finding 1b: reply-target allowlist (server-side identity) ----------
        # Only act on inbound from the operator's own handle, and ALWAYS derive
        # the reply destination from config — never from the payload. This
        # neutralizes the relay vector even if the path token leaks.
        if msg.user_number != cfg.allowed_user_number:
            log.warning("inbound: number not on allowlist; ignoring")
            return {"ignored": True}

        # --- Finding 2: idempotency (empty handle = hard reject + bounded LRU) ---
        if not msg.handle:
            log.warning("inbound: missing/empty handle; ignoring")
            return {"ignored": True}
        if not seen.add(msg.handle):  # already processed
            return {"duplicate": True}

        # --- Finding 3: run the blocking subprocess OFF the event loop, capped --
        try:
            async with sem:
                reply = await asyncio.to_thread(
                    run_hermes,
                    msg.text,
                    hermes_home=cfg.hermes_home,
                    hermes_dir=cfg.hermes_dir,
                    python_bin=cfg.python_bin,
                    timeout=HERMES_TIMEOUT,
                )
        except Exception:  # never 500 back to Sendblue for PROCESSING errors
            log.exception("hermes failed")
            reply = ERROR_REPLY

        try:
            # Destination is ALWAYS the operator's allowlisted number, never the
            # inbound payload — see Finding 1b.
            client.send_message(
                to_number=cfg.allowed_user_number,
                content=reply[:MAX_REPLY_CHARS],
            )
        except Exception:
            log.exception("sendblue reply failed for handle=%s", msg.handle)
            return {"ok": False, "error": "reply_delivery_failed"}

        return {"ok": True}

    return app
