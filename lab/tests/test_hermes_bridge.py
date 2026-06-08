"""Tests for the headless Hermes bridge (Task 4).

The cmd assertions reflect the real headless contract discovered on 2026-06-08
(see the module docstring in hermes_bridge.py): we invoke the venv python +
cli.py with `-q <message> --quiet`. `--quiet` suppresses the banner/ASCII-art so
stdout carries (close to) just the answer, and makes the exit code meaningful.
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
    assert cmd[:2] == ["/hermes/venv/bin/python", "/hermes/cli.py"]
    assert "--quiet" in cmd
    # message fused into ONE token (flag-smuggling defense), not standalone
    assert "--query=Say PONG" in cmd
    assert "Say PONG" not in cmd
    assert kwargs["cwd"] == "/hermes"
    assert kwargs["env"]["HERMES_HOME"] == "/h"


def test_run_hermes_does_not_smuggle_flags_from_untrusted_message():
    """A message that looks like CLI flags must be fused into --query=<...>, never
    passed as standalone argv elements — python-fire would otherwise parse them as
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
