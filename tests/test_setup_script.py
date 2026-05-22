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


def test_setup_helpers_toggle_anomaly_detection_with_ai(tmp_path):
    config_path = tmp_path / "config.yaml"
    script = f"""
set -euo pipefail
export HEALTHSAVE_SETUP_TEST=1
source "{ROOT / "setup.sh"}"
CONFIG_FILE="{config_path}"
CONFIG_EXAMPLE="{ROOT / "config.yaml.example"}"
cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
set_config_anomaly_detection_enabled true
set_config_anomaly_detection_enabled false
set_config_anomaly_detection_enabled true
"""

    subprocess.run(["bash", "-c", script], check=True)

    data = yaml.safe_load(config_path.read_text())
    assert data["analysis"]["anomaly_detection"]["enabled"] is True


def test_setup_env_file_includes_optional_source_plugin_keys(tmp_path):
    env_path = tmp_path / ".env"
    script = f"""
set -euo pipefail
export HEALTHSAVE_SETUP_TEST=1
source "{ROOT / "setup.sh"}"
ENV_FILE="{env_path}"
write_env_file "db-pass" "grafana-pass" "api-key"
"""

    subprocess.run(["bash", "-c", script], check=True)

    body = env_path.read_text()
    for key in (
        "HDH_TOKEN_ENC_KEY=",
        "WHOOP_CLIENT_ID=",
        "WHOOP_CLIENT_SECRET=",
        "WHOOP_REDIRECT_URI=",
        "WHOOP_POLL_CRON=",
        "AMAZFIT_APP_TOKEN=",
        "AMAZFIT_USER_ID=",
        "AMAZFIT_REGION=us",
        "AMAZFIT_POLL_CRON=",
    ):
        assert key in body
