"""The optional Tailscale profile: tailnet-only, off by default, wired end to end.

Remote access is a real option only if the sidecar never starts unasked, never
publishes a host port or a Funnel, and its settings reach the container (an
.env entry that compose never maps is a silent no-op).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVE_CONFIG = ROOT / "deploy" / "tailscale" / "serve.json"


def _service() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["tailscale"]


def test_tailscale_is_opt_in_and_publishes_no_host_port():
    service = _service()
    assert service["profiles"] == ["tailscale"]
    assert "ports" not in service
    assert "network_mode" not in service
    assert "privileged" not in service and "cap_add" not in service
    assert service["environment"]["TS_USERSPACE"] == "true"


def test_tailscale_settings_are_mapped_and_documented():
    env = _service()["environment"]
    assert env["TS_AUTHKEY"] == "${TAILSCALE_AUTHKEY:-}"
    assert env["TS_HOSTNAME"] == "${TAILSCALE_HOSTNAME:-healthsave-observatory}"
    assert env["TS_AUTH_ONCE"] == "true"
    assert env["TS_SERVE_CONFIG"] == "/config/serve.json"
    assert "--no-logs-no-support" in env["TS_TAILSCALED_EXTRA_ARGS"]
    example = (ROOT / ".env.example").read_text()
    assert "\nTAILSCALE_AUTHKEY=\n" in example
    assert "\nTAILSCALE_HOSTNAME=healthsave-observatory\n" in example


def test_tailscale_keeps_its_identity_and_mounts_the_serve_config():
    volumes = _service()["volumes"]
    assert "tailscale_state:/var/lib/tailscale" in volumes
    assert "./deploy/tailscale/serve.json:/config/serve.json:ro" in volumes
    top = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["volumes"]
    assert "tailscale_state" in top


def test_serve_config_is_https_tailnet_only_web_and_api():
    serve = json.loads(SERVE_CONFIG.read_text())
    assert serve["TCP"] == {"443": {"HTTPS": True}, "8443": {"HTTPS": True}}
    assert serve["Web"] == {
        "${TS_CERT_DOMAIN}:443": {"Handlers": {"/": {"Proxy": "http://web:4173"}}},
        "${TS_CERT_DOMAIN}:8443": {"Handlers": {"/": {"Proxy": "http://api:8000"}}},
    }
    assert set(serve["AllowFunnel"].values()) == {False}


def test_remote_access_page_is_linked():
    page = ROOT / "docs" / "operations" / "remote-access.md"
    assert page.is_file()
    assert "operations/remote-access.md" in (ROOT / "docs" / "README.md").read_text()
    assert "--profile tailscale" in page.read_text()
