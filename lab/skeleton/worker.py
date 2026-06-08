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

# Fast lane is a SOFT dependency: a stale/partial deploy (worker.py updated but
# fast_lane.py not yet copied) must degrade to the unchanged Hermes-only path,
# NOT crash-loop the always-on daemon at import time. Mirrors the composio guard.
try:
    from fast_lane import contains_url, fast_reply
except Exception:  # pragma: no cover - exercised only on a broken deploy
    def contains_url(text: str) -> bool:  # noqa: ARG001 - stub keeps the daemon alive
        return False
    fast_reply = None

# composio_api lives in the connections skill scripts; reachable in the repo layout
# (../skills/connections/scripts) and in the deployed worker tree (same dir as this file).
import os as _os, sys as _sys
for _cand in (_os.path.dirname(_os.path.abspath(__file__)),
              _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "skills", "connections", "scripts")):
    if _os.path.isdir(_cand) and _cand not in _sys.path:
        _sys.path.insert(0, _cand)
try:
    from composio_api import ComposioClient
except Exception:  # composio optional — worker still runs the queue without it
    ComposioClient = None

log = logging.getLogger("worker")

MAX_REPLY_CHARS = 1800
# Never leak Hermes/subprocess internals to the end user.
ERROR_REPLY = "Sorry — I hit an error processing that. Try again in a moment."

DEFAULT_MINIMAX_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_MINIMAX_MODEL = "MiniMax-M3"  # pinned: only M3 honors thinking-disabled


def _env_flag(name: str, default: bool) -> bool:
    """Parse a boolean env var; absent -> default, else falsey on 0/false/no/off."""
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "")


def _load_soul() -> str:
    """Load the SOUL voice for the fast lane. Best-effort; '' if not found.

    Looked up in order: $SOUL_PATH, beside this module (deployed worker tree),
    $HERMES_HOME/SOUL.md, then the repo's lab/personality/SOUL.md.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    hh = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes-savedlab"))
    candidates = [
        os.path.expanduser(os.environ["SOUL_PATH"]) if os.environ.get("SOUL_PATH") else None,
        os.path.join(here, "SOUL.md"),
        os.path.join(hh, "SOUL.md"),
        os.path.join(here, "..", "personality", "SOUL.md"),
    ]
    for path in candidates:
        if not path:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            continue
    return ""


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
    poll_interval: float = 2.0          # ACTIVE interval (just after work / draining)
    hermes_timeout: float = 180.0
    composio_user_id: str = ""
    intent_ttl: float = 3600.0  # 1 hour
    # Adaptive polling: poll fast while active, back off to idle_poll_interval
    # after idle_after consecutive empty polls (cuts 24/7 Convex idle-poll volume
    # while keeping pickup snappy during a conversation).
    idle_poll_interval: float = 3.0
    idle_after: int = 6
    intent_interval: float = 10.0       # wall-clock seconds between Composio intent polls
    # Fast conversational lane (latency optimization). Disabled unless a MiniMax
    # key is present; flip FAST_LANE_ENABLED=0 to force everything through Hermes.
    minimax_api_key: str = ""
    minimax_base_url: str = DEFAULT_MINIMAX_BASE_URL
    minimax_model: str = DEFAULT_MINIMAX_MODEL
    soul: str = ""
    fast_lane_enabled: bool = True
    fast_probe_timeout: float = 6.0     # tight cap so a slow probe defers to Hermes fast
    # Medium lane: tool-free messages that need reasoning get a 2nd M3 call with
    # thinking ON (no tools) — faster than Hermes, better than a thinking-off answer.
    medium_lane_enabled: bool = True
    medium_timeout: float = 25.0        # thinking needs more headroom than the probe
    medium_max_tokens: int = 2048       # reasoning tokens count against this — keep generous

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
            poll_interval=float(os.environ.get("POLL_INTERVAL", "0.5")),
            hermes_timeout=float(os.environ.get("HERMES_TIMEOUT", "180.0")),
            composio_user_id=os.environ.get("COMPOSIO_USER_ID", os.environ.get("ALLOWED_USER_NUMBER", "")),
            idle_poll_interval=float(os.environ.get("IDLE_POLL_INTERVAL", "3.0")),
            idle_after=int(os.environ.get("IDLE_AFTER", "6")),
            intent_interval=float(os.environ.get("INTENT_INTERVAL", "10.0")),
            minimax_api_key=os.environ.get("MINIMAX_API_KEY", ""),
            minimax_base_url=os.environ.get("MINIMAX_BASE_URL", DEFAULT_MINIMAX_BASE_URL),
            minimax_model=os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL),
            soul=_load_soul(),
            fast_lane_enabled=_env_flag("FAST_LANE_ENABLED", True),
            fast_probe_timeout=float(os.environ.get("FAST_PROBE_TIMEOUT", "6.0")),
            medium_lane_enabled=_env_flag("MEDIUM_LANE_ENABLED", True),
            medium_timeout=float(os.environ.get("MEDIUM_TIMEOUT", "25.0")),
            medium_max_tokens=int(os.environ.get("MEDIUM_MAX_TOKENS", "2048")),
        )


def _fast_lane_model_ok(cfg: WorkerConfig) -> bool:
    """True if the configured model honors thinking-disabled (only the M3 family)."""
    return cfg.minimax_model.startswith("MiniMax-M3")


def _fast_lane_allowed(cfg: WorkerConfig, text: str, fast_fn: Optional[Callable]) -> bool:
    """Gate the fast lane: enabled, not obvious-heavy, and runnable.

    An injected fast_fn (tests) always counts; the default path additionally needs
    a key AND the fast_reply import to have succeeded (a stale deploy sets it None).
    """
    if not cfg.fast_lane_enabled:
        return False
    if contains_url(text):  # links almost always need the real tool agent
        return False
    if fast_fn is not None:
        return True
    return bool(cfg.minimax_api_key) and fast_reply is not None


def _run_fast_lane(text: str, cfg: WorkerConfig) -> Optional[str]:
    """Production fast-lane call: one direct MiniMax-M3 turn, thinking disabled.

    Uses a TIGHT timeout (cfg.fast_probe_timeout) so a slow/hanging MiniMax probe
    falls back to Hermes quickly instead of stacking up to the 20s requests default
    in front of the heavy path on a deferred message.
    """
    assert fast_reply is not None  # guaranteed by _fast_lane_allowed before we get here
    return fast_reply(
        text,
        api_key=cfg.minimax_api_key,
        soul=cfg.soul,
        base_url=cfg.minimax_base_url,
        model=cfg.minimax_model,
        timeout=cfg.fast_probe_timeout,
        medium=cfg.medium_lane_enabled,
        think_timeout=cfg.medium_timeout,
        think_max_tokens=cfg.medium_max_tokens,
    )


def process_one(
    convex: Any,
    sendblue: Any,
    cfg: WorkerConfig,
    *,
    run_fn: Callable[..., str] = run_hermes,
    fast_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> bool:
    """Claim and process at most one queued message.

    Returns True if a message was claimed and handled (so the caller should poll
    again immediately), False if the queue was empty (caller should back off).
    Never raises for a per-message failure — Hermes errors are caught, the
    message is marked failed, and the user gets a friendly reply.

    Latency: the FAST LANE is tried first (one slim MiniMax-M3 call, no tools,
    reasoning off) for messages that need no tools. On a real answer the message
    completes in ~1.5-3s without ever cold-starting Hermes. On a deferral (None)
    or ANY fast-lane error, it falls back to the unchanged Hermes path — so heavy
    work is never broken by the optimization. NOTE: a deferred message pays the
    fast-lane probe (≤ cfg.fast_probe_timeout) BEFORE the Hermes turn; the probe
    timeout is kept tight so that tail stays small.
    """
    claimed = convex.mutation("messages:claimNext", {"workerSecret": cfg.worker_secret})
    if not claimed:
        return False

    mid = claimed["id"]
    text = claimed["text"]

    # --- Fast lane (answer-or-defer) ---------------------------------------
    reply: Optional[str] = None
    completed = False
    if _fast_lane_allowed(cfg, text, fast_fn):
        try:
            reply = fast_fn(text) if fast_fn is not None else _run_fast_lane(text, cfg)
        except Exception:  # a fast-lane failure is NON-fatal: defer to Hermes
            log.exception("fast lane error for %s; deferring to hermes", mid)
            reply = None
        if reply is not None:
            # Guard the completion just like the heavy lane: a transient Convex
            # failure here must degrade to `messages:fail` (terminal state +
            # friendly reply), NOT propagate and strand the message in
            # "processing" forever (no reaper exists). Do NOT re-run Hermes after
            # a successful answer — that would double-reply.
            try:
                convex.mutation(
                    "messages:complete",
                    {"workerSecret": cfg.worker_secret, "id": mid, "reply": reply},
                )
            except Exception as e:
                log.exception("fast-lane complete failed for %s; marking failed", mid)
                reply = ERROR_REPLY
                try:
                    convex.mutation(
                        "messages:fail",
                        {"workerSecret": cfg.worker_secret, "id": mid, "error": str(e)[:500]},
                    )
                except Exception:
                    log.exception("fail mutation also failed for %s", mid)
            completed = True

    # --- Heavy lane: full Hermes (unchanged) -------------------------------
    if not completed:
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
        sendblue.send_message(to_number=cfg.reply_target, content=(reply or ERROR_REPLY)[:MAX_REPLY_CHARS])
    except Exception:
        log.exception("sendblue reply failed for message %s", mid)

    return True


def process_intents(convex: Any, cfg: WorkerConfig, *, composio: Optional[Any] = None, now: Optional[float] = None) -> None:
    """Poll Composio status for pending intents; resolve (enqueue resume) or expire.

    Never raises — a failure here must not kill the loop.
    """
    import time as _t
    now = _t.time() if now is None else now
    if composio is None:
        if ComposioClient is None or not os.environ.get("COMPOSIO_API_KEY"):
            return
        composio = ComposioClient(user_id=cfg.composio_user_id)
    try:
        intents = convex.query("intents:listPending", {"workerSecret": cfg.worker_secret}) or []
    except Exception:
        log.exception("listPending failed")
        return
    for it in intents:
        try:
            if now - float(it.get("createdAt", now)) > cfg.intent_ttl:
                convex.mutation("intents:expireIntent",
                                {"workerSecret": cfg.worker_secret, "id": it["id"]})
                continue
            uid = it.get("userNumber") or cfg.composio_user_id
            active = []
            for tk in it.get("requiredToolkits", []):
                if composio.connection_status(tk, user_id=uid) == "ACTIVE":
                    active.append(tk)
            convex.mutation("intents:resolveIntent", {
                "workerSecret": cfg.worker_secret, "id": it["id"], "connectedToolkits": active,
            })
        except Exception:
            log.exception("intent %s poll failed", it.get("id"))


def run_loop(
    cfg: WorkerConfig,
    *,
    convex: Optional[Any] = None,
    sendblue: Optional[Any] = None,
    process_fn: Callable[..., bool] = process_one,
    intent_fn: Optional[Callable[..., None]] = process_intents,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
    max_iterations: Optional[int] = None,
) -> None:
    """Poll the durable queue forever (or `max_iterations` times for tests).

    Adaptive cadence: poll at cfg.poll_interval (fast) while active, backing off to
    cfg.idle_poll_interval after cfg.idle_after consecutive empty polls — snappy
    pickup during a conversation, low idle Convex volume otherwise. Composio intent
    polling fires on a WALL-CLOCK interval (cfg.intent_interval), decoupled from
    the poll cadence so adaptive sleeps don't change how often it runs.

    A whole-iteration crash (e.g. Convex unreachable) is logged and treated as an
    empty poll so the worker backs off and retries instead of dying.
    """
    convex = convex or ConvexClient(cfg.convex_url)
    sendblue = sendblue or SendblueClient(
        cfg.sendblue_key_id, cfg.sendblue_secret, cfg.sendblue_from
    )
    i = 0
    empties = 0
    last_intent: Optional[float] = None
    while max_iterations is None or i < max_iterations:
        i += 1
        try:
            if intent_fn is not None:
                now = time_fn()
                if last_intent is None or now - last_intent >= cfg.intent_interval:
                    intent_fn(convex, cfg)
                    last_intent = now
            did = process_fn(convex, sendblue, cfg)
        except Exception:
            log.exception("worker iteration crashed")
            did = False
        if did:
            empties = 0
        else:
            empties += 1
            interval = cfg.poll_interval if empties <= cfg.idle_after else cfg.idle_poll_interval
            sleep_fn(interval)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    cfg = WorkerConfig.from_env()
    if cfg.fast_lane_enabled and cfg.minimax_api_key and not _fast_lane_model_ok(cfg):
        log.warning(
            "fast lane model %r does not honor thinking-disabled (only MiniMax-M3 "
            "does) — the fast lane will run with reasoning ON and be slow. Set "
            "MINIMAX_MODEL=MiniMax-M3 or FAST_LANE_ENABLED=0.", cfg.minimax_model,
        )
    log.info(
        "worker starting: polling %s (active %ss / idle %ss), fast_lane=%s",
        cfg.convex_url, cfg.poll_interval, cfg.idle_poll_interval,
        cfg.fast_lane_enabled and bool(cfg.minimax_api_key) and fast_reply is not None,
    )
    run_loop(cfg)


if __name__ == "__main__":
    main()
