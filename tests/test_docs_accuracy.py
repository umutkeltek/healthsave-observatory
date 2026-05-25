"""Docs should describe the shipped surface, not an older migration state."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_readme_and_bridge_list_all_shipped_grafana_dashboards():
    readme = (ROOT / "README.md").read_text()
    bridge = (ROOT / "BRIDGE.md").read_text()

    for text in (readme, bridge):
        for expected in (
            "HealthSave Overview",
            "Activity & Movement",
            "Heart",
            "Sleep",
            "Insights",
            "Workouts",
        ):
            assert expected in text

    assert "Three auto-provisioned Grafana dashboards" not in bridge


def test_source_plugin_readmes_match_worker_and_ingest_state():
    whoop = (ROOT / "plugins" / "sources" / "whoop" / "README.md").read_text()
    amazfit = (ROOT / "plugins" / "sources" / "amazfit" / "README.md").read_text()

    assert "worker scheduler registration" not in whoop
    assert "remaining piece" not in whoop
    assert "raises `NotImplementedError`" not in amazfit
    assert "H-ingest ships" in amazfit


def test_source_plugin_runtime_docs_match_amazfit_ingest_state():
    docs = [
        ROOT / ".env.example",
        ROOT / "apps" / "worker" / "worker" / "sources.py",
        ROOT / "plugins" / "sources" / "amazfit" / "__init__.py",
    ]
    combined = "\n".join(path.read_text() for path in docs)

    assert "Amazfit/Zepp next" not in combined
    assert "Amazfit next" not in combined
    assert "AmazfitSource shell raises NotImplementedError" not in combined
    assert "until the H-ingest commit lands" not in combined


def test_source_plugin_docs_use_docker_safe_operator_commands():
    docs = [
        ROOT / ".env.example",
        ROOT / "setup.sh",
        ROOT / "plugins" / "sources" / "whoop" / "README.md",
        ROOT / "plugins" / "sources" / "amazfit" / "README.md",
    ]
    combined = "\n".join(path.read_text() for path in docs)

    bad_bare_keygen = [
        line
        for line in combined.splitlines()
        if line.strip().startswith(
            ("python -c", "#   python -c", "HDH_TOKEN_ENC_KEY=<run `python -c")
        )
    ]
    assert bad_bare_keygen == []
    assert "docker compose run --rm --no-deps --build api python -c" in combined
    assert "docker compose run --rm --build api python scripts/whoop_authorize.py" in combined
    assert "docker compose run --rm --build api python scripts/amazfit_authorize.py" in combined


def test_public_docs_describe_healthsave_delivery_receipts():
    docs = [
        ROOT / "API.md",
        ROOT / "contracts" / "IOS_CROSS_CHECK.md",
    ]
    combined = "\n".join(path.read_text() for path in docs)

    for expected in (
        "receipt_id",
        "sync_run_id",
        "records_received",
        "records_accepted",
        "verification_level",
        "delivery_receipt",
    ):
        assert expected in combined

    reserved_phrase = "not yet" + " — reserved for future dedup"
    assert reserved_phrase not in combined
    assert "not yet" not in combined.lower()


def test_api_docs_split_core_contract_from_optional_datahub_receipts():
    api = (ROOT / "API.md").read_text()
    compatibility = api.split("## Compatibility tiers", 1)[1].split(
        "### `GET /api/v2/setup/diagnostics`",
        1,
    )[0]

    assert "Core app/setup contract" in compatibility
    for endpoint in (
        "`GET /api/health`",
        "`GET /api/apple/status`",
        "`POST /api/apple/batch`",
    ):
        assert endpoint in compatibility
    assert "successful `2xx`" in compatibility
    assert "Recommended retry-safe behavior" in compatibility
    assert "Optional Data Hub extensions" in compatibility
    assert "`GET /api/v2/sync/runs/latest`" in compatibility
    assert "`GET /api/v2/sync/coverage`" in compatibility
    assert "HealthSave uses those only when present" in compatibility
    assert "must implement `/api/v2/sync/runs/latest`" not in compatibility


def test_generated_plugin_registry_uses_repo_relative_paths():
    registry = ROOT / "plugins" / ".generated" / "plugin-registry.json"
    text = registry.read_text()

    local_home = "/" + "Users" + "/"
    assert local_home not in text
    assert "plugin_dir" in text
    assert "plugins/sources/apple_health_healthsave" in text


def test_tracked_public_files_do_not_leak_absolute_local_paths():
    output = subprocess.check_output(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
    )
    tracked_files = [
        ROOT / line
        for line in output.splitlines()
        if line and not line.startswith(".git") and not line.startswith("docs/HANDOFF.md")
    ]
    offenders: list[str] = []
    for path in tracked_files:
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        local_home = "/" + "Users" + "/"
        if local_home in text:
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_config_example_uses_healthsave_home_assistant_defaults():
    config_text = (ROOT / "config.yaml.example").read_text()
    compose_text = (ROOT / "docker-compose.yml").read_text()
    config = yaml.safe_load(config_text)

    mqtt = config["home_assistant"]["mqtt"]
    assert mqtt["state_topic_prefix"] == "healthsave"
    assert mqtt["device_identifier"] == "healthsave"
    assert mqtt["device_name"] == "HealthSave"
    assert "healthtrack_owl" not in config_text
    assert "healthtrack_*" not in compose_text


def test_remote_vm_deploy_docs_do_not_target_private_personal_stack():
    deploy_script = (ROOT / "deploy" / "remote-vm" / "deploy.sh").read_text()
    deploy_readme = (ROOT / "deploy" / "remote-vm" / "README.md").read_text()
    combined = deploy_script + "\n" + deploy_readme

    for private_marker in (
        "apps.internal",
        "HealthTrack",
        "personal_stack",
        "/srv/stacks/healthtrack",
        "/srv/localappdata/healthtrack",
    ):
        assert private_marker not in combined

    assert 'REMOTE_HOST="${REMOTE_HOST:-}"' in deploy_script
    assert "REMOTE_HOST=your-vm.example" in deploy_readme
    assert "apps-vm" not in deploy_script
    assert "apps-vm" not in deploy_readme


def test_runtime_docs_use_product_neutral_examples():
    docs = [
        ROOT / "apps" / "worker" / "worker" / "sources.py",
        ROOT / "plugins" / "sources" / "amazfit" / "__init__.py",
        ROOT / "plugins" / "sources" / "amazfit" / "normalize.py",
        ROOT / "plugins" / "sources" / "amazfit" / "auth.py",
        ROOT / "packages" / "py" / "homeassistant_mqtt" / "bridge.py",
        ROOT / "packages" / "py" / "homeassistant_mqtt" / "snapshot.py",
    ]
    combined = "\n".join(path.read_text() for path in docs)

    assert "personal_stack" not in combined
    assert "Umut's" not in combined


def test_ci_workflow_uses_node24_ready_action_majors():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow


def test_readme_and_bridge_list_shipped_importers():
    readme = (ROOT / "README.md").read_text()
    bridge = (ROOT / "BRIDGE.md").read_text()

    for text in (readme, bridge):
        assert "scripts/import_garmin.py" in text
        assert "scripts/import_samsung.py" in text
        assert "Health Sync" in text
