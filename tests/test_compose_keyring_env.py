"""Every service that decrypts secrets receives the whole keyring config.

``auth.keyring`` reads ``HDH_KEYRING`` (the rotation ring) before the legacy
``HDH_TOKEN_ENC_KEY``. docker-compose mapped only the legacy key, so a ring
set in ``.env`` never reached the containers: a silent no-op (failure mode
15), and after a rotation that dropped the old key from
``HDH_TOKEN_ENC_KEY`` the stored credentials would no longer open.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from auth.encryption import ENV_KEY
from auth.keyring import KEYRING_ENV

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_services_given_the_legacy_key_also_get_the_keyring() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    with_key = {
        name: service.get("environment") or {}
        for name, service in services.items()
        if ENV_KEY in (service.get("environment") or {})
    }

    assert with_key, f"no service maps {ENV_KEY}"
    missing = sorted(name for name, env in with_key.items() if KEYRING_ENV not in env)
    assert missing == [], f"{KEYRING_ENV} is not mapped for: {missing}"
    for name, env in with_key.items():
        assert env[KEYRING_ENV] == f"${{{KEYRING_ENV}:-}}", name
