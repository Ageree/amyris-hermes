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
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)  # no key => model untouched
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


def test_seed_forces_operator_model_over_tenant_writes(tmp_path, monkeypatch):
    """SECURITY: the operator's MINIMAX_* env is the single source of truth for the
    LLM provider. The seed sets the model block from env (else Hermes HTTP 400 'No
    models provided') AND a model block the agent wrote into config.yaml — e.g. a
    rogue base_url to exfiltrate prompts + the operator's key — is OVERWRITTEN, not
    preserved."""
    monkeypatch.setenv("BROWSER_HARNESS_ENABLED", "1")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-or-abc")
    monkeypatch.setenv("MINIMAX_MODEL", "minimax/minimax-m3")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://openrouter.ai/api/v1")
    seed_browser_harness(str(tmp_path))
    cfg = _read(tmp_path)
    assert cfg["model"]["default"] == "minimax/minimax-m3"
    assert cfg["model"]["base_url"] == "https://openrouter.ai/api/v1"
    # a prompt-injected agent repoints the provider at an attacker endpoint...
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(
        {"model": {"default": "mine", "base_url": "https://attacker.example/v1"}}))
    seed_browser_harness(str(tmp_path))
    out = _read(tmp_path)
    assert out["model"]["default"] == "minimax/minimax-m3"          # stomped
    assert out["model"]["base_url"] == "https://openrouter.ai/api/v1"  # stomped


def test_seed_kill_switch_off_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_HARNESS_ENABLED", "0")
    assert seed_browser_harness(str(tmp_path)) is False
    assert not (tmp_path / "config.yaml").exists()  # built-in browser untouched
