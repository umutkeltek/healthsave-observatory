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
