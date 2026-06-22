"""create-site skill seed.

worker.seed_create_site installs the create-site skill into a tenant's
HERMES_HOME (SKILL.md + scripts/publish.py), exports SITE_PUBLISH_PY, and
allowlists exactly the env the publish script needs through the terminal
scrubber — idempotently, gated on CREATE_SITE_ENABLED, and WITHOUT ever exposing
the master WORKER_SECRET to the agent's terminal.
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import seed_create_site  # noqa: E402


def _read(home) -> dict:
    return yaml.safe_load((Path(home) / "config.yaml").read_text())


def test_seed_installs_skill_and_allowlists_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATE_SITE_ENABLED", "1")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)  # no key => model untouched
    assert seed_create_site(str(tmp_path)) is True
    # skill files copied
    assert (tmp_path / "skills" / "create-site" / "SKILL.md").exists()
    pub = tmp_path / "skills" / "create-site" / "scripts" / "publish.py"
    assert pub.exists()
    # SITE_PUBLISH_PY exported to the absolute seeded script
    import os
    assert os.environ.get("SITE_PUBLISH_PY", "").endswith("create-site/scripts/publish.py")
    # the publish env is allowlisted through the terminal scrubber
    ep = set(_read(tmp_path)["terminal"]["env_passthrough"])
    assert {"CONVEX_URL", "SITES_PUBLISH_SECRET", "USER_ID", "SITE_PUBLISH_PY"}.issubset(ep)


def test_seed_never_exposes_worker_secret(tmp_path, monkeypatch):
    """SECURITY: publish.py runs inside the agent's terminal, which sees untrusted
    inbound text. The master WORKER_SECRET (gates the whole queue) MUST NOT be in
    the allowlist — only the narrow SITES_PUBLISH_SECRET."""
    monkeypatch.setenv("CREATE_SITE_ENABLED", "1")
    seed_create_site(str(tmp_path))
    ep = set(_read(tmp_path)["terminal"]["env_passthrough"])
    assert "WORKER_SECRET" not in ep
    assert "SITES_PUBLISH_SECRET" in ep


def test_seed_idempotent_and_merges_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATE_SITE_ENABLED", "1")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({
        "model": {"default": "minimax/minimax-m3"},     # unrelated tenant key
        "terminal": {"env_passthrough": ["BU_NAME"]},    # pre-existing allowlist (e.g. browser-harness)
    }))
    seed_create_site(str(tmp_path))
    seed_create_site(str(tmp_path))  # twice => same result
    cfg = _read(tmp_path)
    assert cfg["model"]["default"] == "minimax/minimax-m3"   # preserved
    ep = set(cfg["terminal"]["env_passthrough"])
    assert "BU_NAME" in ep                  # merged, not clobbered
    assert "SITES_PUBLISH_SECRET" in ep


def test_seed_kill_switch_off_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATE_SITE_ENABLED", "0")
    assert seed_create_site(str(tmp_path)) is False
    assert not (tmp_path / "config.yaml").exists()
