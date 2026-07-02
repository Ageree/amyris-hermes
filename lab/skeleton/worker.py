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

Security (multi-tenant, M2): each reply is routed to the CLAIMED message's own
channel + address (A2), set server-side by the authenticated inbound webhook —
never a user-controllable payload field, and never a single hardcoded operator
number. Cross-tenant isolation is enforced at the claim layer (claimNextForUser
is userId-scoped) and at inbound resolution (verified channelBindings only).
Hermes-internal error text is never leaked back to the user.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import threading
import time
import weakref as _weakref
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any, Callable

import yaml

# Channel layer (HARD dependency — it IS the reply path). Routes each reply to the
# claimed message's own channel + address (multi-tenancy M2), replacing the single
# hardcoded operator number.
from channels import ChannelRegistry, SendblueChannel
from channels.rich import TextPart, parse_rich
from convex_client import ConvexClient
from hermes_bridge import run_hermes
from supermemory_client import SupermemoryClient, SupermemoryConfig

# Fast lane is a SOFT dependency: a stale/partial deploy (worker.py updated but
# fast_lane.py / bubbles.py not yet copied) must degrade to the unchanged
# Hermes-only path, NOT crash-loop the always-on daemon at import time. Mirrors
# the composio guard.
try:
    from fast_lane import (
        contains_url,
        fast_reply,
        looks_like_build_request,
        stream_fast_reply,
    )
except Exception:  # pragma: no cover - exercised only on a broken deploy

    def contains_url(text: str) -> bool:  # noqa: ARG001 - stub keeps the daemon alive
        return False

    def looks_like_build_request(text: str) -> bool:  # noqa: ARG001 - stub
        return False

    fast_reply = None
    stream_fast_reply = None

# Quota gate is a SOFT dependency too: a partial deploy must degrade to UNMETERED
# (never block a turn because the module is missing), not crash-loop the daemon.
try:
    import quota_client
except Exception:  # pragma: no cover - exercised only on a broken deploy
    quota_client = None

# Fleet client (M6) is a SOFT dependency: a stale/partial deploy must degrade
# gracefully — the always-on loop must never crash because this module is absent.
try:
    import fleet_client
except Exception:  # pragma: no cover - exercised only on a broken deploy
    fleet_client = None

# Photon inbound consumer (rich iMessage) is a SOFT dependency: the worker only
# wires it when IMESSAGE_PROVIDER=photon, and a stale/partial deploy (worker.py
# updated but photon_inbound.py not yet copied) must degrade to Sendblue rather
# than crash-loop the always-on daemon at import time.
try:
    from photon_inbound import PhotonInboundConsumer
except Exception:  # pragma: no cover - exercised only on a broken deploy
    PhotonInboundConsumer = None

# Multi-bubble splitting now lives in the Channel layer (SendblueChannel.split via
# bubbles.split_into_bubbles); the worker no longer imports it directly. The typing
# indicator is still a soft dep (stale-deploy resilience): if unavailable, the
# worker still replies, just without the "…" indicator.
try:
    from typing_indicator import TypingKeepalive
except Exception:  # pragma: no cover
    TypingKeepalive = None

# composio_api lives in the connections skill scripts; reachable in the repo
# layout (../skills/connections/scripts) and deployed worker tree.
import os as _os
import sys as _sys

for _cand in (
    _os.path.dirname(_os.path.abspath(__file__)),
    _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)),
        "..",
        "skills",
        "connections",
        "scripts",
    ),
):
    if _os.path.isdir(_cand) and _cand not in _sys.path:
        _sys.path.insert(0, _cand)
try:
    from composio_api import ComposioClient
except Exception:  # composio optional — worker still runs the queue without it
    ComposioClient = None

log = logging.getLogger("worker")

# --- Graceful shutdown (Bug H3) -------------------------------------------------
# On `docker stop` (idle-reap / relaunch) the container gets SIGTERM, then SIGKILL
# after a grace period. Without a handler the worker ignores SIGTERM and is killed
# mid-turn, losing the in-flight reply. We install a SIGTERM/SIGINT handler that
# sets this Event; run_loop finishes the CURRENT process_one, stops claiming new
# work, and exits 0. A heartbeat desired="stopped" sets the SAME flag (proactive
# drain). Everything here is FAIL-SOFT: signal handling must never crash the loop.
_STOP = threading.Event()


def request_stop() -> None:
    """Signal the worker loop to drain and exit after the current turn."""
    _STOP.set()


def clear_stop() -> None:
    """Reset the stop flag (tests / a fresh start)."""
    _STOP.clear()


def should_stop() -> bool:
    """True once a shutdown has been requested (signal or desired=stopped)."""
    return _STOP.is_set()


def _handle_stop_signal(signum, frame) -> None:  # noqa: ARG001 - signal API shape
    """SIGTERM/SIGINT handler: request a graceful drain. Never raises."""
    with suppress(Exception):
        log.info("received signal %s — beginning graceful drain", signum)
    _STOP.set()


def _install_signal_handlers() -> None:
    """Install SIGTERM + SIGINT handlers. FAIL-SOFT.

    signal.signal only works on the main thread of the main interpreter; if it
    raises (e.g. embedded / off-main-thread), we log and continue — the loop still
    honors `should_stop()` for the desired=stopped path, just not OS signals.
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle_stop_signal)
        except Exception:  # pragma: no cover - platform/threading dependent
            log.warning(
                "could not install handler for signal %s (non-fatal)",
                sig,
                exc_info=True,
            )


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
        os.path.expanduser(os.environ["SOUL_PATH"])
        if os.environ.get("SOUL_PATH")
        else None,
        os.path.join(here, "SOUL.md"),
        os.path.join(hh, "SOUL.md"),
        os.path.join(here, "..", "personality", "SOUL.md"),
    ]
    for path in candidates:
        if not path:
            continue
        try:
            with open(path, encoding="utf-8") as f:
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
    reply_target: (
        str  # operator's E.164 — LEGACY FALLBACK only (userId-less rows); see A2
    )
    hermes_home: str
    hermes_dir: str
    python_bin: str
    poll_interval: float = 2.0  # ACTIVE interval (just after work / draining)
    hermes_timeout: float = 180.0
    composio_user_id: str = ""
    # Fleet scoping: when USER_ID is set (a per-tenant container, M6), the worker
    # claims ONLY that user's rows via claimNextForUser; empty = the legacy/operator
    # global claimNext path. Server-side userId-scoping means a scoped worker can
    # never touch another tenant's rows (design §8).
    scoped_user_id: str = ""
    # Telegram channel (M3). Optional: a worker with no token serves iMessage only;
    # ChannelRegistry.from_config skips Telegram and get("telegram") then raises.
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    intent_ttl: float = 3600.0  # 1 hour
    # Adaptive polling: poll fast while active, back off to idle_poll_interval
    # after idle_after consecutive empty polls (cuts 24/7 Convex idle-poll volume
    # while keeping pickup snappy during a conversation).
    idle_poll_interval: float = 3.0
    idle_after: int = 6
    intent_interval: float = 10.0  # wall-clock seconds between Composio intent polls
    # Fast conversational lane (latency optimization). Disabled unless a MiniMax
    # key is present; flip FAST_LANE_ENABLED=0 to force everything through Hermes.
    minimax_api_key: str = ""
    minimax_base_url: str = DEFAULT_MINIMAX_BASE_URL
    minimax_model: str = DEFAULT_MINIMAX_MODEL
    soul: str = ""
    fast_lane_enabled: bool = True
    # Stage-1 probe answers directly OR emits a sentinel. Tool messages emit
    # [[DEFER]] in ~2s (short output) regardless of this cap, so it only bounds the
    # "M3 is generating a long direct answer" case. 6s was too tight: normal
    # questions with a longer answer (e.g. "почему устал?") timed out and paid a
    # full Hermes turn on top (~22s) to regenerate the SAME answer. 10s lets them
    # finish in-lane (~7-9s); genuine tool-defers are unaffected.
    fast_probe_timeout: float = 10.0
    # Medium lane: tool-free messages that need reasoning get a 2nd M3 call with
    # thinking ON (no tools) — faster than Hermes, better than a thinking-off answer.
    medium_lane_enabled: bool = True
    medium_timeout: float = 25.0  # thinking needs more headroom than the probe
    medium_max_tokens: int = 2048  # reasoning tokens count against this — keep generous
    # Conversation MEMORY: prior turns for this user, fetched from Convex and
    # spliced into the prompt so follow-up references are understood
    # in-lane instead of falling through to the slow stateless Hermes path.
    history_enabled: bool = True
    history_turns: int = 6  # how many recent done messages to recall
    history_char_cap: int = 600  # cap each stored text/reply (avoid huge tool dumps)
    # Durable Supermemory: tenant-scoped long-term memory, keyed by userId when
    # present and by phone only for legacy rows. Missing key disables it safely.
    supermemory_enabled: bool = True
    supermemory_write_enabled: bool = True
    supermemory_api_key: str = ""
    supermemory_base_url: str = "https://api.supermemory.ai"
    supermemory_search_limit: int = 8
    supermemory_timeout: float = 10.0
    # Poke-style MULTI-BUBBLE: split a reply into a few short iMessage messages
    # (blank-line paragraphs -> separate bubbles), paced bubble_delay apart so they
    # arrive in order (Sendblue drains 1 msg/s and does NOT formally guarantee
    # order). bubble_delay defaults to 0.0 in the dataclass so unit tests don't
    # sleep; from_env sets the real production pacing.
    multi_bubble_enabled: bool = True
    bubble_max_count: int = 4
    bubble_max_chars: int = 1200
    bubble_delay: float = 0.0
    # Typing indicator: show the "…" bubble while composing, re-fired on a timer
    # through long turns. iMessage-only, best-effort (never blocks the reply).
    typing_enabled: bool = True
    typing_interval: float = 6.0
    typing_max_duration_ms: int = 10000
    # STREAMING fast lane: emit each bubble the moment it's ready (and detect a
    # defer in <1s) instead of waiting for the whole answer. Requires multi-bubble.
    streaming_enabled: bool = True
    # Quota gate (M5): reserve one unit per real tenant turn BEFORE any model call;
    # over-quota -> friendly upsell, zero model spend. Synthetic (resume:/e2e) and
    # operator/legacy (userId-less) turns are unmetered. Flip QUOTA_ENABLED=0 to
    # bypass entirely. upsell_url is appended to the over-quota message when set.
    quota_enabled: bool = True
    upsell_url: str = ""
    # Fleet (M6): worker mode ("scoped" for a per-tenant container, "legacy" for the
    # original operator-global worker) and the optional instance ID assigned by the
    # controller. Neither is required for the queue to work — they are metadata.
    worker_mode: str = "legacy"
    instance_id: str = ""
    # Heartbeat (M6): the scoped worker pings fleet:heartbeat once per poll loop
    # iteration so the controller knows it is alive and can act on desired="stopped".
    # Flip HEARTBEAT_ENABLED=0 to disable without restarting (useful during tests /
    # a partial deploy where fleet_client is not yet available).
    heartbeat_enabled: bool = True
    # iMessage transport selection (Photon rich messages). IMESSAGE_PROVIDER picks
    # the iMessage channel: "sendblue" (default, the kill-switch) or "photon" (rich:
    # attachments/voice/reactions via the loopback sidecar). ChannelRegistry.from_config
    # reads these by these exact names; if "photon" is chosen but creds/base are
    # missing it falls back to Sendblue (never an empty iMessage slot). Photon creds
    # come from the env, NEVER literals.
    imessage_provider: str = "sendblue"
    photon_sidecar_base: str = "http://127.0.0.1:8790"
    photon_bearer: str = ""
    photon_sidecar_dir: str = "/Users/saveliy/Documents/Amyris/lab/photon-sidecar"
    photon_project_id: str = ""
    photon_project_secret: str = ""

    @classmethod
    def from_env(cls) -> WorkerConfig:
        """Build from the environment. Required vars raise KeyError (fail fast)."""
        return cls(
            convex_url=os.environ["CONVEX_URL"],
            worker_secret=os.environ["WORKER_SECRET"],
            sendblue_key_id=os.environ["SENDBLUE_API_KEY_ID"],
            sendblue_secret=os.environ["SENDBLUE_API_SECRET_KEY"],
            sendblue_from=os.environ["SENDBLUE_FROM_NUMBER"],
            # reply_target is the LEGACY fallback (operator/pre-migration rows only).
            # A SCOPED fleet container is per-tenant and is NEVER pinned to an
            # operator number — the controller intentionally omits ALLOWED_USER_NUMBER
            # (multi-tenant keystone). So it is OPTIONAL here: per-message routing
            # supplies the real reply address, and a tenant row with no address is
            # already failed safely in process_one. The legacy/operator worker still
            # sets it via its own .env.
            reply_target=os.environ.get("ALLOWED_USER_NUMBER", ""),
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
            composio_user_id=os.environ.get(
                "COMPOSIO_USER_ID", os.environ.get("ALLOWED_USER_NUMBER", "")
            ),
            scoped_user_id=os.environ.get("USER_ID", ""),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_webhook_secret=os.environ.get("TELEGRAM_WEBHOOK_SECRET", ""),
            idle_poll_interval=float(os.environ.get("IDLE_POLL_INTERVAL", "3.0")),
            idle_after=int(os.environ.get("IDLE_AFTER", "6")),
            intent_interval=float(os.environ.get("INTENT_INTERVAL", "10.0")),
            minimax_api_key=os.environ.get("MINIMAX_API_KEY", ""),
            minimax_base_url=os.environ.get(
                "MINIMAX_BASE_URL", DEFAULT_MINIMAX_BASE_URL
            ),
            minimax_model=os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL),
            soul=_load_soul(),
            fast_lane_enabled=_env_flag("FAST_LANE_ENABLED", True),
            fast_probe_timeout=float(os.environ.get("FAST_PROBE_TIMEOUT", "10.0")),
            medium_lane_enabled=_env_flag("MEDIUM_LANE_ENABLED", True),
            medium_timeout=float(os.environ.get("MEDIUM_TIMEOUT", "25.0")),
            medium_max_tokens=int(os.environ.get("MEDIUM_MAX_TOKENS", "2048")),
            history_enabled=_env_flag("HISTORY_ENABLED", True),
            history_turns=int(os.environ.get("HISTORY_TURNS", "6")),
            history_char_cap=int(os.environ.get("HISTORY_CHAR_CAP", "600")),
            supermemory_enabled=_env_flag("SUPERMEMORY_ENABLED", True),
            supermemory_write_enabled=_env_flag("SUPERMEMORY_WRITE_ENABLED", True),
            supermemory_api_key=os.environ.get("SUPERMEMORY_API_KEY", ""),
            supermemory_base_url=os.environ.get(
                "SUPERMEMORY_BASE_URL", "https://api.supermemory.ai"
            ),
            supermemory_search_limit=int(
                os.environ.get("SUPERMEMORY_SEARCH_LIMIT", "8")
            ),
            supermemory_timeout=float(os.environ.get("SUPERMEMORY_TIMEOUT", "10.0")),
            multi_bubble_enabled=_env_flag("MULTI_BUBBLE_ENABLED", True),
            bubble_max_count=int(os.environ.get("BUBBLE_MAX_COUNT", "4")),
            bubble_max_chars=int(os.environ.get("BUBBLE_MAX_CHARS", "1200")),
            bubble_delay=float(os.environ.get("BUBBLE_DELAY", "0.4")),
            typing_enabled=_env_flag("TYPING_ENABLED", True),
            typing_interval=float(os.environ.get("TYPING_INTERVAL", "6.0")),
            typing_max_duration_ms=int(
                os.environ.get("TYPING_MAX_DURATION_MS", "10000")
            ),
            streaming_enabled=_env_flag("STREAMING_ENABLED", True),
            quota_enabled=_env_flag("QUOTA_ENABLED", True),
            upsell_url=os.environ.get("UPGRADE_URL", ""),
            worker_mode=os.environ.get(
                "WORKER_MODE",
                "scoped" if os.environ.get("USER_ID") else "legacy",
            ),
            instance_id=os.environ.get("INSTANCE_ID", ""),
            heartbeat_enabled=_env_flag("HEARTBEAT_ENABLED", True),
            # iMessage transport (Photon rich messages). Creds from the env only.
            imessage_provider=os.environ.get("IMESSAGE_PROVIDER", "sendblue"),
            photon_sidecar_base=os.environ.get(
                "PHOTON_SIDECAR_BASE", "http://127.0.0.1:8790"
            ),
            photon_bearer=os.environ.get("PHOTON_SIDECAR_BEARER", ""),
            photon_sidecar_dir=os.environ.get(
                "PHOTON_SIDECAR_DIR",
                "/Users/saveliy/Documents/Amyris/lab/photon-sidecar",
            ),
            photon_project_id=os.environ.get("PHOTON_PROJECT_ID", ""),
            photon_project_secret=os.environ.get("PHOTON_PROJECT_SECRET", ""),
        )


def _fast_lane_model_ok(cfg: WorkerConfig) -> bool:
    """True if the configured model is the M3 family (the only one that honors
    reasoning-off, so the fast lane stays fast).

    Accepts BOTH the native MiniMax id ("MiniMax-M3") and the OpenRouter slug
    ("minimax/minimax-m3") — the assistant runs M3 via either provider. The match
    is on the normalized "minimax-m3" stem so an M2.x model (which silently keeps
    reasoning on) is still rejected under either naming.
    """
    # Drop any provider prefix ("minimax/…") to compare the bare model name.
    stem = cfg.minimax_model.lower().rsplit("/", 1)[-1]
    return stem.startswith("minimax-m3")


def _fast_lane_allowed(cfg: WorkerConfig, text: str, fast_fn: Callable | None) -> bool:
    """Gate the fast lane: enabled, not obvious-heavy, and runnable.

    An injected fast_fn (tests) always counts; the default path additionally needs
    a key AND the fast_reply import to have succeeded (a stale deploy sets it None).
    """
    if not cfg.fast_lane_enabled:
        return False
    if contains_url(text):  # links almost always need the real tool agent
        return False
    if looks_like_build_request(
        text
    ):  # "make me a site/app" needs create-site skill + terminal
        return False
    if fast_fn is not None:
        return True
    return bool(cfg.minimax_api_key) and fast_reply is not None


def _fetch_history(
    convex: Any, cfg: WorkerConfig, user_number: str, user_id: str | None = None
) -> list:
    """Recent (text, reply) turns for this user, as OpenAI {role, content} dicts.

    Scopes by the STABLE tenant key (userId, A1) when the claimed row carries one
    — so no tenant's transcript can bleed into another's prompt — and falls back to
    the source address (userNumber) for legacy/operator rows that predate userId.
    Chronological (oldest first) so they read as a real transcript. Best-effort:
    any Convex error -> [] (memory is an enhancement, never a hard dependency).
    Skips turns missing text or reply and caps each string so an old huge tool
    dump can't blow up the prompt.
    """
    if not cfg.history_enabled or not (user_id or user_number):
        return []
    args: dict = {"workerSecret": cfg.worker_secret, "limit": cfg.history_turns}
    if user_id:
        args["userId"] = user_id
    else:
        args["userNumber"] = user_number
    try:
        rows = convex.query("messages:recentForUser", args) or []
    except Exception:
        log.exception("history fetch failed for %s", user_id or user_number)
        return []
    cap = cfg.history_char_cap
    msgs: list = []
    for r in rows:
        text = (r.get("text") or "").strip()
        reply = (r.get("reply") or "").strip()
        if not text or not reply:
            continue
        msgs.append({"role": "user", "content": text[:cap]})
        msgs.append({"role": "assistant", "content": reply[:cap]})
    return msgs


_REMEMBER_RE = re.compile(r"\[\[remember:([^\]\n]+?)\]\]", re.IGNORECASE)


def _memory_user_key(user_id: str | None, user_number: str) -> str:
    """Stable tenant key for external memory."""
    return (user_id or user_number or "").strip()


def _supermemory_cfg(cfg: WorkerConfig) -> SupermemoryConfig:
    return SupermemoryConfig(
        api_key=cfg.supermemory_api_key,
        base_url=cfg.supermemory_base_url,
        enabled=cfg.supermemory_enabled,
        write_enabled=cfg.supermemory_write_enabled,
        search_limit=cfg.supermemory_search_limit,
        timeout=cfg.supermemory_timeout,
    )


def _fetch_supermemory(cfg: WorkerConfig, user_key: str, query: str) -> list:
    """Return one OpenAI-style system message with tenant-scoped Supermemory facts."""
    sm_cfg = _supermemory_cfg(cfg)
    client = SupermemoryClient.from_config(sm_cfg)
    if client is None or not user_key:
        return []
    try:
        facts = client.recall(user_key, query, limit=sm_cfg.search_limit)
    except Exception:
        log.exception("supermemory recall failed for %s", user_key)
        return []
    if not facts:
        return []
    content = "Durable user memory from Supermemory:\n" + "\n".join(
        f"- {f}" for f in facts
    )
    return [{"role": "system", "content": content[:4000]}]


def _extract_memory_markers(reply: str) -> list[str]:
    return [m.strip() for m in _REMEMBER_RE.findall(reply or "") if m.strip()]


def _remember_supermemory_turn(
    cfg: WorkerConfig,
    user_key: str,
    text: str,
    reply: str | None,
) -> None:
    """Best-effort durable memory write for one delivered turn."""
    if not (user_key and reply):
        return
    sm_cfg = _supermemory_cfg(cfg)
    if not sm_cfg.write_enabled:
        return
    client = SupermemoryClient.from_config(sm_cfg)
    if client is None:
        return
    try:
        for fact in _extract_memory_markers(reply):
            client.remember_text(user_key, fact, kind="explicit_fact")
        transcript = f"User: {text.strip()}\nAssistant: {reply.strip()}"
        client.remember_text(user_key, transcript, kind="conversation_turn")
    except Exception:
        log.exception("supermemory write failed for %s", user_key)


def _run_fast_lane(
    text: str, cfg: WorkerConfig, history: list | None = None
) -> str | None:
    """Production fast-lane call: one direct MiniMax-M3 turn, thinking disabled.

    Uses a TIGHT timeout (cfg.fast_probe_timeout) so a slow/hanging MiniMax probe
    falls back to Hermes quickly instead of stacking up to the 20s requests default
    in front of the heavy path on a deferred message. `history` is prior turns for
    conversational memory.
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
        history=history,
    )


def _run_stream_fast_lane(
    text: str,
    cfg: WorkerConfig,
    history: list | None,
    on_bubble: Callable[[str], None],
):
    """Production STREAMING fast-lane call -> StreamResult.

    Emits Poke-style bubbles via `on_bubble` as they are generated and resolves a
    defer/think verdict from the first tokens. Same model/timeout/medium params as
    the non-streaming `_run_fast_lane`, plus the bubble caps.
    """
    assert stream_fast_reply is not None  # guaranteed by the caller's gate
    return stream_fast_reply(
        text,
        on_bubble=on_bubble,
        api_key=cfg.minimax_api_key,
        soul=cfg.soul,
        base_url=cfg.minimax_base_url,
        model=cfg.minimax_model,
        timeout=cfg.fast_probe_timeout,
        medium=cfg.medium_lane_enabled,
        think_timeout=cfg.medium_timeout,
        think_max_tokens=cfg.medium_max_tokens,
        history=history,
        max_chars=cfg.bubble_max_chars,
        max_bubbles=cfg.bubble_max_count,
    )


class _NullTyping:
    """No-op typing handle (typing disabled / module unavailable / no target)."""

    def poke(self) -> None:  # pragma: no cover - trivial
        pass

    def stop(self) -> None:  # pragma: no cover - trivial
        pass


_NULL_TYPING = _NullTyping()

# Channels whose sidecar we've already ensured this process, so ensure_sidecar runs
# at most once per channel instance (its own /healthz probe is idempotent, but a
# WeakSet skips even that on the hot path). ponytail: a process-global set, fine for
# the singleton sidecar topology (one PhotonChannel per project); the ceiling is
# "multiple distinct PhotonChannel instances" — each is ensured once independently.
_SIDECAR_READY: _weakref.WeakSet = _weakref.WeakSet()


def _ensure_photon_sidecar(channel: Any) -> None:
    """Lazily start the Photon sidecar for an active PhotonChannel, once.

    No-op for any channel without ensure_sidecar (Sendblue/Telegram/test fakes).
    Best-effort: ensure_sidecar already swallows its own errors and returns a bool;
    we never let a sidecar-startup hiccup raise into the reply path (a failed start
    surfaces as a send failure, logged + best-effort, exactly like any provider
    outage). Idempotent: subsequent calls for the same channel return immediately.
    """
    ensure = getattr(channel, "ensure_sidecar", None)
    if ensure is None or channel in _SIDECAR_READY:
        return
    try:
        if ensure():
            _SIDECAR_READY.add(channel)
    except Exception:  # pragma: no cover - ensure_sidecar is already fail-soft
        log.warning(
            "photon ensure_sidecar raised (will retry next turn)", exc_info=True
        )


def _make_typing(channel: Any, cfg: WorkerConfig, target: str):
    """Build + start a TypingKeepalive over a Channel, or a no-op when disabled.

    TypingKeepalive fires channel.send_typing(target, state=, max_duration_ms=) —
    the Channel Protocol shape — so it works for any provider (iMessage re-fires +
    explicit stop; Telegram's "start" sends a chat action and "stop" is a no-op).
    """
    if not (cfg.typing_enabled and TypingKeepalive is not None and target):
        return _NULL_TYPING
    try:
        return TypingKeepalive(
            channel,
            target,
            interval=cfg.typing_interval,
            max_duration_ms=cfg.typing_max_duration_ms,
            enabled=True,
        ).start()
    except Exception:  # pragma: no cover - typing must never break the reply
        log.debug("typing keepalive failed to start for %s", target, exc_info=True)
        return _NULL_TYPING


class _BubbleEmitter:
    """Send a reply through a Channel to ONE address (the claimed message's own).

    `stream_sink(bubble)` is the streaming fast lane's on_bubble sink: render + send
    a single already-split bubble NOW, with NO pacing (paragraphs are naturally
    spaced by generation, and a sleep here would block the read loop). `send_text(text)`
    renders then splits into the channel's chunks (Poke bubbles for iMessage, a
    tag-safe split for Telegram) and sends each paced cfg.bubble_delay apart (Hermes /
    non-streaming paths, where output is produced all at once). Sends are BEST-EFFORT
    — the Channel swallows provider errors into OutboundResult(ok=False), logged here,
    never raised, so they can't kill the loop. Order is safe in both paths: sends are
    sequential + blocking, so the provider receives chunks in order regardless of the
    gap. The typing indicator is re-poked after each send so the next chunk shows "…".
    """

    def __init__(
        self,
        channel: Any,
        target: str,
        cfg: WorkerConfig,
        *,
        typing: Any = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self._channel = channel
        self._target = target
        self._cfg = cfg
        self._typing = typing
        self._sleep = sleep_fn
        self.count = 0
        self.first_at: float | None = (
            None  # monotonic of the first successful send (TTFB)
        )

    def _send(self, chunk: str, *, pace: bool) -> None:
        text = (chunk or "").strip()
        if not text:
            return
        # Pacing is ONLY for the batch path (chunks produced all at once) — a small
        # human gap. The STREAMING path must NOT pace: paragraphs are naturally
        # spaced by generation, and a sleep here would BLOCK the read loop and delay
        # the next bubble. Order is safe either way: sends are sequential + blocking,
        # so the provider receives them in order regardless of the gap.
        if pace and self.count > 0 and self._cfg.bubble_delay > 0:
            try:
                self._sleep(self._cfg.bubble_delay)
            except Exception:
                log.debug(
                    "bubble delay sleep interrupted for %s", self._target, exc_info=True
                )
        try:
            res = self._channel.send_message(self._target, text)
            if getattr(res, "ok", True) and self.first_at is None:
                self.first_at = time.monotonic()
        except (
            Exception
        ):  # defensive: a Channel impl should swallow, but never trust it
            log.exception(
                "channel reply failed (chunk %d) for %s", self.count, self._target
            )
        self.count += 1
        if self._typing is not None:
            self._typing.poke()

    def _render(self, text: str) -> str:
        """channel.render, but a formatting bug can NEVER raise into the loop
        (A3): on failure, fall back to the raw stripped text."""
        try:
            return self._channel.render(text)
        except Exception:
            log.exception("channel render failed for %s; sending raw", self._target)
            return (text or "").strip()

    def _split(self, rendered: str) -> list:
        """channel.split, fail-safe to a single chunk (never raises)."""
        try:
            return self._channel.split(rendered)
        except Exception:
            log.exception("channel split failed for %s; single chunk", self._target)
            return [rendered.strip()] if rendered.strip() else []

    def stream_sink(self, bubble: str) -> None:
        """on_bubble sink for the streaming fast lane — render + send now, no pacing."""
        # SP3: rich directives are intentionally NOT parsed on the streamed path —
        # only the non-streaming (_complete_then_send -> send_reply) and Hermes lanes
        # run parse_rich. The fast lane's SOUL note (P5) must avoid emitting rich
        # directives in streamed fast replies, since they'd be sent verbatim here.
        self._send(self._render(bubble), pace=False)

    def send_text(self, text: str) -> int:
        body = text if (text or "").strip() else ERROR_REPLY
        rendered = self._render(body)
        if self._cfg.multi_bubble_enabled:
            chunks = self._split(rendered)
            if chunks and str(chunks[-1]).endswith("…"):
                log.warning(
                    "reply for %s exceeded chunk budget; tail truncated", self._target
                )
        else:
            chunks = [rendered.strip()]
        for c in chunks or [rendered.strip()]:
            self._send(c, pace=True)
        return self.count

    def send_reply(self, reply: str, *, reply_to: str | None = None) -> int:
        """Send a brain reply, applying the rich-message contract (channels/rich.py).

        Parse the flat reply into ordered parts. The common case — a reply with no
        rich directives — parses to a single TextPart, so it takes the EXACT
        send_text() path (byte-identical to the pre-rich behavior; every existing
        text test stays green and fast-lane/Hermes plain replies are unchanged).

        For a reply with directives, each part is delivered in order: a TextPart
        goes through the same render -> split -> send_message path, any other kind
        (image/file/voice/reaction/poll) is delegated to channel.send_rich, which
        each channel handles or degrades gracefully. Every send is BEST-EFFORT — a
        failed part is logged and the loop continues; rich delivery NEVER raises and
        NEVER breaks the reply.

        `reply_to` is the user's most-recent inbound provider message id (for
        Reaction parts and anything that anchors to a message); None when unknown.
        """
        parts = parse_rich(reply)
        # Fast path: no rich directives (or empty) -> identical to send_text.
        if len(parts) <= 1 and (not parts or isinstance(parts[0], TextPart)):
            return self.send_text(parts[0].text if parts else reply)
        for part in parts:
            if isinstance(part, TextPart):
                self.send_text(part.text)
                continue
            try:
                res = self._channel.send_rich(self._target, part, reply_to=reply_to)
                if not getattr(res, "ok", True):
                    log.info(
                        "rich part %s not delivered to %s: %s",
                        type(part).__name__,
                        self._target,
                        getattr(res, "error", None),
                    )
                elif self.first_at is None:
                    self.first_at = time.monotonic()
            except Exception:  # a Channel impl should swallow; never trust it
                log.exception(
                    "channel send_rich failed (%s) for %s",
                    type(part).__name__,
                    self._target,
                )
            self.count += 1
            if self._typing is not None:
                self._typing.poke()
        return self.count


def _use_streaming(cfg: WorkerConfig, channel_kind: str = "imessage") -> bool:
    """Production streaming requires the flag, multi-bubble, an available module, and
    an iMessage channel. Telegram uses ONE batch-rendered message (its ~1/s per-chat
    limit makes Poke-style multi-bubble streaming counterproductive)."""
    return (
        cfg.streaming_enabled
        and cfg.multi_bubble_enabled
        and stream_fast_reply is not None
        and channel_kind == "imessage"
    )


def _safe_fast_reply(
    text: str, cfg: WorkerConfig, history: list | None, mid: str
) -> str | None:
    """Non-streaming fast lane, swallowing errors to a defer (None)."""
    try:
        return _run_fast_lane(text, cfg, history)
    except Exception:  # a fast-lane failure is NON-fatal: defer to Hermes
        log.exception("fast lane error for %s; deferring to hermes", mid)
        return None


TG_HANDLE_WITH_MESSAGE_PARTS = 3


def _provider_msg_id(handle: str) -> str | None:
    """Recover the inbound provider message id for reaction targeting.

    The Photon inbound consumer encodes it in the claim handle as
    "photon:<providerMessageId>" (no schema field needed — see convex
    messages.ts::enqueuePhotonInbound). Telegram encodes it as
    "tg:<update_id>:<message_id>" (http.ts Telegram inbound) — the message_id is
    the reaction target (setMessageReaction). A BARE (un-prefixed) handle is a
    Sendblue message_handle (Apple GUID) and IS the reaction target for
    /send-reaction, so it flows through as-is. A legacy "tg:<update_id>" with no
    message id, or an empty handle, has no targetable id -> None (reaction degrades).
    """
    h = handle or ""
    if h.startswith("photon:"):
        pid = h[len("photon:") :].strip()
        return pid or None
    if h.startswith("tg:"):
        parts = h.split(":")
        return (
            parts[2]
            if len(parts) >= TG_HANDLE_WITH_MESSAGE_PARTS and parts[2]
            else None
        )
    return h or None  # bare handle = Sendblue Apple GUID (tapback target)


def _complete_then_send(
    convex: Any,
    cfg: WorkerConfig,
    mid: str,
    reply: str,
    emitter: _BubbleEmitter,
    *,
    reply_to: str | None = None,
) -> bool:
    """Non-streaming completion guard: complete in Convex, THEN send the reply.

    A transient Convex `complete` failure degrades to `messages:fail` (terminal
    state, no stranded "processing" row) + a friendly ERROR reply — exactly the
    pre-streaming semantics. The reply is sent rich-aware (send_reply): a plain-text
    reply is byte-identical to the old send_text path; rich parts route per channel.
    Returns True (the message is handled).
    """
    try:
        convex.mutation(
            "messages:complete",
            {"workerSecret": cfg.worker_secret, "id": mid, "reply": reply},
        )
    except Exception as e:
        log.exception("fast-lane complete failed for %s; marking failed", mid)
        try:
            convex.mutation(
                "messages:fail",
                {"workerSecret": cfg.worker_secret, "id": mid, "error": str(e)[:500]},
            )
        except Exception:
            log.exception("fail mutation also failed for %s", mid)
        emitter.send_text(ERROR_REPLY)
        return True
    emitter.send_reply(reply, reply_to=reply_to)
    return True


def _complete_after_send(convex: Any, cfg: WorkerConfig, mid: str, reply: str) -> None:
    """Streaming completion: bubbles ALREADY sent, so just record the outcome.

    On a Convex `complete` failure the user already has the answer — we must NOT
    send a second ERROR reply; we only mark `fail` so the row isn't stuck in
    "processing" (no reaper exists).
    """
    try:
        convex.mutation(
            "messages:complete",
            {"workerSecret": cfg.worker_secret, "id": mid, "reply": reply},
        )
    except Exception as e:
        log.exception(
            "streaming complete failed for %s (reply already sent); marking failed", mid
        )
        try:
            convex.mutation(
                "messages:fail",
                {"workerSecret": cfg.worker_secret, "id": mid, "error": str(e)[:500]},
            )
        except Exception:
            log.exception("fail mutation also failed for %s", mid)


def _as_registry(channels_or_client: Any, cfg: WorkerConfig) -> ChannelRegistry:
    """Accept a ChannelRegistry OR a single raw client (back-compat).

    The fleet/run_loop passes a ChannelRegistry. Older callers (and the 200+ unit
    tests) pass a single Sendblue-like client positionally — wrap it as the sole
    "imessage" channel so the routing code path is identical and the underlying
    client receives the SAME send_message(to_number=, content=) / send_typing(state=)
    calls it always has.
    """
    if isinstance(channels_or_client, ChannelRegistry):
        return channels_or_client
    return ChannelRegistry(
        {
            "imessage": SendblueChannel(
                channels_or_client,
                max_bubbles=cfg.bubble_max_count,
                max_chars=cfg.bubble_max_chars,
            )
        }
    )


def _maybe_heartbeat(convex: Any, cfg: WorkerConfig) -> str | None:
    """Send a fleet heartbeat if enabled and in scoped mode. FAIL-SOFT.

    Returns the desired-state string from fleet:heartbeat ("running" | "stopped"
    | None) or None when disabled/legacy/error. Never raises — the always-on
    worker loop must never be interrupted by a control-plane hiccup.

    The caller (run_loop) should log a warning when desired="stopped" is returned
    so an operator can see it, but MUST NOT hard-exit mid-loop: graceful drain
    of any in-flight message is safer than an abrupt stop.
    """
    if not cfg.heartbeat_enabled:
        return None
    if not cfg.scoped_user_id:
        return None
    if fleet_client is None:
        log.debug(
            "fleet_client unavailable; skipping heartbeat for %s", cfg.scoped_user_id
        )
        return None
    return fleet_client.heartbeat(convex, cfg.worker_secret, cfg.scoped_user_id)


def process_one(  # noqa: C901, PLR0912, PLR0915
    convex: Any,
    channels: Any,
    cfg: WorkerConfig,
    *,
    run_fn: Callable[..., str] = run_hermes,
    fast_fn: Callable[[str], str | None] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Claim and process at most one queued message.

    `channels` is a ChannelRegistry (fleet) OR a single client (back-compat, wrapped
    as iMessage). Returns True if a message was claimed and handled (so the caller
    should poll again immediately), False if the queue was empty (caller should back
    off). Never raises for a per-message failure — errors are caught, the message is
    marked failed, and the user gets a friendly reply.

    Pipeline (latency-optimized):
      1. Claim (scoped to USER_ID when set, else global) -> route by the claimed
         message's OWN channel + address -> start the TYPING indicator immediately.
      2. FAST LANE first (no tools, reasoning off). In production this STREAMS on
         iMessage: bubbles are sent as each paragraph completes, and a defer verdict
         is detected from the first tokens (<1s). On a real answer the message
         completes without cold-starting Hermes; on a deferral / error it falls back.
      3. Heavy lane (Hermes) reply is rendered + split for the channel and sent.
      4. Stop the typing indicator. Each reply goes to the CLAIMED message's own
         address (A2: per-message routing), never a global config constant.
    """
    registry = _as_registry(channels, cfg)
    # Claim-path selection. Three modes, all routing-identical because the claimed
    # row carries its OWN channel + replyTarget + userId:
    #   shared  -> claimNextAny      (ONE worker drains EVERY tenant; launch bridge)
    #   scoped  -> claimNextForUser  (a per-tenant container, USER_ID pinned; fleet)
    #   legacy  -> claimNext         (operator/un-backfilled userId-less rows)
    # "shared" is checked first so it overrides the scoped/legacy default even if a
    # stray USER_ID is present; it is enabled only by an explicit WORKER_MODE=shared.
    if cfg.worker_mode == "shared":
        claimed = convex.mutation(
            "messages:claimNextAny", {"workerSecret": cfg.worker_secret}
        )
    elif cfg.scoped_user_id:
        claimed = convex.mutation(
            "messages:claimNextForUser",
            {"workerSecret": cfg.worker_secret, "userId": cfg.scoped_user_id},
        )
    else:
        claimed = convex.mutation(
            "messages:claimNext", {"workerSecret": cfg.worker_secret}
        )
    if not claimed:
        return False

    mid = claimed["id"]
    text = claimed["text"]
    user_number = claimed.get("userNumber") or ""
    user_id = claimed.get("userId")
    user_key = _memory_user_key(user_id, user_number)
    channel_kind = claimed.get("channel") or "imessage"
    # A2: route by the claimed row's OWN address. cfg.reply_target is the legacy
    # fallback ONLY for userId-less (operator/pre-migration) rows. A TENANT row
    # (userId set) with no address is a data bug — replying to cfg.reply_target
    # would leak one tenant's answer to the operator, so we mark it failed instead.
    reply_target = claimed.get("replyTarget") or user_number
    if not reply_target:
        if user_id:
            log.error(
                "tenant row %s (user %s) has no reply address; marking failed",
                mid,
                user_id,
            )
            try:
                convex.mutation(
                    "messages:fail",
                    {
                        "workerSecret": cfg.worker_secret,
                        "id": mid,
                        "error": "tenant row missing reply address",
                    },
                )
            except Exception:
                log.exception("fail mutation also failed for %s", mid)
            return True
        reply_target = (
            cfg.reply_target
        )  # legacy fallback: operator/pre-migration rows only
    started = time.monotonic()
    lane = "hermes"  # updated to "fastlane" if the fast lane answers
    history: list = []
    # Reaction targeting: the user's most-recent inbound provider message id. The
    # Photon inbound consumer carries it in the claim handle ("photon:<id>"); other
    # channels have no targetable id here, so reactions degrade gracefully (None).
    reply_to = _provider_msg_id(claimed.get("handle") or "")

    try:
        channel = registry.get(channel_kind)
    except KeyError:
        # This worker has no channel for the claimed kind (e.g. a Telegram row on an
        # iMessage-only worker). Don't strand the row or crash the loop — mark it
        # failed with a clear error. In the fleet this shouldn't happen (tenant rows
        # are claimed by their own scoped, correctly-provisioned worker).
        log.error("no channel for kind %r (msg %s); marking failed", channel_kind, mid)
        try:
            convex.mutation(
                "messages:fail",
                {
                    "workerSecret": cfg.worker_secret,
                    "id": mid,
                    "error": f"unconfigured channel {channel_kind}",
                },
            )
        except Exception:
            log.exception("fail mutation also failed for %s", mid)
        return True

    # Photon: ensure the loopback sidecar is up before the first send (lazy, once).
    # No-op for Sendblue/Telegram/test fakes. The sidecar IS the reply transport for
    # Photon, so this is on the reply path by necessity (not cosmetic); it is gated
    # by _healthy() so a warm sidecar costs one /healthz probe at most once.
    _ensure_photon_sidecar(channel)

    # --- Quota gate (M5, design §6) -------------------------------------------
    # A real tenant turn is METERED: reserve one unit BEFORE any model call.
    # Synthetic (resume:/e2e) and operator/legacy (userId-less) turns are NOT
    # metered. A clean over-quota/canceled verdict => friendly upsell + complete +
    # NO lane (zero model spend). A Convex error => FAIL OPEN (proceed unmetered).
    handle = claimed.get("handle") or ""
    metered = bool(
        cfg.quota_enabled
        and quota_client is not None
        and user_id
        and not quota_client.is_synthetic(handle)
    )
    reserved = False
    if metered:
        verdict = quota_client.check_and_reserve(convex, cfg.worker_secret, user_id)
        if not verdict.get("allowed", True):
            msg = quota_client.upsell_text(verdict.get("tier"), cfg.upsell_url)
            try:
                convex.mutation(
                    "messages:complete",
                    {"workerSecret": cfg.worker_secret, "id": mid, "reply": msg},
                )
            except Exception:
                log.exception("complete (upsell) failed for %s", mid)
            _BubbleEmitter(channel, reply_target, cfg).send_text(msg)
            log.info(
                "processed %s lane=quota-denied reason=%s", mid, verdict.get("reason")
            )
            return True
        # A fail-open verdict reserved NOTHING -> don't record usage or release later.
        reserved = not verdict.get("fail_open", False)

    typing = _make_typing(channel, cfg, reply_target)
    emitter = _BubbleEmitter(
        channel, reply_target, cfg, typing=typing, sleep_fn=sleep_fn
    )
    t_hist = started  # stamp set after history fetch (stage timing)
    hard_failed = False  # set on a hermes hard failure -> refund the reserved unit
    try:
        # Conversation memory: prior turns for this user (best-effort, [] on error).
        # Scoped by userId when present (A1) so no tenant's transcript bleeds across.
        history = _fetch_history(convex, cfg, user_number, user_id=user_id)
        history = _fetch_supermemory(cfg, user_key, text) + history
        t_hist = time.monotonic()

        reply: str | None = None
        completed = False

        if _fast_lane_allowed(cfg, text, fast_fn):
            if fast_fn is not None:
                # Injected (tests / explicit non-stream): answer-or-defer, then
                # complete-THEN-send (preserves the original guard semantics).
                try:
                    full = fast_fn(text)
                except Exception:
                    log.exception("fast lane error for %s; deferring to hermes", mid)
                    full = None
                if full is not None:
                    reply, lane = full, "fastlane"
                    completed = _complete_then_send(
                        convex, cfg, mid, full, emitter, reply_to=reply_to
                    )
            elif _use_streaming(cfg, channel_kind):
                # Production streaming: bubbles are sent AS generated; complete
                # AFTER (the user already has the answer).
                try:
                    res = _run_stream_fast_lane(text, cfg, history, emitter.stream_sink)
                except Exception:
                    log.exception("streaming fast lane crashed for %s; deferring", mid)
                    res = None
                if res is not None and res.emitted > 0:
                    reply, lane, completed = res.reply, "fastlane", True
                    _complete_after_send(convex, cfg, mid, reply or "")
                elif res is not None and res.errored and emitter.count == 0:
                    # transport error, nothing sent yet: cheap non-stream retry.
                    full = _safe_fast_reply(text, cfg, history, mid)
                    if full is not None:
                        reply, lane = full, "fastlane"
                        completed = _complete_then_send(
                            convex, cfg, mid, full, emitter, reply_to=reply_to
                        )
                # else: deferred -> Hermes
            else:
                # streaming disabled/unavailable: non-streaming fast lane + batch send.
                full = _safe_fast_reply(text, cfg, history, mid)
                if full is not None:
                    reply, lane = full, "fastlane"
                    completed = _complete_then_send(
                        convex, cfg, mid, full, emitter, reply_to=reply_to
                    )

        if not completed:
            # --- Heavy lane: full Hermes ---------------------------------------
            try:
                # SECURITY: re-pin the operator's LLM provider before every Hermes
                # turn so a prompt-injected agent can't persist a rogue base_url
                # in config.yaml (the only chat-writable model surface).
                _enforce_model_block(cfg.hermes_home)
                reply = run_fn(
                    text,
                    hermes_home=cfg.hermes_home,
                    hermes_dir=cfg.hermes_dir,
                    python_bin=cfg.python_bin,
                    timeout=cfg.hermes_timeout,
                    history=history,
                )
                convex.mutation(
                    "messages:complete",
                    {"workerSecret": cfg.worker_secret, "id": mid, "reply": reply},
                )
                emitter.send_reply(reply or ERROR_REPLY, reply_to=reply_to)
            except Exception as e:  # per-message failure must not kill the loop
                log.exception("hermes failed for message %s", mid)
                reply = ERROR_REPLY
                hard_failed = True  # undelivered turn -> refund the reserved unit
                convex.mutation(
                    "messages:fail",
                    {
                        "workerSecret": cfg.worker_secret,
                        "id": mid,
                        "error": str(e)[:500],
                    },
                )
                emitter.send_text(ERROR_REPLY)
    finally:
        typing.stop()

    # Meter the turn (M5): record one usage unit on success, or refund the reserved
    # unit on a hard (undelivered) failure. Best-effort — never affects the reply.
    if metered and reserved:
        if hard_failed:
            quota_client.release_reserve(convex, cfg.worker_secret, user_id)
        else:
            quota_client.record_usage(
                convex,
                cfg.worker_secret,
                user_id,
                message_id=mid,
                lane=lane,
                channel=channel_kind,
            )

    if not hard_failed:
        _remember_supermemory_turn(cfg, user_key, text, reply)

    # Observability: lane, bubble count, history depth, end-to-end latency, and the
    # stage breakdown — ttfb (claim -> FIRST bubble on the wire = perceived latency),
    # hist (history-fetch cost). ttfb is the number that matters for "feels fast".
    now = time.monotonic()
    ttfb = (emitter.first_at - started) if emitter.first_at is not None else None
    log.info(
        "processed %s lane=%s bubbles=%d history=%d in_chars=%d hist=%.2fs "
        "ttfb=%s dt=%.2fs",
        mid,
        lane,
        emitter.count,
        len(history),
        len(text or ""),
        t_hist - started,
        (f"{ttfb:.2f}s") if ttfb is not None else "n/a",
        now - started,
    )
    return True


def process_intents(
    convex: Any,
    cfg: WorkerConfig,
    *,
    composio: Any | None = None,
    now: float | None = None,
) -> None:
    """Poll Composio status for pending intents; resolve (enqueue resume) or expire.

    Never raises — a failure here must not kill the loop.
    """
    now = time.time() if now is None else now
    if composio is None:
        if ComposioClient is None or not os.environ.get("COMPOSIO_API_KEY"):
            return
        composio = ComposioClient(user_id=cfg.composio_user_id)
    try:
        intents = (
            convex.query("intents:listPending", {"workerSecret": cfg.worker_secret})
            or []
        )
    except Exception:
        log.exception("listPending failed")
        return
    for it in intents:
        try:
            if now - float(it.get("createdAt", now)) > cfg.intent_ttl:
                convex.mutation(
                    "intents:expireIntent",
                    {"workerSecret": cfg.worker_secret, "id": it["id"]},
                )
                continue
            uid = it.get("userNumber") or cfg.composio_user_id
            active = []
            for tk in it.get("requiredToolkits", []):
                if composio.connection_status(tk, user_id=uid) == "ACTIVE":
                    active.append(tk)
            convex.mutation(
                "intents:resolveIntent",
                {
                    "workerSecret": cfg.worker_secret,
                    "id": it["id"],
                    "connectedToolkits": active,
                },
            )
        except Exception:
            log.exception("intent %s poll failed", it.get("id"))


def run_loop(
    cfg: WorkerConfig,
    *,
    convex: Any | None = None,
    channels: Any | None = None,
    sendblue: Any | None = None,
    process_fn: Callable[..., bool] = process_one,
    intent_fn: Callable[..., None] | None = process_intents,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
    max_iterations: int | None = None,
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
    # Build the outbound channel registry. Production: from_config (Sendblue +
    # Telegram if a bot token is set). Tests inject a single client via `channels=`
    # or the legacy `sendblue=` — both are wrapped as an iMessage-only registry.
    if channels is not None:
        registry = _as_registry(channels, cfg)
    elif sendblue is not None:
        registry = _as_registry(sendblue, cfg)
    else:
        registry = ChannelRegistry.from_config(cfg)
    i = 0
    empties = 0
    last_intent: float | None = None
    while max_iterations is None or i < max_iterations:
        # Graceful shutdown (Bug H3): stop CLAIMING new work the moment a drain was
        # requested (SIGTERM/SIGINT or desired=stopped). Any in-flight process_one
        # has already returned by the time we re-check here, so the current turn
        # always finishes; we just don't start another.
        if should_stop():
            log.info("stop requested — draining complete, exiting loop cleanly")
            return
        i += 1
        try:
            if intent_fn is not None:
                now = time_fn()
                if last_intent is None or now - last_intent >= cfg.intent_interval:
                    intent_fn(convex, cfg)
                    last_intent = now
            # Fleet heartbeat (M6): once per poll iteration in scoped mode.
            # FAIL-SOFT: a control-plane outage must never kill the loop.
            # desired="stopped" => the controller wants this container down: begin
            # a GRACEFUL drain (set the stop flag) instead of claiming more work.
            # We do NOT hard-exit mid-iteration — any in-flight turn already
            # finished, and the loop-top check exits before the next claim.
            _hb = _maybe_heartbeat(convex, cfg)
            if _hb == "stopped":
                log.warning(
                    "fleet:heartbeat desired=stopped for %s — controller requested "
                    "shutdown; draining and exiting after this iteration",
                    cfg.scoped_user_id,
                )
                request_stop()
                # Skip claiming new work this iteration; exit on next loop-top check.
                continue
            did = process_fn(convex, registry, cfg)
        except Exception:
            log.exception("worker iteration crashed")
            did = False
        if did:
            empties = 0
        else:
            empties += 1
            interval = (
                cfg.poll_interval
                if empties <= cfg.idle_after
                else cfg.idle_poll_interval
            )
            sleep_fn(interval)


# ---------------------------------------------------------------------------
# browser-harness (Lane B): replace the built-in browser with the harness skill
# ---------------------------------------------------------------------------
# Default Hermes "cli" toolsets MINUS "browser" — the built-in browser is
# replaced by the browser-harness skill, which Hermes drives via the `terminal`
# tool. ponytail: hardcoded to mirror hermes v0.11 cli defaults; if hermes adds a
# cli toolset, add it here too (the alternative — importing hermes' resolver — is
# unavailable: hermes lives in a separate venv the worker cannot import).
_CLI_TOOLSETS_NO_BROWSER = [
    "clarify",
    "code_execution",
    "cronjob",
    "delegation",
    "file",
    "image_gen",
    "memory",
    "messaging",
    "session_search",
    "skills",
    "terminal",
    "todo",
    "tts",
    "vision",
    "web",
]


def _truthy(v: str) -> bool:
    return str(v).strip().lower() not in ("", "0", "false", "no", "off")


def _enforce_model_block(hermes_home: str) -> None:
    """Force the operator's LLM provider/model/base_url into config.yaml from env.

    SECURITY: config.yaml lives on the agent-writable HERMES_HOME bind-mount and
    short-circuits Hermes' env-based model resolution. A prompt-injected agent (it
    has the `terminal` tool) could rewrite `base_url` to an attacker endpoint and
    exfiltrate every prompt PLUS the operator's MINIMAX_API_KEY. So we re-assert
    the operator's env values (OVERWRITE, not setdefault) before every Hermes turn:
    any model block the agent wrote is stomped. The api key is never written to the
    file — it stays in env, which a chat turn cannot change. The fast/medium lanes
    are already immune (they read the key from env, never config.yaml).

    No-op when MINIMAX_API_KEY is unset (a fresh tenant resolves its model from env
    directly) or the home dir is absent (tests). Fail-soft: a config hiccup logs
    rather than blocking the user's turn.
    """
    key = os.environ.get("MINIMAX_API_KEY", "")
    home = os.path.expanduser(hermes_home)
    if not key or not os.path.isdir(home):
        return
    cfg_path = os.path.join(home, "config.yaml")
    try:
        cfg: dict = {}
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f) or {}
        is_or = key.startswith("sk-or-")
        model = cfg.setdefault("model", {})
        model["default"] = os.environ.get("MINIMAX_MODEL") or (
            "minimax/minimax-m3" if is_or else "MiniMax-M3"
        )
        model["provider"] = "minimax"
        model["base_url"] = os.environ.get("MINIMAX_BASE_URL") or (
            "https://openrouter.ai/api/v1" if is_or else "https://api.minimax.io/v1"
        )
        with open(cfg_path, "w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
    except Exception as e:  # fail-soft: a config hiccup must not block the turn
        log.warning("could not enforce LLM provider in %s: %s", cfg_path, e)


def seed_browser_harness(hermes_home: str) -> bool:
    """Idempotently flip a tenant to browse via browser-harness (Lane B) instead
    of Hermes' built-in browser: disable the `browser` toolset, allowlist BU_*
    through the terminal env scrubber, and seed the harness skill into the
    tenant's HERMES_HOME. Returns True if applied.

    Kill-switch: BROWSER_HARNESS_ENABLED=0 makes this a no-op and the built-in
    browser stays as the fallback. Fail-soft: any error leaves the built-in
    browser in place rather than crash-looping the worker.
    """
    if not _truthy(os.environ.get("BROWSER_HARNESS_ENABLED", "1")):
        return False
    try:
        home = os.path.expanduser(hermes_home)
        os.makedirs(home, exist_ok=True)
        cfg_path = os.path.join(home, "config.yaml")
        cfg: dict = {}
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f) or {}
        # Disable built-in browser via an explicit cli toolset list: the
        # `hermes chat` path resolves platform_toolsets, NOT disabled_toolsets.
        cfg.setdefault("platform_toolsets", {})["cli"] = list(_CLI_TOOLSETS_NO_BROWSER)
        # Let BU_* reach the harness through the terminal env scrubber.
        term = cfg.setdefault("terminal", {})
        ep = set(term.get("env_passthrough") or [])
        ep.update(["BU_NAME", "BU_CDP_URL", "BU_CDP_WS"])
        term["env_passthrough"] = sorted(ep)
        with open(cfg_path, "w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
        # Writing a config.yaml short-circuits Hermes' env-based model resolution
        # (a fresh tenant with NO config.yaml resolves its model from MINIMAX_*
        # env; once a config exists Hermes loads it and would have no model ->
        # HTTP 400 "No models provided"). Force the model block from the operator's
        # env so it's present AND so an agent-tampered provider can't persist.
        _enforce_model_block(home)
        # Seed the skill instruction so Hermes knows to drive the harness.
        src = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "skills",
            "browser-harness",
            "SKILL.md",
        )
        if os.path.exists(src):
            dst_dir = os.path.join(home, "skills", "browser-harness")
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copyfile(src, os.path.join(dst_dir, "SKILL.md"))
        log.info(
            "browser-harness: tenant flipped to Lane B (built-in browser disabled)"
        )
        return True
    except Exception as e:  # fail-soft: keep the built-in browser
        log.warning("browser-harness seed failed (built-in browser remains): %s", e)
        return False


def seed_create_site(hermes_home: str) -> bool:
    """Idempotently install the create-site skill so the agent can build & deploy
    personalized sites/apps in chat. Copies SKILL.md + publish.py into the tenant's
    HERMES_HOME, exports SITE_PUBLISH_PY (its absolute path), and allowlists the
    env the publish script needs (CONVEX_URL / SITES_PUBLISH_SECRET / USER_ID /
    SITE_PUBLISH_PY) through the terminal scrubber. Returns True if applied.

    Kill-switch: CREATE_SITE_ENABLED=0 -> no-op. Fail-soft: any error leaves the
    worker running without the skill rather than crash-looping. Deliberately uses
    the NARROW SITES_PUBLISH_SECRET (not WORKER_SECRET) — that secret becomes
    readable inside the agent's terminal, so its blast radius is capped at "can
    publish sites".
    """
    if not _truthy(os.environ.get("CREATE_SITE_ENABLED", "1")):
        return False
    try:
        home = os.path.expanduser(hermes_home)
        os.makedirs(home, exist_ok=True)
        # Copy the skill (SKILL.md + scripts/publish.py) into HERMES_HOME/skills.
        src_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "skills", "create-site"
        )
        dst_dir = os.path.join(home, "skills", "create-site")
        os.makedirs(os.path.join(dst_dir, "scripts"), exist_ok=True)
        for rel in ("SKILL.md", os.path.join("scripts", "publish.py")):
            s = os.path.join(src_dir, rel)
            d = os.path.join(dst_dir, rel)
            # In the operator's deployed layout HERMES_HOME is the worker's parent,
            # so src == dst — skip the self-copy (shutil.copyfile would SameFileError).
            if os.path.exists(s) and os.path.abspath(s) != os.path.abspath(d):
                shutil.copyfile(s, d)
        script = os.path.join(dst_dir, "scripts", "publish.py")
        os.environ["SITE_PUBLISH_PY"] = (
            script  # SKILL.md runs `python3 "$SITE_PUBLISH_PY"`
        )

        cfg_path = os.path.join(home, "config.yaml")
        cfg: dict = {}
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f) or {}
        term = cfg.setdefault("terminal", {})
        ep = set(term.get("env_passthrough") or [])
        ep.update(["CONVEX_URL", "SITES_PUBLISH_SECRET", "USER_ID", "SITE_PUBLISH_PY"])
        term["env_passthrough"] = sorted(ep)
        with open(cfg_path, "w") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
        # Writing config.yaml short-circuits env-based model resolution — re-assert
        # the model block (same reason as seed_browser_harness).
        _enforce_model_block(home)
        log.info("create-site: skill seeded (publish via SITES_PUBLISH_SECRET)")
        return True
    except Exception as e:  # fail-soft
        log.warning("create-site seed failed (skill unavailable this run): %s", e)
        return False


def _bootstrap_photon_inbound(
    cfg: WorkerConfig, *, convex: Any | None = None
) -> WorkerConfig:
    """Wire the Photon inbound consumer (W1) + enforce the bearer precondition (W4).

    Photon inbound flows over the loopback sidecar's /inbound stream, NOT an HTTP
    webhook, so SOMETHING in-process must consume it — otherwise no iMessage ever
    arrives via Photon. When IMESSAGE_PROVIDER=photon:

      W4: a missing PHOTON_SIDECAR_TOKEN (cfg.photon_bearer) would make the sidecar
          exit(2) on launch. Rather than spawn a doomed sidecar, log FATAL and fall
          back to Sendblue (the kill-switch) for THIS run — return a cfg with the
          effective provider flipped to "sendblue".

      W1: with a bearer present, (a) build the imessage PhotonChannel via the
          registry and ensure its sidecar ONCE (brings up the loopback /inbound),
          and (b) start a daemon thread running PhotonInboundConsumer.run_forever.
          The consumer's url/token are derived from the SAME cfg fields the channel
          uses (cfg.photon_sidecar_base / cfg.photon_bearer) — a single source, so
          there is no second literal and no 8789/8790 port divergence.

    Returns the EFFECTIVE cfg (unchanged for non-photon / valid-photon; flipped to
    Sendblue for the W4 fallback). FAIL-SOFT: any hiccup logs and degrades; it must
    NEVER block run_loop or crash the daemon.
    """
    if cfg.imessage_provider != "photon":
        return cfg

    if not cfg.photon_bearer:
        log.critical(
            "FATAL: IMESSAGE_PROVIDER=photon but PHOTON_SIDECAR_BEARER is unset — the "
            "sidecar would exit(2) on the missing token. Falling back to Sendblue for "
            "this run. Set PHOTON_SIDECAR_BEARER to enable Photon rich iMessage."
        )
        return replace(cfg, imessage_provider="sendblue")

    try:
        convex = convex or ConvexClient(cfg.convex_url)
        # (a) Build the imessage channel via the registry and ensure the sidecar once
        #     so the loopback /inbound stream is up before the consumer connects.
        registry = ChannelRegistry.from_config(cfg)
        try:
            channel = registry.get("imessage")
            _ensure_photon_sidecar(channel)
        except KeyError:
            log.warning("photon inbound: no imessage channel built; skipping consumer")
            return cfg
        # (b) Construct + start the consumer on a daemon thread. url/token come from
        #     the SAME cfg fields the channel uses (single source — no port drift).
        if PhotonInboundConsumer is None:
            log.warning("photon inbound: PhotonInboundConsumer unavailable; skipping")
            return cfg
        consumer = PhotonInboundConsumer(
            convex,
            cfg.worker_secret,
            sidecar_url=cfg.photon_sidecar_base,
            sidecar_token=cfg.photon_bearer,
        )
        threading.Thread(
            target=consumer.run_forever, name="photon-inbound", daemon=True
        ).start()
        log.info(
            "photon inbound consumer started (sidecar %s)", cfg.photon_sidecar_base
        )
    except Exception:  # FAIL-SOFT: a hiccup must never block run_loop
        log.exception("photon inbound bootstrap failed (degraded — no rich inbound)")
    return cfg


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    cfg = WorkerConfig.from_env()
    seed_browser_harness(cfg.hermes_home)
    seed_create_site(cfg.hermes_home)
    # Graceful shutdown (Bug H3): catch docker stop's SIGTERM (and Ctrl-C) so an
    # in-flight turn finishes instead of being SIGKILLed. Fail-soft.
    _install_signal_handlers()
    # Photon rich iMessage (W1/W4): wire the inbound consumer + enforce the bearer
    # precondition. Returns the EFFECTIVE cfg (flipped to Sendblue if the bearer is
    # missing) so run_loop below builds the right outbound registry.
    cfg = _bootstrap_photon_inbound(cfg)
    if cfg.fast_lane_enabled and cfg.minimax_api_key and not _fast_lane_model_ok(cfg):
        log.warning(
            "fast lane model %r does not honor thinking-disabled (only MiniMax-M3 "
            "does) — the fast lane will run with reasoning ON and be slow. Set "
            "MINIMAX_MODEL=MiniMax-M3 or FAST_LANE_ENABLED=0.",
            cfg.minimax_model,
        )
    log.info(
        "worker starting: polling %s (active %ss / idle %ss), mode=%s, "
        "model=%s, fast_lane=%s",
        cfg.convex_url,
        cfg.poll_interval,
        cfg.idle_poll_interval,
        cfg.worker_mode,
        cfg.minimax_model,
        cfg.fast_lane_enabled and bool(cfg.minimax_api_key) and fast_reply is not None,
    )
    run_loop(cfg)


if __name__ == "__main__":
    main()
