"""SECURITY-005: docker-compose ships no guessable default credentials and does
not expose Grafana (the full PHI dashboard) on all interfaces by default."""

from __future__ import annotations

from pathlib import Path

_COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_compose_has_no_changeme_default():
    assert "changeme" not in _COMPOSE.read_text()


def test_db_and_grafana_passwords_are_required():
    text = _COMPOSE.read_text()
    # `${VAR:?...}` makes compose fail loudly if the secret is unset, instead of
    # silently falling back to a guessable default.
    assert "${DB_PASSWORD:?" in text
    assert "${GRAFANA_PASSWORD:?" in text


def test_grafana_not_bound_to_all_interfaces_by_default():
    text = _COMPOSE.read_text()
    # No bare all-interfaces publish; default to loopback, env opt-in for LAN.
    assert '- "3000:3000"' not in text
    assert "${GRAFANA_BIND:-127.0.0.1}:3000:3000" in text
