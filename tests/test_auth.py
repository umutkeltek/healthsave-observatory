"""Auth dependency enforcement (SECURITY-001 / SECURITY-006 / TEST-001).

The audit found auth was never tested: a refactor dropping the dependency or
inverting the check would pass CI green. ``verify_api_key`` reads the
module-global ``API_KEY`` at call time, so these tests monkeypatch
``server.api.deps.API_KEY`` to exercise both configured and open modes without
reloading the module.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.api import deps  # noqa: E402


def test_verify_api_key_rejects_missing_key_when_configured(monkeypatch):
    monkeypatch.setattr(deps, "API_KEY", "s3cret")
    with pytest.raises(HTTPException) as exc_info:
        deps.verify_api_key(x_api_key="")
    assert exc_info.value.status_code == 401


def test_verify_api_key_rejects_wrong_key_when_configured(monkeypatch):
    monkeypatch.setattr(deps, "API_KEY", "s3cret")
    with pytest.raises(HTTPException) as exc_info:
        deps.verify_api_key(x_api_key="wrong")
    assert exc_info.value.status_code == 401


def test_verify_api_key_accepts_matching_key(monkeypatch):
    monkeypatch.setattr(deps, "API_KEY", "s3cret")
    # No exception raised == accepted.
    assert deps.verify_api_key(x_api_key="s3cret") is None


def test_verify_api_key_refuses_when_unconfigured_and_unacknowledged(monkeypatch):
    # SECURITY-001 default-deny: no key AND no ALLOW_NO_AUTH -> 503, not open.
    monkeypatch.setattr(deps, "API_KEY", "")
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", False)
    with pytest.raises(HTTPException) as exc_info:
        deps.verify_api_key(x_api_key="")
    assert exc_info.value.status_code == 503


def test_verify_api_key_open_mode_passes_when_acknowledged(monkeypatch):
    # Explicit ALLOW_NO_AUTH opt-in keeps the keyless surface open.
    monkeypatch.setattr(deps, "API_KEY", "")
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", True)
    assert deps.verify_api_key(x_api_key="") is None
    assert deps.verify_api_key(x_api_key="anything") is None


def test_warn_if_auth_disabled_warns_when_no_key(monkeypatch, caplog):
    monkeypatch.setattr(deps, "API_KEY", "")
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", False)
    with caplog.at_level(logging.WARNING, logger="healthsave"):
        deps.warn_if_auth_disabled()
    assert "REFUSED" in caplog.text
    assert "API_KEY" in caplog.text


def test_warn_if_auth_disabled_warns_on_explicit_opt_in(monkeypatch, caplog):
    monkeypatch.setattr(deps, "API_KEY", "")
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", True)
    with caplog.at_level(logging.WARNING, logger="healthsave"):
        deps.warn_if_auth_disabled()
    assert "ALLOW_NO_AUTH" in caplog.text


def test_warn_if_auth_disabled_silent_when_key_set(monkeypatch, caplog):
    monkeypatch.setattr(deps, "API_KEY", "s3cret")
    with caplog.at_level(logging.WARNING, logger="healthsave"):
        deps.warn_if_auth_disabled()
    assert caplog.text == ""
