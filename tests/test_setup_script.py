"""Tests for pure setup.sh helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_setup_helpers_update_config_without_running_docker(tmp_path):
    config_path = tmp_path / "config.yaml"
    script = f"""
set -euo pipefail
export HEALTHSAVE_SETUP_TEST=1
source "{ROOT / "setup.sh"}"
CONFIG_FILE="{config_path}"
CONFIG_EXAMPLE="{ROOT / "config.yaml.example"}"
cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
set_config_daily_briefing_enabled true
set_config_llm_model "llama3.2:1b"
"""

    subprocess.run(["bash", "-c", script], check=True)

    data = yaml.safe_load(config_path.read_text())
    assert data["analysis"]["daily_briefing"]["enabled"] is True
    assert data["llm"]["model"] == "llama3.2:1b"


def test_setup_helpers_can_disable_daily_briefing(tmp_path):
    config_path = tmp_path / "config.yaml"
    script = f"""
set -euo pipefail
export HEALTHSAVE_SETUP_TEST=1
source "{ROOT / "setup.sh"}"
CONFIG_FILE="{config_path}"
CONFIG_EXAMPLE="{ROOT / "config.yaml.example"}"
cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
set_config_daily_briefing_enabled true
set_config_daily_briefing_enabled false
"""

    subprocess.run(["bash", "-c", script], check=True)

    data = yaml.safe_load(config_path.read_text())
    assert data["analysis"]["daily_briefing"]["enabled"] is False
