"""Run the lab Hermes headless and return its reply text.

DISCOVERY (real run, 2026-06-08 — `cli.py -q "...PONG..."`):
  * DEFAULT mode stdout is heavily decorated: a `[2J[H` clear-screen, a full
    boxed banner (ASCII-art logo, tool/skill list, session id), the echoed
    `Query:` line, `Initializing agent...`, separator rules, an answer/error
    panel, and a `Session:` footer — all wrapped in ANSI color escapes. The
    real answer is NOT cleanly isolated, and the process exits 0 EVEN ON
    FAILURE (an HTTP 400 from the model still returned exit 0).
  * `--quiet` mode: stdout carries (essentially) just the answer, stderr is a
    single `session_id: ...` line, and — crucially — the EXIT CODE IS
    MEANINGFUL (it returned exit 1 when the underlying model call failed).

So this bridge runs `--quiet` and trusts the exit code. It also defensively
strips any leaked `<think>...</think>` reasoning blocks (M3 can emit them) and
ANSI escape sequences, then returns the trimmed text. The `hermes` shell alias
is unavailable to subprocesses, so we call the venv python + cli.py directly
(see hermes-lab-cli-ops).

NOTE (environment): at discovery time the live model call failed with
`HTTP 400: No models provided` (provider=openrouter, empty model) — a config
issue in ~/.hermes-savedlab, separate from this bridge. The unit tests below
mock subprocess.run so they do not depend on a working model; the optional live
smoke and the operator-dependent live e2e require that model routing be fixed.
"""
from __future__ import annotations

import os
import re
import subprocess

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
# CSI / OSC ANSI escape sequences (colors, cursor moves, hyperlinks).
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]")
# Hermes leaks operational notices to stdout even in --quiet mode (e.g.
# "⚠️  Normalized model 'minimax/MiniMax-M3' to 'MiniMax-M3' for minimax." —
# observed live 2026-06-08). A whole line beginning with the warning sign is
# never part of the answer; drop it so it never reaches the user's iMessage.
_NOTICE = re.compile(r"^[ \t]*⚠️?.*$", re.MULTILINE)


def run_hermes(message: str, *, hermes_home: str, hermes_dir: str,
               python_bin: str, timeout: float = 180.0) -> str:
    """Invoke headless Hermes for `message` and return the cleaned reply.

    Raises ValueError for an empty message and RuntimeError on a nonzero exit
    (which, in --quiet mode, reliably signals a failed turn).
    """
    if not message.strip():
        raise ValueError("empty message")
    env = {**os.environ, "HERMES_HOME": hermes_home}
    # SECURITY (argv flag smuggling): `message` is UNTRUSTED — it is the raw text
    # of an inbound iMessage and can be sent by any third party. cli.py uses
    # python-fire (`fire.Fire(main)`), whose flags include dangerous ones like
    # --api_key / --base_url / --provider / --image (arbitrary file read) /
    # --ignore_rules. If the message were its own argv element, a message such as
    # "--ignore_rules" would be parsed as a FLAG. We therefore fuse it into a
    # single `--query=<message>` token: Fire splits flags across argv elements but
    # never WITHIN one (it splits a token only on the first `=`), so any `--flag`
    # inside the message stays part of the query string. Fire parses values with
    # ast.literal_eval (no eval/RCE). The `--` separator the reviewer suggested is
    # an argparse idiom and does NOT bind reliably in Fire — this does.
    # (Edge case, deferred to P1B hardening: Fire literal-eval coerces a lone
    # numeric/bool/bracket token, e.g. "123" -> int; harmless, not a security issue.)
    proc = subprocess.run(
        [python_bin, f"{hermes_dir}/cli.py", "--quiet", f"--query={message}"],
        cwd=hermes_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(f"hermes exited {proc.returncode}: {stderr[:500]}")
    cleaned = _THINK.sub("", proc.stdout)
    cleaned = _ANSI.sub("", cleaned)
    cleaned = _NOTICE.sub("", cleaned).strip()
    return cleaned or "(no reply)"
