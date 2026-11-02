"""Every golden client batch ingests under a participant key as that owner.

Participant keys (migration 029) change no byte on the wire: the same iOS
v1, iOS v2 and Android goldens the clients are pinned to replay through the
live handlers, and the only difference a participant key makes is the
``owner_id`` every written row carries. Each golden is replayed twice:

* with a participant principal on ``request.state`` (what
  ``verify_api_key`` leaves there) -> every owner-bearing write is the
  participant's owner, and the response is identical to the control;
* without one (the legacy key / open mode) -> every write is the default
  owner, exactly as before participant keys existed.

DB-free (``tests.test_api_contract.FakeSession``); reads datahub's own
mirrors, so it runs in backend-only CI too.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from server.api import deps
from server.api.access import Principal
from server.db.session import get_session
from server.ingestion.owner import DEFAULT_OWNER_ID
from storage.timescale.api_keys import hash_api_key

from tests.test_api_contract import FakeRequest, FakeResult, FakeSession, _explode_batched_params

REPO_ROOT = Path(__file__).resolve().parents[2]
V1_DIR = REPO_ROOT / "tests" / "fixtures" / "apple_healthsave"
V2_DIR = REPO_ROOT / "tests" / "fixtures" / "apple_healthsave_v2"
ANDROID_DIR = REPO_ROOT / "tests" / "fixtures" / "android_healthsave"

V1_GOLDENS = sorted(p.name for p in V1_DIR.glob("*_batch.json"))
V2_GOLDENS = sorted(p.name for p in V2_DIR.glob("*_batch.json"))
ANDROID_GOLDENS = sorted(p.name for p in ANDROID_DIR.glob("*.json"))

#: Owner-bearing writes that are not health data (receipts, source registry).
_BOOKKEEPING_TABLES = {"healthsave_sync_receipts", "sources", "source_device_streams"}

PARTICIPANT = UUID("7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00")
PARTICIPANT_KEY = "participant-alice-ingest-key"


def _headers(name: str, payload: dict) -> dict[str, str]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    payload_hash = "sha256:" + hashlib.sha256(body).hexdigest()
    headers = {
        "Idempotency-Key": payload_hash,
        "X-HealthSave-Payload-Hash": payload_hash,
        "X-HealthSave-Sync-Run-ID": f"participant-run-{name}",
        "X-HealthSave-Batch-ID": f"participant-batch-{name}",
        "X-HealthSave-Metric": payload["metric"],
        "X-HealthSave-Batch-Index": str(payload.get("batch_index", 0)),
        "X-HealthSave-Total-Batches": str(payload.get("total_batches", 1)),
    }
    if payload.get("schema_version") == 2:
        headers["X-HealthSave-Schema-Version"] = "2"
    return headers


class _Session(FakeSession):
    """FakeSession + the v2 supersede rowcount + the api_keys lookup."""

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        if "FROM api_keys WHERE key_hash" in sql:
            self.calls.append((sql, params or {}))
            if (params or {}).get("key_hash") != hash_api_key(PARTICIPANT_KEY):
                return FakeResult()
            return FakeResult(
                row=SimpleNamespace(
                    _mapping={
                        "id": UUID(int=29),
                        "label": "Alice",
                        "scope": "ingest",
                        "owner_id": PARTICIPANT,
                        "created_at": None,
                        "revoked_at": None,
                    }
                )
            )
        if sql.startswith("UPDATE") and "'superseded'" in sql:
            self.calls.append((sql, params or {}))
            result = FakeResult()
            result.rowcount = len((params or {}).get("uuids") or [])
            return result
        return await super().execute(statement, params)

    async def begin_nested(self):
        from unittest.mock import AsyncMock

        return AsyncMock()


def _request(payload: dict, headers: dict, principal: Principal | None) -> FakeRequest:
    request = FakeRequest(payload, headers=headers)
    if principal is not None:
        request.state = SimpleNamespace(api_principal=principal)
    return request


def _written_owner_ids(session: _Session) -> dict[str, set[str]]:
    """``{table: {owner_id, ...}}`` over every INSERT/UPDATE that binds an owner."""

    owners: dict[str, set[str]] = {}
    for sql, params in session.calls:
        if sql.startswith("INSERT INTO"):
            table = sql.split()[2].split("(")[0]
        elif sql.startswith("UPDATE"):
            table = sql.split()[1]
        else:
            continue
        batches = params if isinstance(params, list) else [params]
        rows = [row for batch in batches for row in _explode_batched_params(batch)]
        for row in rows:
            if "owner_id" in row and row["owner_id"] is not None:
                owners.setdefault(table, set()).add(str(row["owner_id"]))
    return owners


async def _replay(name: str, directory: Path, principal: Principal | None):
    from server.api.ingest import apple_batch
    from server.api.v2_apple_batch import v2_apple_batch

    payload = json.loads((directory / name).read_text())
    request = _request(payload, _headers(name, payload), principal)
    session = _Session()
    if payload.get("schema_version") == 2:
        result = await v2_apple_batch(request, None, session)
    else:
        result = await apple_batch(request, session)
    return result, session


CORPUS = (
    [(name, V1_DIR) for name in V1_GOLDENS]
    + [(name, V2_DIR) for name in V2_GOLDENS]
    + [(name, ANDROID_DIR) for name in ANDROID_GOLDENS]
)


def test_every_corpus_is_present() -> None:
    assert V1_GOLDENS and V2_GOLDENS and ANDROID_GOLDENS


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "directory"), CORPUS, ids=[f"{d.name}/{n}" for n, d in CORPUS])
async def test_golden_ingests_under_the_participant_owner(name: str, directory: Path) -> None:
    participant = Principal(scope="ingest", owner_id=PARTICIPANT, label="Alice")
    result, session = await _replay(name, directory, participant)
    control, control_session = await _replay(name, directory, None)

    assert result["status"] == "processed", f"{name}: {result}"
    assert result == control, f"{name}: a participant key changed the response bytes"

    written = _written_owner_ids(session)
    assert "healthsave_sync_receipts" in written, f"{name}: no receipt bound an owner"
    data_tables = set(written) - _BOOKKEEPING_TABLES
    assert data_tables, f"{name}: no health-data write bound an owner: {sorted(written)}"
    stray = {table: owners for table, owners in written.items() if owners != {str(PARTICIPANT)}}
    assert not stray, f"{name}: rows written outside the participant owner: {stray}"

    control_written = _written_owner_ids(control_session)
    assert set(control_written) == set(written)
    assert all(owners == {str(DEFAULT_OWNER_ID)} for owners in control_written.values())


def test_participant_key_header_reaches_the_rows_through_the_live_app(monkeypatch) -> None:
    """Header -> auth dependency -> request.state -> handler -> rows."""

    from server.main import app

    monkeypatch.setattr(deps, "API_KEY", "legacy-admin-key")
    payload = json.loads((V2_DIR / "heart_rate_batch.json").read_text())
    session = _Session()
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app, headers={"x-api-key": PARTICIPANT_KEY})
        body = json.dumps(payload, separators=(",", ":"))
        response = client.post(
            "/api/v2/apple/batch",
            content=body,
            headers={"content-type": "application/json"},
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert response.status_code == 200, response.text
    written = _written_owner_ids(session)
    assert written and all(owners == {str(PARTICIPANT)} for owners in written.values()), written
