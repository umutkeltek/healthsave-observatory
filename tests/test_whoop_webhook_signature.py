"""SECURITY-003: Whoop webhook HMAC verification, freshness window and replay.

Whoop signs base64(HMAC-SHA256(client_secret, timestamp + raw_body)) in the
X-WHOOP-Signature header; the timestamp (milliseconds since the epoch) travels in
X-WHOOP-Signature-Timestamp. The route must reject forged events and stale or
malformed timestamps when the secret is configured, apply an identical signed
delivery only once inside the window, and warn-and-allow when the secret is not
configured (unconfigured integration).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.api import v2_sources  # noqa: E402
from server.api.v2_sources import (  # noqa: E402
    _RecentDeliveries,
    _SignedDelivery,
    _verify_whoop_signature,
)

from plugins.sources.whoop import WhoopSource  # noqa: E402

_SECRET = "whoop-client-secret"
_BODY = b'{"type":"recovery.updated","id":"rec-1"}'
_NOW = 1_700_000_000.0
_TS = str(int(_NOW * 1000))
_URL = "/api/v2/sources/whoop/webhook"


def _sign(secret: str, ts: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def _headers(ts: str, body: bytes = _BODY, secret: str = _SECRET) -> dict[str, str]:
    return {"x-whoop-signature": _sign(secret, ts, body), "x-whoop-signature-timestamp": ts}


@pytest.fixture(autouse=True)
def _fresh_delivery_memory():
    v2_sources._RECENT_WHOOP_DELIVERIES.clear()
    yield
    v2_sources._RECENT_WHOOP_DELIVERIES.clear()


# --- the signature check -----------------------------------------------------


def test_valid_signature_in_window_passes(monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    headers = _headers(_TS)
    delivery = _verify_whoop_signature(_BODY, headers, now=_NOW)
    assert delivery == _SignedDelivery(signature=headers["x-whoop-signature"], signed_at=_NOW)


@pytest.mark.parametrize("offset_ms", [0, -300_000, 300_000, -1, 1])
def test_timestamp_up_to_five_minutes_either_way_is_fresh(monkeypatch, offset_ms):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    ts = str(int(_NOW * 1000) + offset_ms)
    assert _verify_whoop_signature(_BODY, _headers(ts), now=_NOW) is not None


@pytest.mark.parametrize("offset_ms", [-300_001, 300_001, -3_600_000, 3_600_000, -86_400_000])
def test_stale_or_future_timestamp_rejected(monkeypatch, offset_ms):
    """Correctly signed but outside the window: a captured delivery replayed late."""
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    ts = str(int(_NOW * 1000) + offset_ms)
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, _headers(ts), now=_NOW)
    assert exc.value.status_code == 401
    assert exc.value.detail == "stale Whoop signature timestamp"


def test_timestamp_is_read_as_milliseconds(monkeypatch):
    """Whoop documents milliseconds; a seconds value reads as January 1970."""
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    ts = str(int(_NOW))
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, _headers(ts), now=_NOW)
    assert exc.value.detail == "stale Whoop signature timestamp"


@pytest.mark.parametrize(
    "ts",
    [
        "not-a-timestamp",
        "1.7e12",
        "1700000000000.0",
        "-1700000000000",
        "+1700000000000",
        " 1700000000000",
        "1_700_000_000_000",
        "１７００００００００００００",  # full-width digits: str.isdigit() says yes
        "1" * 17,
        "9" * 5000,
    ],
)
def test_non_numeric_timestamp_rejected(monkeypatch, ts):
    """Signed correctly, so the rejection is the format, not the signature."""
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    headers = {"x-whoop-signature": "x", "x-whoop-signature-timestamp": ts}
    if ts.isascii():
        headers = _headers(ts)
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, headers, now=_NOW)
    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid Whoop signature timestamp"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-whoop-signature-timestamp": _TS},
        {"x-whoop-signature": _sign(_SECRET, _TS, _BODY)},
        {"x-whoop-signature": "", "x-whoop-signature-timestamp": _TS},
        {"x-whoop-signature": _sign(_SECRET, _TS, _BODY), "x-whoop-signature-timestamp": ""},
    ],
    ids=["none", "no-signature", "no-timestamp", "empty-signature", "empty-timestamp"],
)
def test_missing_signature_headers_rejected(monkeypatch, headers):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, headers, now=_NOW)
    assert exc.value.status_code == 401
    assert exc.value.detail == "missing Whoop signature headers"


def test_invalid_signature_rejected_even_with_a_fresh_timestamp(monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    headers = {"x-whoop-signature": "not-the-right-signature", "x-whoop-signature-timestamp": _TS}
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, headers, now=_NOW)
    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid Whoop signature"


def test_signature_from_another_secret_rejected(monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, _headers(_TS, secret="someone-else"), now=_NOW)
    assert exc.value.detail == "invalid Whoop signature"


def test_forged_signature_on_a_stale_timestamp_reports_the_signature(monkeypatch):
    """The HMAC is checked before freshness: a forger learns nothing about the window."""
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    stale = str(int(_NOW * 1000) - 3_600_000)
    headers = {"x-whoop-signature": "forged", "x-whoop-signature-timestamp": stale}
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, headers, now=_NOW)
    assert exc.value.detail == "invalid Whoop signature"


def test_non_ascii_signature_is_a_401_not_a_crash(monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    headers = {"x-whoop-signature": "sïgnature", "x-whoop-signature-timestamp": _TS}
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, headers, now=_NOW)
    assert exc.value.status_code == 401


def test_tampered_body_rejected(monkeypatch):
    """A valid signature for the original body must not validate a forged body."""
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    forged = b'{"type":"recovery.updated","id":"FORGED"}'
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(forged, _headers(_TS), now=_NOW)
    assert exc.value.status_code == 401


def test_signature_does_not_transfer_to_another_timestamp(monkeypatch):
    """Re-stamping a captured delivery with a fresh time breaks the signature."""
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    old = str(int(_NOW * 1000) - 3_600_000)
    headers = {"x-whoop-signature": _sign(_SECRET, old, _BODY), "x-whoop-signature-timestamp": _TS}
    with pytest.raises(HTTPException) as exc:
        _verify_whoop_signature(_BODY, headers, now=_NOW)
    assert exc.value.detail == "invalid Whoop signature"


def test_unconfigured_secret_allows_with_warning(monkeypatch, caplog):
    monkeypatch.delenv("WHOOP_CLIENT_SECRET", raising=False)
    with caplog.at_level("WARNING", logger="healthsave.api.v2_sources"):
        assert _verify_whoop_signature(_BODY, {}) is None
    assert "not set" in caplog.text.lower()


# --- the recent-delivery memory ----------------------------------------------


def test_memory_claims_once_then_reports_duplicates():
    memory = _RecentDeliveries(max_entries=10)
    delivery = _SignedDelivery("sig-a", _NOW)
    assert memory.claim(delivery, now=_NOW) is True
    assert memory.claim(delivery, now=_NOW + 1) is False
    assert memory.claim(_SignedDelivery("sig-b", _NOW), now=_NOW + 1) is True


def test_memory_release_lets_the_same_delivery_through_again():
    memory = _RecentDeliveries(max_entries=10)
    delivery = _SignedDelivery("sig-a", _NOW)
    assert memory.claim(delivery, now=_NOW)
    memory.release(delivery)
    assert memory.claim(delivery, now=_NOW) is True


def test_memory_forgets_a_delivery_once_it_left_the_window():
    memory = _RecentDeliveries(max_entries=10)
    delivery = _SignedDelivery("sig-a", _NOW)
    assert memory.claim(delivery, now=_NOW)
    assert memory.claim(delivery, now=_NOW + 300) is False
    # Past signed_at + 5 min the entry is dropped (the signature check now
    # rejects that delivery as stale before it ever reaches the memory).
    assert memory.claim(_SignedDelivery("sig-b", _NOW + 301), now=_NOW + 301)
    assert "sig-a" not in memory._expires_at


def test_memory_is_bounded():
    memory = _RecentDeliveries(max_entries=3)
    for i in range(5):
        assert memory.claim(_SignedDelivery(f"sig-{i}", _NOW), now=_NOW)
    assert list(memory._expires_at) == ["sig-2", "sig-3", "sig-4"]


# --- the route ---------------------------------------------------------------


def _route_client(monkeypatch, *, fail_first: BaseException | None = None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server.api.deps import get_session

    class _RouteSession:
        async def commit(self) -> None:
            pass

        async def rollback(self) -> None:
            pass

    calls: list[dict] = []

    async def handle(self, payload):
        calls.append(payload["event"])
        if fail_first is not None and len(calls) == 1:
            raise fail_first
        return {"accepted": 1, "rejected": 0}

    monkeypatch.setattr(WhoopSource, "handle_webhook", handle)
    app = FastAPI()
    app.include_router(v2_sources.router)

    async def _session():
        yield _RouteSession()

    app.dependency_overrides[get_session] = _session
    return TestClient(app, raise_server_exceptions=False), calls


def _fresh_ts(offset_s: float = 0) -> str:
    return str(int((time.time() + offset_s) * 1000))


def test_route_applies_a_fresh_signed_delivery(monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    client, calls = _route_client(monkeypatch)

    response = client.post(_URL, content=_BODY, headers=_headers(_fresh_ts()))

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "result": {"accepted": 1, "rejected": 0}}
    assert calls == [{"type": "recovery.updated", "id": "rec-1"}]


def test_route_suppresses_a_replay_of_the_same_delivery(monkeypatch):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    client, calls = _route_client(monkeypatch)
    headers = _headers(_fresh_ts())

    first = client.post(_URL, content=_BODY, headers=headers)
    replay = client.post(_URL, content=_BODY, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == {
        "status": "accepted",
        "result": {"accepted": 0, "rejected": 0, "duplicate": 1},
    }
    assert len(calls) == 1


def test_route_applies_a_new_delivery_of_the_same_event(monkeypatch):
    """Same body, new signed time: a distinct delivery, applied (idempotently)."""
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    client, calls = _route_client(monkeypatch)

    client.post(_URL, content=_BODY, headers=_headers(_fresh_ts()))
    client.post(_URL, content=_BODY, headers=_headers(_fresh_ts(-1)))

    assert len(calls) == 2


def test_route_applies_the_retry_of_a_delivery_that_failed(monkeypatch):
    """A 5xx makes Whoop resend; that resend must not be taken for a replay."""
    import httpx

    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    client, calls = _route_client(monkeypatch, fail_first=httpx.ConnectError("refused"))
    headers = _headers(_fresh_ts())

    failed = client.post(_URL, content=_BODY, headers=headers)
    retried = client.post(_URL, content=_BODY, headers=headers)
    replay = client.post(_URL, content=_BODY, headers=headers)

    assert failed.status_code == 503
    assert retried.status_code == 200
    assert retried.json()["result"] == {"accepted": 1, "rejected": 0}
    assert replay.json()["result"]["duplicate"] == 1
    assert len(calls) == 2


@pytest.mark.parametrize("offset_s", [-301, 301, -3600])
def test_route_rejects_a_stale_or_future_delivery_without_work(monkeypatch, offset_s):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    client, calls = _route_client(monkeypatch)

    response = client.post(_URL, content=_BODY, headers=_headers(_fresh_ts(offset_s)))

    assert response.status_code == 401
    assert response.json() == {"detail": "stale Whoop signature timestamp"}
    assert calls == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-whoop-signature": _sign(_SECRET, _TS, _BODY)},
        {"x-whoop-signature": "x", "x-whoop-signature-timestamp": "soon"},
        {"x-whoop-signature": "forged", "x-whoop-signature-timestamp": "1"},
    ],
    ids=["unsigned", "no-timestamp", "non-numeric", "forged"],
)
def test_route_still_requires_a_valid_signature(monkeypatch, headers):
    monkeypatch.setenv("WHOOP_CLIENT_SECRET", _SECRET)
    client, calls = _route_client(monkeypatch)

    response = client.post(_URL, content=_BODY, headers=headers)

    assert response.status_code == 401
    assert calls == []


def test_route_without_a_secret_keeps_warn_and_allow(monkeypatch):
    """Unconfigured: nothing is authenticated, so nothing is remembered either."""
    monkeypatch.delenv("WHOOP_CLIENT_SECRET", raising=False)
    client, calls = _route_client(monkeypatch)

    first = client.post(_URL, content=_BODY)
    second = client.post(_URL, content=_BODY)

    assert first.status_code == second.status_code == 200
    assert len(calls) == 2
