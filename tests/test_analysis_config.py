"""Regression tests for Phase 1.5 analysis configuration behavior."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.config import load_config  # noqa: E402


def test_missing_config_keeps_analysis_disabled_by_default(tmp_path):
    config = load_config(tmp_path / "missing-config.yaml")

    assert config.analysis.daily_briefing.enabled is False
    assert config.analysis.anomaly_detection.enabled is False


def test_environment_overrides_llm_model_from_file(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
analysis:
  daily_briefing:
    enabled: true
llm:
  provider: "ollama"
  model: "llama3.1:8b"
  base_url: "http://ollama:11434"
""".strip()
    )
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:1b")
    monkeypatch.setenv("LLM_BASE_URL", "http://custom-ollama:11434")

    config = load_config(config_path)

    assert config.llm.model == "llama3.2:1b"
    assert config.llm.base_url == "http://custom-ollama:11434"


def test_example_config_ships_with_daily_briefing_disabled_until_setup_enables_it():
    data = yaml.safe_load(Path("config.yaml.example").read_text())

    assert data["analysis"]["daily_briefing"]["enabled"] is False
    assert data["analysis"]["anomaly_detection"]["enabled"] is False


def test_cloud_prompt_redaction_defaults_on(tmp_path):
    # Safe by construction: the opt-in cloud tier scrubs prompts unless told not to.
    config = load_config(tmp_path / "missing-config.yaml")
    assert config.llm.redact_cloud_prompts is True
    assert config.llm.redaction_salt == ""


def test_llm_fallback_env_parses_ordered_routes(tmp_path, monkeypatch):
    # Cloud routes keep their full litellm path; ollama routes drop the prefix
    # (the client re-adds it). Whitespace around entries is trimmed.
    monkeypatch.setenv("LLM_FALLBACK", "openrouter/google/gemini-2.0-flash-001, ollama/llama3.2:3b")
    config = load_config(tmp_path / "missing-config.yaml")
    assert [(e.provider, e.model) for e in config.llm.fallback] == [
        ("openrouter", "openrouter/google/gemini-2.0-flash-001"),
        ("ollama", "llama3.2:3b"),
    ]


def test_environment_can_opt_out_of_cloud_prompt_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_REDACT_CLOUD_PROMPTS", "false")
    monkeypatch.setenv("LLM_REDACTION_SALT", "pepper")

    config = load_config(tmp_path / "missing-config.yaml")

    assert config.llm.redact_cloud_prompts is False
    assert config.llm.redaction_salt == "pepper"


def test_example_config_keeps_cloud_prompt_redaction_enabled():
    data = yaml.safe_load(Path("config.yaml.example").read_text())
    assert data["llm"]["redact_cloud_prompts"] is True


def test_env_can_enable_recovery_job_without_a_config_file(tmp_path, monkeypatch):
    # The remote deploy mounts config.yaml.example (every job off) and wipes any
    # host config.yaml on redeploy, so .env is the deploy-survivable enable path.
    monkeypatch.setenv("ANALYSIS_RECOVERY_ENABLED", "true")

    config = load_config(tmp_path / "missing-config.yaml")

    assert config.analysis.recovery.enabled is True
    # Other jobs stay at their (disabled) defaults.
    assert config.analysis.daily_briefing.enabled is False


def test_env_job_enable_override_respects_falsey_values(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYSIS_TREND_ANALYSIS_ENABLED", "0")
    config = load_config(tmp_path / "missing-config.yaml")
    assert config.analysis.trend_analysis.enabled is False
