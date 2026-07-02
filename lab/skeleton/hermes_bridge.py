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
is unavailable to subprocesses, so we call the venv python + the `hermes`
wrapper script (-> hermes_cli.main, argparse) with the `chat` subcommand. We
deliberately use this argparse entry rather than `cli.py` directly because only
it runs `discover_mcp_tools()` at startup — that's what makes configured MCP
servers (e.g. `exa` web search) available to the agent on this path (see
run_hermes for details and hermes-lab-cli-ops).

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

from text_cleaning import THINK_RE as _THINK

# CSI / OSC ANSI escape sequences (colors, cursor moves, hyperlinks).
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]")
# Hermes leaks operational notices to stdout even in --quiet mode (e.g.
# "⚠️  Normalized model 'minimax/MiniMax-M3' to 'MiniMax-M3' for minimax." —
# observed live 2026-06-08). A whole line beginning with the warning sign is
# never part of the answer; drop it so it never reaches the user's iMessage.
_NOTICE = re.compile(r"^[ \t]*⚠️?.*$", re.MULTILINE)
# Headless Hermes still prints the WHOLE tool-permission prompt to stdout in
# --quiet mode when a command trips the approval gate: a "⚠️ DANGEROUS COMMAND"
# header, the echoed command (which may span MULTIPLE lines), the
# [o]nce/[s]ession/[a]lways/[d]eny choices, and a resolution line. None of it is
# the answer — observed live 2026-06-08 glued in front of an auto-resume gmail
# reply that was texted to the user. Strip the entire block. MUST run before
# _NOTICE (which removes the ⚠️ header line and would orphan the rest). The deny
# still happens; this only cleans the user-facing reply text.
_APPROVAL = re.compile(
    r"^[ \t]*⚠️?\s*DANGEROUS COMMAND:.*?"
    r"(?:✗ Denied|✗ Cancelled|✓ Allowed once|✓ Allowed for this session|"
    r"✓ Added to permanent allowlist|⏱ Timeout - denying command)[ \t]*$",
    re.DOTALL | re.MULTILINE,
)
# Even in --quiet, Hermes renders progress + answer-panel chrome when a SKILL
# loads or the TERMINAL tool runs — i.e. the browse-via-harness path: a
# "┊ 📚 preparing skill_view…" progress tree, a "╭─ ⚕ Hermes ─╮" answer-panel
# frame, and a trailing "session_id: …" footer (observed live 2026-06-17 in the
# fleet e2e — without this the user gets 3 bubbles of pure framing). None of it
# is the answer; strip these decorative lines.
# ponytail: line-prefix heuristic on box-drawing chars + the session footer; a
# reply whose CONTENT legitimately begins with ┊/╭/╰ (rare for chat) would lose
# that line — widen the class if it ever bites.
_FRAME = re.compile(r"^[ \t]*(?:[┊╭╰].*|session_id:.*)$", re.MULTILINE)


def _with_history(message: str, history: list | None) -> str:
    """Prepend a compact transcript of prior turns; the current message stays LAST.

    Hermes is spawned fresh per message (stateless), so this is how it gets
    conversational memory. The whole string becomes a SINGLE `--query=` token (see
    the flag-smuggling note in run_hermes), so untrusted history/message text can
    never become its own argv flag.
    """
    if not history:
        return message
    lines = ["recent conversation (for context, oldest first):"]
    for turn in history:
        role = turn.get("role") if isinstance(turn, dict) else None
        content = (turn.get("content") if isinstance(turn, dict) else "") or ""
        who = (
            "system context"
            if role == "system"
            else ("you" if role == "assistant" else "user")
        )
        lines.append(f"{who}: {content}")
    lines.append("\ncurrent message (reply to this):")
    lines.append(message)
    return "\n".join(lines)


def run_hermes(
    message: str,
    *,
    hermes_home: str,
    hermes_dir: str,
    python_bin: str,
    timeout: float = 180.0,
    history: list | None = None,
) -> str:
    """Invoke headless Hermes for `message` and return the cleaned reply.

    `history` (prior {role, content} turns) is prepended as context so the
    otherwise-stateless Hermes subprocess can follow a conversation.

    Raises ValueError for an empty message and RuntimeError on a nonzero exit
    (which, in --quiet mode, reliably signals a failed turn).
    """
    if not message.strip():
        raise ValueError("empty message")
    query = _with_history(message, history)
    env = {**os.environ, "HERMES_HOME": hermes_home}
    # ENTRY POINT: we invoke the `hermes` wrapper (-> hermes_cli.main, argparse)
    # with the `chat` subcommand, NOT `cli.py` directly. WHY: only the argparse
    # entry runs `discover_mcp_tools()` at startup (hermes_cli/main.py), which
    # connects the configured MCP servers (e.g. `exa` web search) and registers
    # their tools for the turn. The bare `cli.py` (python-fire) entry NEVER does
    # MCP discovery, so MCP tools were silently absent on the worker path. The
    # underlying run logic — and therefore the stdout/stderr split and the
    # meaningful --quiet exit code this bridge relies on — is identical.
    #
    # SECURITY (argv flag smuggling): `message` is UNTRUSTED — it is the raw text
    # of an inbound iMessage and can be sent by any third party. argparse exposes
    # dangerous options (--api_key / --base_url / --provider / --image (arbitrary
    # file read) / --model / ...). If the message were its own argv element, a
    # message like "--model=evil" would be parsed as a FLAG. We therefore fuse it
    # into a SINGLE `--query=<message>` token: argparse assigns everything after
    # the first `=` to the value and never splits WITHIN one argv element, so any
    # `--flag` inside the message stays part of the query string. Live-verified
    # 2026-06-14: a query of "--model=evil-model --api_key=LEAKED ..." left the
    # model as MiniMax-M3 and was treated as plain (injection) text. stdin is
    # DEVNULL so the non-TTY worker never blocks on an interactive prompt.
    proc = subprocess.run(
        [python_bin, f"{hermes_dir}/hermes", "chat", "--quiet", f"--query={query}"],
        cwd=hermes_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(f"hermes exited {proc.returncode}: {stderr[:500]}")
    cleaned = _THINK.sub("", proc.stdout)
    cleaned = _ANSI.sub("", cleaned)
    cleaned = _APPROVAL.sub("", cleaned)
    cleaned = _NOTICE.sub("", cleaned)
    cleaned = _FRAME.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or "(no reply)"
