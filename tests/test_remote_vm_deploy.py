"""Remote VM deployment contracts.

The default compose file is intentionally self-contained, but the remote VM
operator lane must also support an existing central Postgres/TimescaleDB
database. These tests prevent the deploy path from quietly pointing API,
worker, migrations, or Grafana back at the bundled ``db`` service.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_DB_OVERRIDE = ROOT / "deploy" / "remote-vm" / "docker-compose.external-db.override.yml"


def _central_config() -> dict:
    env = os.environ.copy()
    env.update(
        {
            "DB_PASSWORD": "test-pass",
            "GRAFANA_PASSWORD": "grafana-pass",
            "API_KEY": "test-api-key",
            "HEALTH_DATA_HUB_API_PORT": "19080",
            "HEALTH_DATA_HUB_GRAFANA_PORT": "3900",
            "HEALTH_DATA_HUB_DB_HOST": "pg.internal",
            "HEALTH_DATA_HUB_DB_PORT": "6543",
            "HEALTH_DATA_HUB_DB_NAME": "hubdb",
            "HEALTH_DATA_HUB_DB_USER": "hubuser",
        }
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            str(EXTERNAL_DB_OVERRIDE),
            "--profile",
            "home-assistant",
            "config",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return yaml.safe_load(result.stdout)


def test_remote_vm_external_db_override_exists():
    assert EXTERNAL_DB_OVERRIDE.is_file()
    assert "db.internal" not in EXTERNAL_DB_OVERRIDE.read_text()


def test_remote_vm_external_db_services_use_external_database_url():
    config = _central_config()
    expected = "postgresql+asyncpg://hubuser:test-pass@pg.internal:6543/hubdb"

    for service_name in ("migrate", "api", "worker", "homeassistant-mqtt"):
        service = config["services"][service_name]
        assert service["environment"]["DATABASE_URL"] == expected


def test_remote_vm_external_db_override_removes_bundled_db_dependencies():
    config = _central_config()
    services = config["services"]

    assert "depends_on" not in services["migrate"]
    assert set(services["api"]["depends_on"]) == {"migrate"}
    assert set(services["worker"]["depends_on"]) == {"migrate"}
    assert "depends_on" not in services["grafana"]
    assert set(services["homeassistant-mqtt"]["depends_on"]) == {"migrate"}


def test_remote_vm_external_db_override_points_grafana_at_external_db():
    config = _central_config()
    grafana = config["services"]["grafana"]

    assert grafana["environment"]["HDH_GRAFANA_DATASOURCE_URL"] == "pg.internal:6543"
    assert grafana["environment"]["DB_PASSWORD"] == "test-pass"


def test_remote_vm_external_db_override_keeps_remote_ports():
    config = _central_config()

    api_ports = config["services"]["api"]["ports"]
    grafana_ports = config["services"]["grafana"]["ports"]

    assert any(p["published"] == "19080" and p["target"] == 8000 for p in api_ports)
    assert any(p["published"] == "3900" and p["target"] == 3000 for p in grafana_ports)


def test_grafana_datasource_url_is_environment_driven():
    datasource = ROOT / "deploy" / "grafana" / "provisioning" / "datasources" / "healthsave.yaml"
    body = datasource.read_text()

    assert "url: ${HDH_GRAFANA_DATASOURCE_URL}" in body
    assert "url: db:5432" not in body


def test_remote_vm_deploy_script_has_explicit_external_database_mode():
    script = (ROOT / "deploy" / "remote-vm" / "deploy.sh").read_text()

    assert "HEALTH_DATA_HUB_DATABASE_MODE" in script
    assert "docker-compose.external-db.override.yml" in script
    assert "migrate api worker grafana" in script
    assert "db migrate api worker grafana" in script
    assert "HEALTH_DATA_HUB_DB_PUBLISH_PORT" in script


def test_remote_vm_deploy_script_recreates_grafana_after_replacing_remote_tree():
    script = (ROOT / "deploy" / "remote-vm" / "deploy.sh").read_text()

    assert "up -d --no-deps --force-recreate grafana" in script


def test_remote_vm_readme_documents_external_database_mode():
    readme = (ROOT / "deploy" / "remote-vm" / "README.md").read_text()

    assert "HEALTH_DATA_HUB_DATABASE_MODE=external" in readme
    assert "HEALTH_DATA_HUB_DB_HOST=postgres.example.internal" in readme
    assert "db.internal" not in readme
