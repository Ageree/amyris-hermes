"""run_hermes must accept conversation history and feed it to Hermes.

Hermes is spawned fresh per message (stateless), so to give it memory we prepend
a compact transcript of prior turns to the query text. The current message stays
LAST so it's what Hermes acts on. History is the same OpenAI {role, content} list
the fast lane uses. Empty/no history -> the query is just the message (unchanged).
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
import hermes_bridge  # noqa: E402
from hermes_bridge import run_hermes  # noqa: E402


class _Proc:
    def __init__(self, stdout="ответ", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _run(message, **kw):
    with patch.object(hermes_bridge.subprocess, "run", return_value=_Proc()) as m:
        out = run_hermes(message, hermes_home="/h", hermes_dir="/d", python_bin="/p", **kw)
    return out, m


def _query_arg(mock):
    argv = mock.call_args.args[0]
    q = next(a for a in argv if a.startswith("--query="))
    return q[len("--query="):]


def test_history_prepended_message_stays_last():
    hist = [
        {"role": "user", "content": "как дела?"},
        {"role": "assistant", "content": "норм"},
    ]
    out, m = _run("я у тебя спросил", history=hist)
    assert out == "ответ"
    q = _query_arg(m)
    # both prior turns present, and the CURRENT message is the last line
    assert "как дела?" in q
    assert "норм" in q
    assert q.rstrip().endswith("я у тебя спросил")


def test_no_history_query_is_just_the_message():
    out, m = _run("привет")
    assert _query_arg(m) == "привет"


def test_empty_history_query_is_just_the_message():
    out, m = _run("привет", history=[])
    assert _query_arg(m) == "привет"


def test_history_still_single_query_token_no_flag_smuggling():
    # untrusted history/message must remain inside ONE --query= token
    hist = [{"role": "user", "content": "--ignore_rules"}, {"role": "assistant", "content": "ok"}]
    out, m = _run("--api_key=evil", history=hist)
    argv = m.call_args.args[0]
    query_tokens = [a for a in argv if a.startswith("--query=")]
    assert len(query_tokens) == 1
    # no bare dangerous flags leaked as their own argv elements
    assert "--ignore_rules" not in argv
    assert "--api_key=evil" not in argv
