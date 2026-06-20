"""IMESSAGE_PROVIDER switch in ChannelRegistry.from_config (Photon rich-messages B3).

Covers ONLY base.py's provider switch (the rest of the channel layer is in
test_channels.py). Network-free.

`from_config` reads the new cfg fields via getattr(cfg, name, default), so these
tests drive it with a SimpleNamespace fake cfg — independent of whether the
integration agent has yet added imessage_provider / photon_* to WorkerConfig.

PhotonChannel lives in channels/photon_channel.py, owned by a sibling agent and
not present in every checkout while this is built in parallel. We stub a minimal
module into sys.modules BEFORE importing base, so from_config's lazy
`from channels.photon_channel import PhotonChannel` resolves to a fake that
records the PINNED constructor kwargs — exactly the contract base.py builds to.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))


# ---- Fake PhotonChannel injected at the import path from_config uses ----------

class _FakePhotonChannel:
    """Records constructor kwargs; duck-types the `kind` the registry expects."""

    kind = "imessage"

    def __init__(self, *, sidecar_base, bearer, sidecar_dir=None,
                 project_id=None, project_secret=None, **extra):
        self.sidecar_base = sidecar_base
        self.bearer = bearer
        self.sidecar_dir = sidecar_dir
        self.project_id = project_id
        self.project_secret = project_secret
        self.extra = extra


_photon_mod = types.ModuleType("channels.photon_channel")
_photon_mod.PhotonChannel = _FakePhotonChannel
sys.modules["channels.photon_channel"] = _photon_mod

from channels.base import ChannelRegistry  # noqa: E402
from channels.sendblue_channel import SendblueChannel  # noqa: E402


def _cfg(**over):
    """A duck-typed cfg with the fields from_config reads (sendblue + photon + tg)."""
    base = dict(
        # sendblue (kill-switch default)
        sendblue_key_id="kid", sendblue_secret="sec", sendblue_from="+1999",
        bubble_max_count=4, bubble_max_chars=1200,
        telegram_bot_token="",
        # photon (added by the integration agent; read via getattr here)
        imessage_provider="sendblue",
        photon_sidecar_base="http://127.0.0.1:8790",
        photon_bearer="tok",
        photon_sidecar_dir="/tmp/photon-sidecar",
        photon_project_id="proj_123",
        photon_project_secret="shh",
    )
    base.update(over)
    return types.SimpleNamespace(**base)


# ---- provider=photon (full creds) -> PhotonChannel ---------------------------

def test_provider_photon_builds_photon_channel():
    reg = ChannelRegistry.from_config(_cfg(imessage_provider="photon"))
    ch = reg.get("imessage")
    assert isinstance(ch, _FakePhotonChannel)
    assert ch.kind == "imessage"


def test_provider_photon_passes_pinned_constructor_kwargs():
    reg = ChannelRegistry.from_config(_cfg(imessage_provider="photon"))
    ch = reg.get("imessage")
    assert ch.sidecar_base == "http://127.0.0.1:8790"
    assert ch.bearer == "tok"
    assert ch.sidecar_dir == "/tmp/photon-sidecar"
    assert ch.project_id == "proj_123"
    assert ch.project_secret == "shh"


def test_provider_photon_is_case_insensitive():
    reg = ChannelRegistry.from_config(_cfg(imessage_provider="Photon"))
    assert isinstance(reg.get("imessage"), _FakePhotonChannel)


# ---- provider=sendblue / unset -> SendblueChannel (kill-switch default) -------

def test_provider_sendblue_builds_sendblue_channel():
    reg = ChannelRegistry.from_config(_cfg(imessage_provider="sendblue"))
    assert isinstance(reg.get("imessage"), SendblueChannel)


def test_provider_unset_defaults_to_sendblue():
    # No imessage_provider attribute at all -> getattr default "sendblue".
    cfg = _cfg()
    del cfg.imessage_provider
    reg = ChannelRegistry.from_config(cfg)
    assert isinstance(reg.get("imessage"), SendblueChannel)


# ---- provider=photon but creds missing -> SAFE fallback to Sendblue ----------

def test_provider_photon_missing_creds_falls_back_to_sendblue():
    # provider says photon, but no project creds -> must NOT yield an empty
    # iMessage slot (get("imessage") would raise + strand replies). Falls back to
    # the known-good Sendblue path.
    reg = ChannelRegistry.from_config(
        _cfg(imessage_provider="photon", photon_project_id="", photon_project_secret="")
    )
    assert isinstance(reg.get("imessage"), SendblueChannel)


def test_provider_photon_missing_sidecar_base_falls_back_to_sendblue():
    reg = ChannelRegistry.from_config(
        _cfg(imessage_provider="photon", photon_sidecar_base="")
    )
    assert isinstance(reg.get("imessage"), SendblueChannel)


def test_provider_photon_no_photon_attrs_at_all_falls_back_to_sendblue():
    # Worker built before the integration agent added photon_* fields: getattr
    # defaults make provider=photon degrade to Sendblue rather than crash.
    cfg = types.SimpleNamespace(
        sendblue_key_id="kid", sendblue_secret="sec", sendblue_from="+1999",
        bubble_max_count=4, bubble_max_chars=1200, telegram_bot_token="",
        imessage_provider="photon",
    )
    reg = ChannelRegistry.from_config(cfg)
    assert isinstance(reg.get("imessage"), SendblueChannel)


# ---- telegram branch unchanged alongside the switch --------------------------

def test_photon_and_telegram_coexist():
    reg = ChannelRegistry.from_config(
        _cfg(imessage_provider="photon", telegram_bot_token="123:abc")
    )
    assert isinstance(reg.get("imessage"), _FakePhotonChannel)
    assert "telegram" in reg


def test_send_rich_is_on_the_channel_protocol():
    # Acceptance: the Protocol gained send_rich (concrete impls satisfy it).
    from channels.base import Channel
    sb = SendblueChannel(types.SimpleNamespace())
    # SendblueChannel doesn't implement send_rich yet (sibling agent owns that);
    # the Protocol MEMBER must at least be declared so isinstance/contract holds.
    assert hasattr(Channel, "send_rich")
    assert sb.kind == "imessage"
