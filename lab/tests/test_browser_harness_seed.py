"""browser-harness (Lane B) seed.

worker.seed_browser_harness flips a tenant's config to browse via the harness:
disable the built-in `browser` toolset, allowlist BU_* through the terminal env
scrubber, and drop the skill into HERMES_HOME — idempotently, and gated on the
BROWSER_HARNESS_ENABLED kill-switch (off => no-op, built-in browser stays).
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "skeleton"))
from worker import seed_browser_harness, _CLI_TOOLSETS_NO_BROWSER  # noqa: E402


def _read(home) -> dict:
    return yaml.safe_load((Path(home) / "config.yaml").read_text())


def test_seed_disables_browser_keeps_terminal_and_seeds_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_HARNESS_ENABLED", "1")
    assert seed_browser_harness(str(tmp_path)) is True
    cfg = _read(tmp_path)
    cli = cfg["platform_toolsets"]["cli"]
    assert "browser" not in cli              # built-in browser disabled
    assert "terminal" in cli                 # needed to drive the harness
    assert "web" in cli and "skills" in cli  # web search + skill loading kept
    assert {"BU_NAME", "BU_CDP_URL", "BU_CDP_WS"}.issubset(
        set(cfg["terminal"]["env_passthrough"])
    )
    assert (tmp_path / "skills" / "browser-harness" / "SKILL.md").exists()


def test_seed_idempotent_and_preserves_other_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_HARNESS_ENABLED", "1")
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({
        "model": {"default": "minimax/minimax-m3"},   # unrelated tenant key
        "terminal": {"env_passthrough": ["FOO"]},      # pre-existing allowlist
    }))
    seed_browser_harness(str(tmp_path))
    seed_browser_harness(str(tmp_path))  # twice => same result
    cfg = _read(tmp_path)
    assert cfg["model"]["default"] == "minimax/minimax-m3"   # preserved
    assert "FOO" in cfg["terminal"]["env_passthrough"]        # merged, not clobbered
    assert "BU_NAME" in cfg["terminal"]["env_passthrough"]
    assert cfg["platform_toolsets"]["cli"] == _CLI_TOOLSETS_NO_BROWSER


def test_seed_fills_model_from_env_but_never_clobbers(tmp_path, monkeypatch):
    """Writing config.yaml hides Hermes' env-based model resolution -> the seed
    must set the model block from MINIMAX_* env (else: HTTP 400 'No models
    provided'), without clobbering a tenant's own model."""
    monkeypatch.setenv("BROWSER_HARNESS_ENABLED", "1")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-or-abc")
    monkeypatch.setenv("MINIMAX_MODEL", "minimax/minimax-m3")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://openrouter.ai/api/v1")
    seed_browser_harness(str(tmp_path))
    cfg = _read(tmp_path)
    assert cfg["model"]["default"] == "minimax/minimax-m3"
    assert cfg["model"]["base_url"] == "https://openrouter.ai/api/v1"
    # existing model is preserved, not overwritten
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "mine"}}))
    seed_browser_harness(str(tmp_path))
    assert _read(tmp_path)["model"]["default"] == "mine"


def test_seed_kill_switch_off_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_HARNESS_ENABLED", "0")
    assert seed_browser_harness(str(tmp_path)) is False
    assert not (tmp_path / "config.yaml").exists()  # built-in browser untouched
