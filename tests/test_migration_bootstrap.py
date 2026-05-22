from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_db_package_is_installed_with_editable_project() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())

    includes = data["tool"]["setuptools"]["packages"]["find"]["include"]

    assert "db*" in includes


def test_docker_image_contains_migration_runner_and_sql_files() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "COPY packages/py/db/ ./db/" in dockerfile
    assert "COPY db/migrations/ ./db/migrations/" in dockerfile
    assert "COPY scripts/ ./scripts/" in dockerfile


def test_compose_runs_migrations_before_long_lived_services() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]

    assert services["migrate"]["command"] == ["python", "-m", "scripts.migrate"]
    assert services["migrate"]["restart"] == "no"

    for service_name in ("api", "worker", "agents", "homeassistant-mqtt"):
        depends_on = services[service_name]["depends_on"]
        assert depends_on["migrate"]["condition"] == "service_completed_successfully"
