"""Runtime wiring for source plugins.

Whoop and Amazfit pass in checkout tests only if ``packages/py`` is on
``sys.path``. Docker/Compose is the real user path, so pin the packaging
and env propagation explicitly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def test_docker_image_copies_auth_package_for_source_plugins():
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "COPY packages/py/auth/ ./auth/" in dockerfile


def test_docker_image_copies_agents_service_package():
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "COPY apps/agents/agents/ ./agents/" in dockerfile
    assert "ModuleNotFoundError" not in compose
    assert "does not yet COPY apps/agents/agents" not in compose


def test_api_and_worker_receive_source_plugin_environment():
    services = _compose()["services"]
    required = {
        "HDH_TOKEN_ENC_KEY": "${HDH_TOKEN_ENC_KEY:-}",
        "WHOOP_CLIENT_ID": "${WHOOP_CLIENT_ID:-}",
        "WHOOP_CLIENT_SECRET": "${WHOOP_CLIENT_SECRET:-}",
        "WHOOP_REDIRECT_URI": "${WHOOP_REDIRECT_URI:-}",
        "WHOOP_POLL_CRON": "${WHOOP_POLL_CRON:-}",
        "AMAZFIT_APP_TOKEN": "${AMAZFIT_APP_TOKEN:-}",
        "AMAZFIT_USER_ID": "${AMAZFIT_USER_ID:-}",
        "AMAZFIT_REGION": "${AMAZFIT_REGION:-us}",
        "AMAZFIT_POLL_CRON": "${AMAZFIT_POLL_CRON:-}",
    }

    for service_name in ("api", "worker"):
        env = services[service_name]["environment"]
        for key, value in required.items():
            assert env[key] == value


def test_authorize_scripts_are_runnable_without_manual_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    for script in ("scripts/amazfit_authorize.py", "scripts/whoop_authorize.py"):
        result = subprocess.run(
            [sys.executable, script, "--help"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout
