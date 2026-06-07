"""SECURITY-002: the client-supplied X-User-Id is not trusted by default.

With a single shared API key there is no way to authenticate that a caller may
act as a given owner, so honoring an arbitrary X-User-Id is a cross-tenant
spoof. resolve_owner_id therefore ignores the header unless ALLOW_MULTI_USER is
explicitly enabled (the seam where real per-owner-key auth will plug in).
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.ingestion import owner  # noqa: E402

_OTHER = "11111111-1111-1111-1111-111111111111"


def test_resolve_owner_ignores_x_user_id_by_default(monkeypatch):
    monkeypatch.setattr(owner, "ALLOW_MULTI_USER", False)
    # A spoofed X-User-Id is ignored -> default owner (spoof closed).
    assert owner.resolve_owner_id(_OTHER) == owner.DEFAULT_OWNER_ID
    assert owner.resolve_owner_id(None) == owner.DEFAULT_OWNER_ID


def test_resolve_owner_honors_x_user_id_when_multi_user_enabled(monkeypatch):
    monkeypatch.setattr(owner, "ALLOW_MULTI_USER", True)
    assert owner.resolve_owner_id(_OTHER) == UUID(_OTHER)
    # Empty/missing still falls back to the sentinel.
    assert owner.resolve_owner_id(None) == owner.DEFAULT_OWNER_ID
    assert owner.resolve_owner_id("   ") == owner.DEFAULT_OWNER_ID


def test_resolve_owner_rejects_malformed_when_multi_user_enabled(monkeypatch):
    monkeypatch.setattr(owner, "ALLOW_MULTI_USER", True)
    with pytest.raises(ValueError):
        owner.resolve_owner_id("not-a-uuid")
