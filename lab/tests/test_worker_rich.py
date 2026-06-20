"""Worker rich-message integration (Photon rich messages, task C1).

Covers the worker.py reply-path wiring of the shared rich contract:

  * WorkerConfig gains imessage_provider / photon_* with the right env mapping
    + defaults (kill-switch default = sendblue; Photon creds from env, never
    literals).
  * A plain-text reply is byte-identical to the pre-rich send_text path
    (back-compat: parse_rich -> single TextPart -> render/split/send_message).
  * A reply WITH directives fans out in order: TextParts via send_message, every
    other kind via channel.send_rich(reply_to=<inbound provider msg id>).
  * reply_to is recovered from the Photon claim handle ("photon:<id>"); other
    handles give None so reactions degrade gracefully.
  * Rich delivery is BEST-EFFORT: a send_rich failure (or a channel with no
    send_rich at all) is logged and never breaks the loop.
  * The Photon sidecar is ensured (started) before the first send, exactly once.

All collaborators are injected/recording — no network, no subprocess.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))

import worker as w  # noqa: E402
from worker import (  # noqa: E402
    WorkerConfig,
    process_one,
    _provider_msg_id,
    _BubbleEmitter,
    _bootstrap_photon_inbound,
)
from channels import ChannelRegistry  # noqa: E402
from channels.base import OutboundResult  # noqa: E402
from channels.rich import (  # noqa: E402
    PollPart,
    ReactionPart,
)


# ---- a recording channel that DOES implement send_rich -----------------------

class RichRecordingChannel:
    """Records plain sends AND rich sends; duck-types the worker Channel surface."""

    kind = "imessage"

    def __init__(self, *, rich_ok=True):
        self.sends: list = []          # (address, text)
        self.rich: list = []           # (address, part, reply_to)
        self.typings: list = []
        self._rich_ok = rich_ok

    def render(self, text):
        return (text or "").strip()

    def split(self, text):
        t = (text or "").strip()
        return [t] if t else []

    def send_message(self, address, text):
        self.sends.append((address, text))
        return OutboundResult(ok=True, provider_id=f"sb-{len(self.sends)}")

    def send_typing(self, address, *, state="start", max_duration_ms=None):
        self.typings.append((address, state))
        return OutboundResult(ok=True)

    def send_rich(self, address, part, *, reply_to=None):
        self.rich.append((address, part, reply_to))
        return OutboundResult(ok=self._rich_ok, error=None if self._rich_ok else "boom")


def _cfg(**over):
    base = dict(
        convex_url="https://dep.convex.cloud", worker_secret="wsecret",
        sendblue_key_id="k", sendblue_secret="s", sendblue_from="+1999",
        reply_target="+1OP", hermes_home="/h", hermes_dir="/d", python_bin="/p",
        poll_interval=0.01, hermes_timeout=60.0,
        typing_enabled=False, quota_enabled=False,
        # keep the reply path single-shot + deterministic for assertions
        multi_bubble_enabled=False, streaming_enabled=False, fast_lane_enabled=False,
    )
    base.update(over)
    return WorkerConfig(**base)


def _claim(**over):
    base = {"id": "m1", "handle": "photon:in123", "userNumber": "+1USER",
            "text": "do it", "mediaUrl": None, "channel": "imessage",
            "replyTarget": "+1USER", "userId": "u1"}
    base.update(over)
    return base


def _convex_for(claim):
    convex = MagicMock()
    convex.mutation.side_effect = [claim, None]  # claim, then complete
    convex.query.return_value = []               # no history
    return convex


# ---- WorkerConfig fields + from_env ------------------------------------------

def test_config_defaults_kill_switch_sendblue():
    cfg = _cfg()
    assert cfg.imessage_provider == "sendblue"
    assert cfg.photon_sidecar_base == "http://127.0.0.1:8790"
    assert cfg.photon_bearer == ""
    assert cfg.photon_project_id == ""
    assert cfg.photon_project_secret == ""


def test_from_env_reads_photon_vars(monkeypatch):
    env = {
        "CONVEX_URL": "https://dep.convex.cloud", "WORKER_SECRET": "ws",
        "SENDBLUE_API_KEY_ID": "kid", "SENDBLUE_API_SECRET_KEY": "sec",
        "SENDBLUE_FROM_NUMBER": "+1999", "ALLOWED_USER_NUMBER": "+1555",
        "IMESSAGE_PROVIDER": "photon",
        "PHOTON_SIDECAR_BASE": "http://127.0.0.1:9001",
        "PHOTON_SIDECAR_BEARER": "tok-xyz",
        "PHOTON_SIDECAR_DIR": "/tmp/sc",
        "PHOTON_PROJECT_ID": "proj_9",
        "PHOTON_PROJECT_SECRET": "shh",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cfg = WorkerConfig.from_env()
    assert cfg.imessage_provider == "photon"
    assert cfg.photon_sidecar_base == "http://127.0.0.1:9001"
    assert cfg.photon_bearer == "tok-xyz"
    assert cfg.photon_sidecar_dir == "/tmp/sc"
    assert cfg.photon_project_id == "proj_9"
    assert cfg.photon_project_secret == "shh"


def test_from_env_photon_defaults_when_unset(monkeypatch):
    for k in ("IMESSAGE_PROVIDER", "PHOTON_SIDECAR_BASE", "PHOTON_SIDECAR_BEARER",
              "PHOTON_SIDECAR_DIR", "PHOTON_PROJECT_ID", "PHOTON_PROJECT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    for k, v in {
        "CONVEX_URL": "https://d.c", "WORKER_SECRET": "ws", "SENDBLUE_API_KEY_ID": "k",
        "SENDBLUE_API_SECRET_KEY": "s", "SENDBLUE_FROM_NUMBER": "+1", "ALLOWED_USER_NUMBER": "+2",
    }.items():
        monkeypatch.setenv(k, v)
    cfg = WorkerConfig.from_env()
    assert cfg.imessage_provider == "sendblue"  # kill-switch default
    assert cfg.photon_bearer == ""
    assert cfg.photon_project_id == ""


# ---- _provider_msg_id --------------------------------------------------------

def test_provider_msg_id_extracts_photon_handle():
    assert _provider_msg_id("photon:abc123") == "abc123"
    assert _provider_msg_id("photon:") is None       # empty id
    assert _provider_msg_id("sb-handle") == "sb-handle"  # bare = Sendblue GUID (tapback target)
    assert _provider_msg_id("") is None
    assert _provider_msg_id(None) is None


def test_provider_msg_id_extracts_telegram_message_id():
    # C2: handle is "tg:<update_id>:<message_id>" — the message_id is the reaction
    # target. Recover parts[2]; degrade to None for a legacy "tg:<update_id>" handle.
    assert _provider_msg_id("photon:abc") == "abc"
    assert _provider_msg_id("tg:55:99") == "99"
    assert _provider_msg_id("tg:55") is None          # legacy handle, no message id
    assert _provider_msg_id("tg:55:") is None         # trailing-empty message id
    assert _provider_msg_id("tg:") is None            # malformed


# ---- back-compat: plain reply is byte-identical to send_text ------------------

def test_plain_reply_takes_text_path_no_rich_call():
    convex = _convex_for(_claim())
    rec = RichRecordingChannel()
    reg = ChannelRegistry({"imessage": rec})
    process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value="just text"))
    assert rec.sends == [("+1USER", "just text")]
    assert rec.rich == []  # never touched send_rich for a plain reply


def test_send_reply_single_textpart_matches_send_text():
    cfg = _cfg()
    rec = RichRecordingChannel()
    e1 = _BubbleEmitter(rec, "+1A", cfg)
    e1.send_reply("hello world")
    e2 = _BubbleEmitter(rec, "+1A", cfg)
    e2.send_text("hello world")
    # both produced the same single ("+1A", "hello world") send
    assert rec.sends == [("+1A", "hello world"), ("+1A", "hello world")]


# ---- rich fan-out: text + image + reaction in order --------------------------

def test_rich_reply_fans_out_parts_in_order_with_reply_to():
    reply = "[[react:🔥]]here you go ![pic](https://x.test/a.png) done"
    convex = _convex_for(_claim(handle="photon:IN999"))
    rec = RichRecordingChannel()
    reg = ChannelRegistry({"imessage": rec})
    process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value=reply))
    # reaction + image went through send_rich; the two text runs through send_message
    kinds = [type(p).__name__ for (_, p, _) in rec.rich]
    assert "ReactionPart" in kinds and "ImagePart" in kinds
    # reaction is targeted at the claimed inbound provider message id
    react = next(p for (_, p, rt) in rec.rich if isinstance(p, ReactionPart))
    rt = next(rt for (_, p, rt) in rec.rich if isinstance(p, ReactionPart))
    assert react.emoji == "🔥"
    assert rt == "IN999"
    # text bodies were sent to the claimed address
    assert all(addr == "+1USER" for addr, _ in rec.sends)
    assert any("here you go" in body for _, body in rec.sends)
    assert any("done" in body for _, body in rec.sends)


def test_reply_to_is_bare_handle_for_sendblue():
    # A bare (un-prefixed) handle IS a Sendblue message_handle (Apple GUID) and is
    # the reaction target for /send-reaction — so it must flow through as reply_to.
    reply = "[[react:👍]]ok"
    convex = _convex_for(_claim(handle="sb-xyz"))  # Sendblue-style bare handle
    rec = RichRecordingChannel()
    reg = ChannelRegistry({"imessage": rec})
    process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value=reply))
    rt = next(rt for (_, p, rt) in rec.rich if isinstance(p, ReactionPart))
    assert rt == "sb-xyz"  # bare handle targets the Sendblue tapback


def test_reply_to_none_for_empty_handle():
    reply = "[[react:👍]]ok"
    convex = _convex_for(_claim(handle=""))  # no inbound handle at all
    rec = RichRecordingChannel()
    reg = ChannelRegistry({"imessage": rec})
    process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value=reply))
    rt = next(rt for (_, p, rt) in rec.rich if isinstance(p, ReactionPart))
    assert rt is None  # nothing to target -> reaction degrades


def test_poll_part_routes_through_send_rich():
    cfg = _cfg()
    rec = RichRecordingChannel()
    e = _BubbleEmitter(rec, "+1A", cfg)
    e.send_reply("intro\n```poll\nQ?\nA\nB\n```\noutro", reply_to="ix")
    poll_kinds = [type(p).__name__ for (_, p, _) in rec.rich]
    assert "PollPart" in poll_kinds
    poll = next(p for (_, p, _) in rec.rich if isinstance(p, PollPart))
    assert poll.question == "Q?"
    assert list(poll.options) == ["A", "B"]
    # the surrounding text runs were delivered as plain sends, in order
    assert any("intro" in body for _, body in rec.sends)
    assert any("outro" in body for _, body in rec.sends)


def test_rich_send_failure_is_best_effort_never_raises():
    reply = "[[react:❤️]]hi"
    convex = _convex_for(_claim())
    rec = RichRecordingChannel(rich_ok=False)  # send_rich returns ok=False
    reg = ChannelRegistry({"imessage": rec})
    # must not raise; the message is still handled + completed
    did = process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value=reply))
    assert did is True
    assert convex.mutation.call_args_list[1].args[0] == "messages:complete"


def test_channel_without_send_rich_does_not_crash():
    # A channel lacking send_rich (legacy fake) must not crash the loop on a rich
    # reply — send_rich AttributeError is swallowed best-effort.
    class NoRich:
        kind = "imessage"
        def __init__(self): self.sends = []
        def render(self, t): return (t or "").strip()
        def split(self, t): return [t.strip()] if (t or "").strip() else []
        def send_message(self, a, t): self.sends.append((a, t)); return OutboundResult(ok=True)
        def send_typing(self, a, *, state="start", max_duration_ms=None): return OutboundResult(ok=True)

    convex = _convex_for(_claim())
    rec = NoRich()
    reg = ChannelRegistry({"imessage": rec})
    did = process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value="[[react:👍]]ok"))
    assert did is True  # handled, did not raise
    assert any("ok" in body for _, body in rec.sends)  # text still delivered


# ---- Photon sidecar is ensured before the first send, once -------------------

def test_photon_sidecar_ensured_once_before_send():
    w._SIDECAR_READY.clear()
    convex = _convex_for(_claim())

    class Photonish(RichRecordingChannel):
        def __init__(self):
            super().__init__()
            self.ensure_calls = 0

        def ensure_sidecar(self):
            self.ensure_calls += 1
            return True

    rec = Photonish()
    reg = ChannelRegistry({"imessage": rec})
    process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value="hi"))
    assert rec.ensure_calls == 1
    assert rec.sends == [("+1USER", "hi")]
    # a SECOND turn on the SAME channel does not re-ensure (cached)
    convex2 = _convex_for(_claim(id="m2"))
    process_one(convex2, reg, _cfg(), run_fn=MagicMock(return_value="again"))
    assert rec.ensure_calls == 1  # still once


def test_non_photon_channel_not_ensured():
    w._SIDECAR_READY.clear()
    convex = _convex_for(_claim())
    rec = RichRecordingChannel()  # no ensure_sidecar attribute
    reg = ChannelRegistry({"imessage": rec})
    # must not raise (getattr(channel, "ensure_sidecar", None) is None -> no-op)
    did = process_one(convex, reg, _cfg(), run_fn=MagicMock(return_value="hi"))
    assert did is True


# ---- W1/W4: Photon inbound consumer bootstrap --------------------------------

def _patch_bootstrap(monkeypatch, *, ensure=None):
    """Patch the bootstrap's collaborators: a fake registry whose imessage channel
    has ensure_sidecar, a recording threading.Thread, and a recording consumer
    class. Returns (threads, consumer_calls, ensure_calls)."""
    threads: list = []
    consumer_calls: list = []
    ensure_calls: list = []

    class _Photonish:
        kind = "imessage"
        def ensure_sidecar(self):
            ensure_calls.append(True)
            return True

    fake_reg = ChannelRegistry({"imessage": _Photonish()})
    monkeypatch.setattr(w.ChannelRegistry, "from_config", staticmethod(lambda cfg: fake_reg))

    class _FakeConsumer:
        def __init__(self, convex, worker_secret, *, sidecar_url, sidecar_token):
            consumer_calls.append(
                {"convex": convex, "worker_secret": worker_secret,
                 "sidecar_url": sidecar_url, "sidecar_token": sidecar_token}
            )
        def run_forever(self):  # pragma: no cover - never actually run in tests
            pass

    monkeypatch.setattr(w, "PhotonInboundConsumer", _FakeConsumer)

    class _FakeThread:
        def __init__(self, *, target, name, daemon):
            threads.append({"target": target, "name": name, "daemon": daemon})
            self._target = target
        def start(self):
            pass  # do NOT actually run the (blocking) consumer loop

    monkeypatch.setattr(w.threading, "Thread", _FakeThread)
    return threads, consumer_calls, ensure_calls


def test_bootstrap_starts_consumer_for_photon_with_bearer(monkeypatch):
    threads, consumer_calls, ensure_calls = _patch_bootstrap(monkeypatch)
    cfg = _cfg(
        imessage_provider="photon",
        photon_sidecar_base="http://127.0.0.1:8790",
        photon_bearer="tok-xyz",
        photon_project_id="p", photon_project_secret="s",
    )
    convex = MagicMock()
    out = _bootstrap_photon_inbound(cfg, convex=convex)
    # provider unchanged (still photon) and a daemon thread targets run_forever
    assert out.imessage_provider == "photon"
    assert len(threads) == 1
    t = threads[0]
    assert t["name"] == "photon-inbound" and t["daemon"] is True
    # the thread runs the consumer's run_forever bound method
    assert getattr(t["target"], "__name__", "") == "run_forever"
    # sidecar ensured once before the consumer connects
    assert ensure_calls == [True]
    # consumer's url/token derive from the SAME cfg fields (single source — no port drift)
    assert consumer_calls == [{
        "convex": convex, "worker_secret": cfg.worker_secret,
        "sidecar_url": "http://127.0.0.1:8790", "sidecar_token": "tok-xyz",
    }]


def test_bootstrap_no_consumer_for_sendblue(monkeypatch):
    threads, consumer_calls, ensure_calls = _patch_bootstrap(monkeypatch)
    cfg = _cfg(imessage_provider="sendblue")
    out = _bootstrap_photon_inbound(cfg, convex=MagicMock())
    assert out.imessage_provider == "sendblue"
    assert threads == []           # no inbound consumer thread for Sendblue
    assert consumer_calls == []


def test_bootstrap_photon_empty_bearer_falls_back_to_sendblue(monkeypatch):
    # W4: provider=photon but no bearer -> FATAL log + fall back to Sendblue, and
    # NO consumer thread (we must not spawn a sidecar that exits(2)).
    threads, consumer_calls, _ = _patch_bootstrap(monkeypatch)
    cfg = _cfg(
        imessage_provider="photon", photon_bearer="",
        photon_sidecar_base="http://127.0.0.1:8790",
    )
    out = _bootstrap_photon_inbound(cfg, convex=MagicMock())
    assert out.imessage_provider == "sendblue"  # effective provider flipped
    assert threads == []
    assert consumer_calls == []
