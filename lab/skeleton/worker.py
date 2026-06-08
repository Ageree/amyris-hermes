"""Brain-side worker for the durable Convex queue (P1C).

This REPLACES the throwaway FastAPI app.py. In the durable-queue architecture
the brain (Hermes + a real browser, running on the operator's Mac or a cloud VM)
is NOT publicly reachable. Sendblue posts inbound iMessages to the always-on
Convex HTTP endpoint (control-plane/convex/http.ts), which enqueues them
durably. This worker polls that queue and does the actual work:

    claimNext(workerSecret) -> {id, handle, userNumber, text, mediaUrl} | None
      -> run_hermes(text) -> reply        (friendly error reply on failure)
      -> sendblue.send_message(reply_target, reply)
      -> complete(id, reply)              (or fail(id, error))

Because the queue is durable, messages are never lost while the brain is offline
— they sit as "queued" and are picked up when it restarts.

Security (carried over from app.py): the reply target is ALWAYS the
config-derived operator number, never the inbound payload, and Hermes-internal
error text is never leaked back to the user.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from convex_client import ConvexClient
from hermes_bridge import run_hermes
from sendblue_client import SendblueClient

log = logging.getLogger("worker")

MAX_REPLY_CHARS = 1800
# Never leak Hermes/subprocess internals to the end user.
ERROR_REPLY = "Sorry — I hit an error processing that. Try again in a moment."


@dataclass(frozen=True)
class WorkerConfig:
    convex_url: str
    worker_secret: str
    sendblue_key_id: str
    sendblue_secret: str
    sendblue_from: str
    reply_target: str  # operator's E.164 — the ONLY number we reply to
    hermes_home: str
    hermes_dir: str
    python_bin: str
    poll_interval: float = 2.0
    hermes_timeout: float = 180.0

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        """Build from the environment. Required vars raise KeyError (fail fast)."""
        return cls(
            convex_url=os.environ["CONVEX_URL"],
            worker_secret=os.environ["WORKER_SECRET"],
            sendblue_key_id=os.environ["SENDBLUE_API_KEY_ID"],
            sendblue_secret=os.environ["SENDBLUE_API_SECRET_KEY"],
            sendblue_from=os.environ["SENDBLUE_FROM_NUMBER"],
            reply_target=os.environ["ALLOWED_USER_NUMBER"],
            hermes_home=os.path.expanduser(
                os.environ.get("HERMES_HOME", "~/.hermes-savedlab")
            ),
            hermes_dir=os.path.expanduser(
                os.environ.get("HERMES_DIR", "~/hermes-agent")
            ),
            python_bin=os.path.expanduser(
                os.environ.get("HERMES_PYTHON_BIN", "~/hermes-agent/venv/bin/python")
            ),
            poll_interval=float(os.environ.get("POLL_INTERVAL", "2.0")),
            hermes_timeout=float(os.environ.get("HERMES_TIMEOUT", "180.0")),
        )


def process_one(
    convex: Any,
    sendblue: Any,
    cfg: WorkerConfig,
    *,
    run_fn: Callable[..., str] = run_hermes,
) -> bool:
    """Claim and process at most one queued message.

    Returns True if a message was claimed and handled (so the caller should poll
    again immediately), False if the queue was empty (caller should back off).
    Never raises for a per-message failure — Hermes errors are caught, the
    message is marked failed, and the user gets a friendly reply.
    """
    claimed = convex.mutation("messages:claimNext", {"workerSecret": cfg.worker_secret})
    if not claimed:
        return False

    mid = claimed["id"]
    text = claimed["text"]
    try:
        reply = run_fn(
            text,
            hermes_home=cfg.hermes_home,
            hermes_dir=cfg.hermes_dir,
            python_bin=cfg.python_bin,
            timeout=cfg.hermes_timeout,
        )
        convex.mutation(
            "messages:complete",
            {"workerSecret": cfg.worker_secret, "id": mid, "reply": reply},
        )
    except Exception as e:  # per-message failure must not kill the loop
        log.exception("hermes failed for message %s", mid)
        reply = ERROR_REPLY
        convex.mutation(
            "messages:fail",
            {"workerSecret": cfg.worker_secret, "id": mid, "error": str(e)[:500]},
        )

    # Reply target is ALWAYS the config operator number, never the payload.
    try:
        sendblue.send_message(to_number=cfg.reply_target, content=reply[:MAX_REPLY_CHARS])
    except Exception:
        log.exception("sendblue reply failed for message %s", mid)

    return True


def run_loop(
    cfg: WorkerConfig,
    *,
    convex: Optional[Any] = None,
    sendblue: Optional[Any] = None,
    process_fn: Callable[..., bool] = process_one,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_iterations: Optional[int] = None,
) -> None:
    """Poll the durable queue forever (or `max_iterations` times for tests).

    A whole-iteration crash (e.g. Convex unreachable) is logged and treated as an
    empty poll so the worker backs off and retries instead of dying.
    """
    convex = convex or ConvexClient(cfg.convex_url)
    sendblue = sendblue or SendblueClient(
        cfg.sendblue_key_id, cfg.sendblue_secret, cfg.sendblue_from
    )
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        try:
            did = process_fn(convex, sendblue, cfg)
        except Exception:
            log.exception("worker iteration crashed")
            did = False
        if not did:
            sleep_fn(cfg.poll_interval)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    cfg = WorkerConfig.from_env()
    log.info("worker starting: polling %s every %ss", cfg.convex_url, cfg.poll_interval)
    run_loop(cfg)


if __name__ == "__main__":
    main()
