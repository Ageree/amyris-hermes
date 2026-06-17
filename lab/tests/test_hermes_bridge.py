"""Tests for the headless Hermes bridge (Task 4).

The cmd assertions reflect the real headless contract (see the module docstring
in hermes_bridge.py): we invoke the venv python + the `hermes` wrapper with the
`chat` subcommand and `--query=<message> --quiet`. The `chat` (argparse) entry —
unlike bare `cli.py` — runs MCP discovery at startup, which is what makes the
`exa` web-search tools available on this path. `--quiet` suppresses the
banner/ASCII-art so stdout carries (close to) just the answer, and makes the
exit code meaningful.
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from hermes_bridge import run_hermes


def test_run_hermes_invokes_venv_python_with_home_and_returns_reply():
    fake = MagicMock(returncode=0, stdout="PONG\n", stderr="")
    with patch("hermes_bridge.subprocess.run", return_value=fake) as m:
        out = run_hermes("Say PONG", hermes_home="/h", hermes_dir="/hermes",
                         python_bin="/hermes/venv/bin/python")
    assert out == "PONG"
    args, kwargs = m.call_args
    cmd = args[0]
    # `hermes chat` (argparse) entry — runs MCP discovery so exa tools load.
    assert cmd[:3] == ["/hermes/venv/bin/python", "/hermes/hermes", "chat"]
    assert "--quiet" in cmd
    # message fused into ONE token (flag-smuggling defense), not standalone
    assert "--query=Say PONG" in cmd
    assert "Say PONG" not in cmd
    assert kwargs["cwd"] == "/hermes"
    assert kwargs["env"]["HERMES_HOME"] == "/h"
    # non-TTY worker must never block on an interactive prompt
    import subprocess as _sp
    assert kwargs["stdin"] == _sp.DEVNULL


def test_run_hermes_does_not_smuggle_flags_from_untrusted_message():
    """A message that looks like CLI flags must be fused into --query=<...>, never
    passed as standalone argv elements — argparse would otherwise parse them as
    flags (e.g. --ignore_rules, --api_key, --image=<file>)."""
    fake = MagicMock(returncode=0, stdout="ok\n", stderr="")
    evil = "--ignore_rules --api_key=stolen"
    with patch("hermes_bridge.subprocess.run", return_value=fake) as m:
        run_hermes(evil, hermes_home="/h", hermes_dir="/d", python_bin="/p")
    cmd = m.call_args.args[0]
    assert f"--query={evil}" in cmd
    # the ONLY --flags present are our own --quiet and the fused --query=
    dash_tokens = [c for c in cmd if c.startswith("--")]
    assert dash_tokens == ["--quiet", f"--query={evil}"]


def test_run_hermes_strips_think_blocks():
    fake = MagicMock(returncode=0, stdout="<think>reasoning</think>\nThe answer is 42.\n", stderr="")
    with patch("hermes_bridge.subprocess.run", return_value=fake):
        out = run_hermes("q", hermes_home="/h", hermes_dir="/d", python_bin="/p")
    assert out == "The answer is 42."


def test_run_hermes_strips_ansi_escapes():
    fake = MagicMock(returncode=0, stdout="\x1b[1;34mHello\x1b[0m world\n", stderr="")
    with patch("hermes_bridge.subprocess.run", return_value=fake):
        out = run_hermes("q", hermes_home="/h", hermes_dir="/d", python_bin="/p")
    assert out == "Hello world"


def test_run_hermes_strips_leading_warning_notice():
    """Hermes leaks operational notices to stdout even in --quiet mode, e.g.
    `⚠️  Normalized model 'minimax/MiniMax-M3' to 'MiniMax-M3' for minimax.`
    (observed live 2026-06-08). Those must never reach the user's iMessage."""
    stdout = (
        "⚠️  Normalized model 'minimax/MiniMax-M3' to 'MiniMax-M3' for minimax.\n"
        "Example Domain\n"
    )
    fake = MagicMock(returncode=0, stdout=stdout, stderr="")
    with patch("hermes_bridge.subprocess.run", return_value=fake):
        out = run_hermes("q", hermes_home="/h", hermes_dir="/d", python_bin="/p")
    assert out == "Example Domain"


def test_run_hermes_strips_dangerous_command_approval_block():
    """Headless Hermes can hit a tool-permission gate; in --quiet mode it still
    prints the whole approval prompt (header + the echoed command + the
    [o]nce/[s]ession/[d]eny choices + the resolution line) to stdout, BEFORE the
    real answer. Observed live 2026-06-08: an auto-resume gmail reply was texted
    to the user with this scaffolding glued in front of the summary. The whole
    block — including a MULTILINE command — must be stripped; only the answer
    survives. (The deny still happens; this is reply-cleaning, not a policy
    change.)"""
    stdout = (
        "\n  ⚠️  DANGEROUS COMMAND: run a shell pipe\n"
        "      python3 /h/exec_tool.py GMAIL_FETCH_EMAILS '{\"q\": 1}' | python3 -c \"\n"
        "import json, sys\n"
        "print('parsed')\n"
        "\"\n\n"
        "      [o]nce  |  [s]ession  |  [d]eny\n\n"
        "      Choice [o/s/D]:       ✗ Denied\n\n"
        "посмотрел почту — 2 письма.\n"
    )
    fake = MagicMock(returncode=0, stdout=stdout, stderr="")
    with patch("hermes_bridge.subprocess.run", return_value=fake):
        out = run_hermes("q", hermes_home="/h", hermes_dir="/d", python_bin="/p")
    assert out == "посмотрел почту — 2 письма."


def test_run_hermes_strips_approval_block_on_timeout_and_allowed():
    """The block must be stripped regardless of how the gate resolved
    (timeout-deny or allowed), since the prompt scaffolding is never the
    answer."""
    for resolution in ("⏱ Timeout - denying command", "✓ Allowed once"):
        stdout = (
            "  ⚠️  DANGEROUS COMMAND: x\n"
            "      ls -la /tmp\n\n"
            "      [o]nce  |  [s]ession  |  [a]lways  |  [d]eny\n\n"
            "      Choice [o/s/a/D]:       " + resolution + "\n\n"
            "done.\n"
        )
        fake = MagicMock(returncode=0, stdout=stdout, stderr="")
        with patch("hermes_bridge.subprocess.run", return_value=fake):
            out = run_hermes("q", hermes_home="/h", hermes_dir="/d", python_bin="/p")
        assert out == "done.", f"resolution={resolution!r} -> {out!r}"


def test_run_hermes_strips_skill_terminal_frame_and_session_footer():
    """Live fleet e2e 2026-06-17 (browse-via-harness): loading a SKILL + using the
    TERMINAL tool makes --quiet Hermes render a "┊ 📚 preparing…" progress tree, a
    "╭─ Hermes ─╮" answer-panel frame, and a "session_id:" footer. Only the answer
    must survive — else the user gets bubbles of pure framing (seen live)."""
    stdout = (
        "┊ 📚 preparing skill_view…\n"
        "  ┊ 💻 preparing terminal…\n"
        "\n"
        "╭─ ⚕ Hermes ──────────────────────────────────╮\n"
        "Example Domain\n"
        "\n"
        "session_id: 20260617_175213_334b72\n"
    )
    fake = MagicMock(returncode=0, stdout=stdout, stderr="")
    with patch("hermes_bridge.subprocess.run", return_value=fake):
        out = run_hermes("open example.com", hermes_home="/h", hermes_dir="/d",
                         python_bin="/p")
    assert out == "Example Domain", repr(out)
    for junk in ("preparing", "session_id", "╭", "┊"):
        assert junk not in out


def test_run_hermes_raises_on_nonzero():
    fake = MagicMock(returncode=1, stdout="", stderr="boom")
    with patch("hermes_bridge.subprocess.run", return_value=fake):
        try:
            run_hermes("q", hermes_home="/h", hermes_dir="/d", python_bin="/p")
            assert False
        except RuntimeError as e:
            assert "boom" in str(e)


def test_run_hermes_rejects_empty_message():
    try:
        run_hermes("   ", hermes_home="/h", hermes_dir="/d", python_bin="/p")
        assert False
    except ValueError:
        pass


def test_run_hermes_returns_placeholder_when_stdout_blank():
    fake = MagicMock(returncode=0, stdout="<think>only thinking</think>\n", stderr="")
    with patch("hermes_bridge.subprocess.run", return_value=fake):
        out = run_hermes("q", hermes_home="/h", hermes_dir="/d", python_bin="/p")
    assert out == "(no reply)"
