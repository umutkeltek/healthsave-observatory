"""Docs should describe the shipped surface, not an older migration state."""

from __future__ import annotations

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


def test_config_example_uses_healthsave_home_assistant_defaults():
    config_text = (ROOT / "config.yaml.example").read_text()
    config = yaml.safe_load(config_text)

    mqtt = config["home_assistant"]["mqtt"]
    assert mqtt["state_topic_prefix"] == "healthsave"
    assert mqtt["device_identifier"] == "healthsave"
    assert mqtt["device_name"] == "HealthSave"
    assert "healthtrack_owl" not in config_text


def test_remote_vm_deploy_docs_do_not_target_private_personal_stack():
    deploy_script = (ROOT / "deploy" / "apps-vm" / "deploy.sh").read_text()
    deploy_readme = (ROOT / "deploy" / "apps-vm" / "README.md").read_text()
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
