"""docker-compose.yml runs the published release images; builds stay opt-in.

A fresh install pulls the images the release workflow publishes instead of
building them, so the names in docker-compose.yml and in
.github/workflows/release.yml must agree. Building from source moves to
docker-compose.build.override.yml, and the remote VM deploy keeps building
from the deployed ref under the image names it always had.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
BUILD_OVERRIDE = ROOT / "docker-compose.build.override.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
DEPLOY_SCRIPT = ROOT / "deploy" / "remote-vm" / "deploy.sh"
EXTERNAL_DB_OVERRIDE = ROOT / "deploy" / "remote-vm" / "docker-compose.external-db.override.yml"

IMAGE_REF = re.compile(
    r"^ghcr\.io/(?P<owner>[a-z0-9-]+)/(?P<name>[a-z0-9-]+):\$\{HEALTHSAVE_VERSION:-(?P<tag>v\d+\.\d+\.\d+)\}$"
)


class _ComposeLoader(yaml.SafeLoader):
    """Reads Compose's merge tags (!override, !reset) as plain values."""


for _tag in ("!override", "!reset"):
    _ComposeLoader.add_constructor(
        _tag,
        lambda loader, node: (
            loader.construct_sequence(node)
            if isinstance(node, yaml.SequenceNode)
            else loader.construct_mapping(node)
            if isinstance(node, yaml.MappingNode)
            else loader.construct_scalar(node)
        ),
    )


def _load(text: str) -> dict:
    return yaml.load(text, Loader=_ComposeLoader)  # noqa: S506 - SafeLoader subclass


def _services(path: Path) -> dict:
    return _load(path.read_text())["services"]


def _release_images() -> dict[str, str]:
    """matrix name (api, web) -> GHCR image name the release workflow pushes."""
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    job = workflow["jobs"]["release-image"]
    return {entry["name"]: entry["image"] for entry in job["strategy"]["matrix"]["include"]}


def _release_contexts() -> dict[str, str]:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    job = workflow["jobs"]["release-image"]
    return {entry["image"]: entry["context"] for entry in job["strategy"]["matrix"]["include"]}


def _release_image_services() -> dict[str, re.Match]:
    out: dict[str, re.Match] = {}
    for name, service in _services(COMPOSE).items():
        match = IMAGE_REF.match(service.get("image", ""))
        if match:
            out[name] = match
    return out


def _rendered_remote_override(project: str = "health-data-hub") -> str:
    """The compose-mode override deploy.sh writes on the VM, with its defaults."""
    script = DEPLOY_SCRIPT.read_text()
    match = re.search(
        r"cat > docker-compose\.remote-vm\.override\.yml <<EOF\n(.*?)\nEOF\n", script, re.DOTALL
    )
    assert match, "deploy.sh no longer writes docker-compose.remote-vm.override.yml"
    text = match.group(1).replace('\\"', '"').replace("\\$", "$")
    for var, value in {
        "PROJECT_NAME": project,
        "DB_PUBLISH_PORT": "15432",
        "API_PORT": "18080",
        "GRAFANA_PORT": "3300",
        "WEB_PORT": "18090",
    }.items():
        text = re.sub(rf"\${var}\b", value, text)
    return text


def test_no_service_builds_by_default():
    built = [name for name, service in _services(COMPOSE).items() if "build" in service]
    assert built == [], f"docker-compose.yml builds {built}; builds belong in the build override"


def test_observatory_services_pull_the_images_the_release_publishes():
    published = set(_release_images().values())
    services = _release_image_services()
    assert set(services) == {
        "migrate",
        "api",
        "worker",
        "agents",
        "homeassistant-mqtt",
        "web",
    }
    assert {m["owner"] for m in services.values()} == {"umutkeltek"}
    assert {m["name"] for m in services.values()} == published
    assert services["web"]["name"] == _release_images()["web"]
    for name in ("migrate", "api", "worker", "agents", "homeassistant-mqtt"):
        assert services[name]["name"] == _release_images()["api"], name


def test_every_release_image_defaults_to_one_release_tag():
    tags = {m["tag"] for m in _release_image_services().values()}
    assert len(tags) == 1, f"services default to different releases: {sorted(tags)}"


def test_build_override_builds_exactly_the_release_image_services():
    build = _services(BUILD_OVERRIDE)
    services = _release_image_services()
    assert set(build) == set(services)
    contexts = _release_contexts()
    for name, match in services.items():
        spec = build[name]["build"]
        context = spec if isinstance(spec, str) else spec["context"]
        assert Path(context) == Path(contexts[match["name"]]), name


def test_remote_vm_overrides_build_from_source_under_the_old_image_names():
    services = set(_release_image_services())
    compose_mode = _load(_rendered_remote_override())["services"]
    external_mode = _services(EXTERNAL_DB_OVERRIDE)
    for label, override, prefix in (
        ("deploy.sh compose mode", compose_mode, "health-data-hub"),
        ("external-db override", external_mode, "${COMPOSE_PROJECT_NAME}"),
    ):
        for name in services:
            assert name in override, f"{label}: {name} would pull instead of build"
            assert "build" in override[name], f"{label}: {name} would pull instead of build"
            assert override[name]["image"] == f"{prefix}-{name}", f"{label}: {name}"
        assert Path(override["web"]["build"]) == Path("apps/web"), label


def test_remote_vm_compose_mode_keeps_its_port_publishes():
    services = _load(_rendered_remote_override())["services"]
    assert services["api"]["ports"] == ["${HEALTH_DATA_HUB_API_PORT:-18080}:8000"]
    assert services["web"]["ports"] == ["${HEALTH_DATA_HUB_WEB_PORT:-18090}:4173"]
    assert services["grafana"]["ports"] == ["${HEALTH_DATA_HUB_GRAFANA_PORT:-3300}:3000"]
    assert services["db"]["ports"] == ["127.0.0.1:${HEALTH_DATA_HUB_DB_PUBLISH_PORT:-15432}:5432"]


@pytest.mark.skipif(not shutil.which("docker"), reason="docker CLI is required")
def test_remote_vm_compose_mode_resolves_to_source_builds_and_vm_ports(tmp_path: Path):
    override = tmp_path / "docker-compose.remote-vm.override.yml"
    override.write_text(_rendered_remote_override())
    env = {**os.environ, "DB_PASSWORD": "test-pass", "GRAFANA_PASSWORD": "grafana-pass"}
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            str(override),
            "-p",
            "health-data-hub",
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
    services = yaml.safe_load(result.stdout)["services"]
    assert services["api"]["image"] == "health-data-hub-api"
    assert services["api"]["build"]["context"] == str(ROOT)
    assert services["web"]["image"] == "health-data-hub-web"
    assert services["web"]["build"]["context"] == str(ROOT / "apps" / "web")
    published = {
        name: [(p.get("host_ip", ""), p["published"], p["target"]) for p in svc.get("ports", [])]
        for name, svc in services.items()
    }
    assert published["api"] == [("", "18080", 8000)]
    assert published["web"] == [("", "18090", 4173)]
    assert published["grafana"] == [("", "3300", 3000)]
    assert published["db"] == [("127.0.0.1", "15432", 5432)]


def test_e2e_stacks_build_the_code_under_test():
    """The e2e gates must test this checkout, not a pulled release image."""
    makefile = (ROOT / "Makefile").read_text()
    assert "COMPOSE_FILE=docker-compose.yml:docker-compose.build.override.yml" in makefile
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    assert (
        ci["jobs"]["e2e"]["env"]["COMPOSE_FILE"]
        == "docker-compose.yml:docker-compose.build.override.yml"
    )
