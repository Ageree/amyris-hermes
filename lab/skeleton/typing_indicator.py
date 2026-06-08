"""Keep the iMessage typing indicator ("…") alive while the brain composes a reply.

Sendblue's typing-indicator auto-expiry is undocumented (only an optional
`max_duration_ms` hint), so for a long turn — a 9s medium-lane answer, a 20-37s
Hermes turn — a single "start" would fade. This helper fires "start" right away
(so the user sees activity within ~1s of their message) and re-fires on a timer
well inside `max_duration_ms`, then sends "stop" when the reply is done.

CRITICAL latency property: every "start"/poke fire is OWNED BY THE DAEMON THREAD,
never the caller. A Sendblue typing call costs ~0.5-0.7s of blocking network I/O;
doing it on the caller's thread would delay the model stream (start) and stall the
streaming read loop between bubbles (poke). So `start()` and `poke()` only SIGNAL
the thread (set an event) and return instantly — the thread does the blocking I/O
off the critical path. Only the final "stop" is fired synchronously in `stop()`,
which runs after the reply is already delivered (off the perceived-latency path).

Everything is BEST-EFFORT: typing is cosmetic and must NEVER block or break the
actual reply. Every Sendblue call is wrapped — any error (network, non-iMessage,
stale chat) is swallowed and logged at debug level.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

log = logging.getLogger("worker.typing")

DEFAULT_INTERVAL = 6.0          # re-fire cadence (seconds) — comfortably < duration
DEFAULT_MAX_DURATION_MS = 10000  # per-fire auto-expiry hint sent to Sendblue


class TypingKeepalive:
    """Fire-and-refresh the typing indicator for one recipient over one turn.

    Use as a context manager:

        with TypingKeepalive(sendblue, to_number) as typing:
            ... compose + send reply ...
            typing.poke()   # after each bubble, to re-show "…" for the next one

    Both `start()` and `poke()` return immediately; the daemon thread performs the
    blocking Sendblue calls so the reply path is never stalled by typing I/O.
    """

    def __init__(
        self,
        sendblue: Any,
        to_number: str,
        *,
        interval: float = DEFAULT_INTERVAL,
        max_duration_ms: int = DEFAULT_MAX_DURATION_MS,
        enabled: bool = True,
    ):
        self._sendblue = sendblue
        self._to = to_number
        self._interval = max(0.5, float(interval))
        self._max_duration_ms = int(max_duration_ms)
        self._enabled = bool(enabled) and bool(to_number)
        self._stop_event = threading.Event()
        self._poke_event = threading.Event()   # set by poke() -> thread re-fires "start"
        self._fired_once = threading.Event()    # set after the thread's first fire attempt
        self._thread: Optional[threading.Thread] = None
        self._started = False
        # Serializes the stop-event check with a "start" fire so a thread tick can
        # NEVER fire "start" after stop() set the event — which would re-show the
        # "…" after we cleared it (a real check-then-act race).
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "TypingKeepalive":
        """Start the keepalive. Returns immediately; the thread fires "start" ASAP."""
        if not self._enabled or self._started:
            return self
        self._started = True
        self._thread = threading.Thread(target=self._run, name="typing-keepalive", daemon=True)
        self._thread.start()
        return self

    def poke(self) -> None:
        """Ask the thread to re-show the indicator now (e.g. just after a bubble).

        Non-blocking: only signals the daemon thread. A poke after stop() is a no-op.
        """
        if self._enabled and not self._stop_event.is_set():
            self._poke_event.set()

    def stop(self) -> None:
        if not self._enabled or not self._started:
            return
        with self._lock:
            self._stop_event.set()  # under lock: no "start" can interleave after
        self._poke_event.set()      # wake the thread out of its wait so it exits promptly
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._fire("stop")  # final fire, after the event is set + thread joined

    def wait_first_fire(self, timeout: float = 2.0) -> bool:
        """Block until the thread has attempted its first fire (test/sync helper)."""
        return self._fired_once.wait(timeout)

    def __enter__(self) -> "TypingKeepalive":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # -- internals ---------------------------------------------------------
    def _run(self) -> None:
        # Immediate first fire, then re-fire on every poke OR every interval until
        # stopped. _poke_event doubles as the wakeup: poke() sets it to re-show now,
        # and stop() sets it to break the wait immediately.
        self._fire_start()
        self._fired_once.set()
        while not self._stop_event.is_set():
            self._poke_event.wait(self._interval)
            if self._stop_event.is_set():
                break
            self._poke_event.clear()
            self._fire_start()

    def _fire_start(self) -> None:
        # Atomic check-then-fire: holding the lock while testing the stop event
        # guarantees stop()'s set() either already happened (we skip) or waits
        # until we're done — so "start" never lands after "stop".
        with self._lock:
            if self._stop_event.is_set():
                return
            self._fire("start")

    def _fire(self, state: str) -> None:
        try:
            self._sendblue.send_typing(
                self._to, state=state, max_duration_ms=self._max_duration_ms
            )
        except Exception:  # cosmetic — never let typing break the reply
            log.debug("typing %s failed for %s", state, self._to, exc_info=True)
