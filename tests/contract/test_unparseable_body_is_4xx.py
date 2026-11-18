"""A body that can never parse is a terminal 4xx on every ingest route, never a 500.

Python refuses to turn an integer literal longer than 4,300 digits into an int
(``sys.get_int_max_str_digits``), and ``json.loads`` then raises a plain
``ValueError``, not ``JSONDecodeError``. The batch routes caught only
``JSONDecodeError``, so such a body was a 500, which the apps retry forever: one
poison batch wedges its metric. A body that is not UTF-8 raised
``UnicodeDecodeError`` (also a ``ValueError``) the same way.

Each route now answers these exactly as it already answers malformed JSON. For
the frozen ``POST /api/apple/batch`` that answer is pinned byte for byte in the
shared response corpus (``batch_invalid_json_400.json``), which both apps
classify as terminal (iOS ``BackendResponseCorpusTests``, Android
``ResponseCorpusTest``). Owner approval for this T0 change: Umut, 2026-11-18.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

_CORPUS_400 = json.loads(
    (
        REPO_ROOT / "tests/fixtures/apple_healthsave_responses/batch_invalid_json_400.json"
    ).read_text()
)
_LIMIT = sys.get_int_max_str_digits()


# Raw text, not json.dumps: a Python int past the limit cannot be serialised either.
def _v1(qty: str = "72", batch_index: str = "0") -> bytes:
    sample = '{"date":"2026-11-18T08:00:00Z","qty":' + qty + ',"source":"Apple Watch"}'
    return (
        '{"metric":"heart_rate","batch_index":' + batch_index + ',"total_batches":1,'
        '"samples":[' + sample + "]}"
    ).encode()


def _v2(qty: str = "72") -> bytes:
    sample = (
        '{"uuid":"6f0b7c3e-2d7a-4b8e-9a51-3c1f2d4e5a60","startDate":"2026-11-18T08:00:00Z",'
        '"endDate":"2026-11-18T08:00:00Z","qty":' + qty + ',"unit":"count/min",'
        '"source":"Apple Watch"}'
    )
    return (
        '{"schema_version":2,"metric":"heart_rate","batch_index":0,"total_batches":1,'
        '"samples":[' + sample + "]}"
    ).encode()


_HUGE = "9" * (_LIMIT + 1)
_UNPARSEABLE = {
    "huge-int-just-over-the-limit": lambda build: build(qty=_HUGE),
    "huge-int-10k-digits": lambda build: build(qty="1" * 10_000),
    "huge-negative-int": lambda build: build(qty="-" + _HUGE),
    "not-utf-8": lambda build: build().replace(b"Apple Watch", b"Apple \xff Watch"),
    "malformed-json": lambda build: build()[:-1],
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    from server.main import app

    return TestClient(app, raise_server_exceptions=False)


def _post(client: TestClient, url: str, body: bytes):
    return client.post(url, content=body, headers={"content-type": "application/json"})


def test_the_int_limit_is_what_these_tests_assume():
    """If Python ever lifts the limit, the huge-int cases below parse and prove nothing."""
    assert _LIMIT == 4300
    with pytest.raises(ValueError) as exc:
        json.loads(_v1(qty=_HUGE))
    assert not isinstance(exc.value, json.JSONDecodeError)


@pytest.mark.parametrize("case", sorted(_UNPARSEABLE))
def test_v1_batch_answers_an_unparseable_body_with_the_corpus_400(client, case):
    response = _post(client, "/api/apple/batch", _UNPARSEABLE[case](_v1))

    assert response.status_code == _CORPUS_400["status"] == 400
    assert response.json() == _CORPUS_400["body"] == {"detail": "invalid JSON body"}


def test_v1_batch_huge_int_in_an_envelope_field_is_the_same_400(client):
    response = _post(client, "/api/apple/batch", _v1(batch_index=_HUGE))

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid JSON body"}


@pytest.mark.parametrize("case", sorted(_UNPARSEABLE))
def test_v2_batch_answers_an_unparseable_body_like_malformed_json(client, case):
    response = _post(client, "/api/v2/apple/batch", _UNPARSEABLE[case](_v2))

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid JSON body"}


@pytest.mark.parametrize("url", ["/api/apple/batch", "/api/v2/apple/batch"])
def test_an_int_at_the_limit_still_parses_and_reaches_validation(client, url):
    """4,300 digits is valid JSON: the schema rejects it (422), not the parser (400)."""
    body = b'{"metric":"heart_rate","batch_index":0,"total_batches":1,"samples":%s}' % (
        b"7" * _LIMIT
    )
    response = _post(client, url, body)

    assert response.status_code == 422


@pytest.mark.parametrize("signed", [False, True], ids=["unconfigured", "signed"])
def test_whoop_webhook_answers_a_huge_int_like_malformed_json(client, monkeypatch, signed):
    secret = "whoop-client-secret"
    body = b'{"type":"recovery.updated","id":%s}' % _HUGE.encode()
    headers = {"content-type": "application/json"}
    if signed:
        monkeypatch.setenv("WHOOP_CLIENT_SECRET", secret)
        ts = str(int(time.time() * 1000))
        digest = hmac.new(secret.encode(), ts.encode() + body, hashlib.sha256).digest()
        headers |= {
            "x-whoop-signature": base64.b64encode(digest).decode(),
            "x-whoop-signature-timestamp": ts,
        }
    else:
        monkeypatch.delenv("WHOOP_CLIENT_SECRET", raising=False)

    response = client.post("/api/v2/sources/whoop/webhook", content=body, headers=headers)

    assert response.status_code == 400
    assert response.json() == {"detail": "whoop webhook body must be JSON"}
