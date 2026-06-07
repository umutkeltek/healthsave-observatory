"""SECURITY-003: Whoop webhook HMAC verification.

Whoop signs base64(HMAC-SHA256(client_secret, timestamp + raw_body)) in the
X-WHOOP-Signature header. The route must reject forged events when the secret is
configured, and warn-and-allow when it is not (unconfigured integration).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.api.v2_sources import _verify_whoop_signature  # noqa: E402

_SECRET = "whoop-client-secret"
_BODY = b'{"type":"recovery.updated","id":"rec-1"}'
_TS = "1700000000"


def _sign(secret: str, ts: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_valid_signature_passes(monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    headers = {
        "x-whoop-signature": _sign(_SECRET, _TS, _BODY),
        "x-whoop-signature-timestamp": _TS,
    }
    # No exception == accepted.
    assert _verify_whoop_signature(_BODY, headers) is None


def test_invalid_signature_rejected(monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    headers = {"x-whoop-signature": "not-the-right-signature", "x-whoop-signature-timestamp": _TS}
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, headers)
    assert exc.value.status_code == 401


def test_missing_signature_headers_rejected(monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, {})
    assert exc.value.status_code == 401


def test_tampered_body_rejected(monkeypatch):
    """A valid signature for the original body must not validate a forged body."""
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    headers = {
        "x-whoop-signature": _sign(_SECRET, _TS, _BODY),
        "x-whoop-signature-timestamp": _TS,
    }
    forged = b'{"type":"recovery.updated","id":"FORGED"}'
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(forged, headers)
    assert exc.value.status_code == 401


def test_unconfigured_secret_allows_with_warning(monkeypatch, caplog):
    monkeypatch.delenv("WHOOP_CLIENT_SECRET", raising=False)
    with caplog.at_level("WARNING", logger="healthsave.api.v2_sources"):
        assert _verify_whoop_signature(_BODY, {}) is None
    assert "not set" in caplog.text.lower()
