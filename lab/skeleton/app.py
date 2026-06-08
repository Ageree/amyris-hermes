"""Throwaway single-user webhook bridge: Sendblue inbound -> Hermes -> Sendblue reply.

Idempotency is in-memory (process-local) — fine for the Phase-1A skeleton; P1C
uses Convex for durable idempotency + multi-user identity. The endpoint NEVER
returns a 5xx to Sendblue (Sendblue retries on 5xx) — it absorbs every error,
logs it, and replies to the user with a friendly message.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request

from hermes_bridge import run_hermes
from sendblue_client import SendblueClient, parse_inbound

log = logging.getLogger("skeleton")

MAX_REPLY_CHARS = 1800
ERROR_REPLY = "Sorry — I hit an error processing that. Try again in a moment."


def create_app(cfg) -> FastAPI:
    app = FastAPI()
    client = SendblueClient(cfg.sendblue_key_id, cfg.sendblue_secret, cfg.sendblue_from)
    seen: set[str] = set()

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/sendblue/inbound")
    async def inbound(request: Request):
        # Never trust external data: malformed JSON must not 500 back to Sendblue.
        try:
            payload = await request.json()
        except Exception:
            log.warning("inbound: invalid JSON body")
            return {"ignored": True}

        msg = parse_inbound(payload)
        if msg is None:
            return {"ignored": True}
        if msg.handle and msg.handle in seen:
            return {"duplicate": True}
        if msg.handle:
            seen.add(msg.handle)

        try:
            reply = run_hermes(
                msg.text,
                hermes_home=cfg.hermes_home,
                hermes_dir=cfg.hermes_dir,
                python_bin=cfg.python_bin,
            )
        except Exception:  # never 500 back to Sendblue
            log.exception("hermes failed")
            reply = ERROR_REPLY

        try:
            client.send_message(to_number=msg.user_number, content=reply[:MAX_REPLY_CHARS])
        except Exception:
            log.exception("sendblue reply failed")

        return {"ok": True}

    return app
