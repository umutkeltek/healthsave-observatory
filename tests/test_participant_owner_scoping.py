"""Owner scoping on the phone surface and the v2 reads (migration 029).

* ``/api/apple/status`` and ``/api/apple/coverage`` keep their exact shape
  and answer for the key's owner.
* ``/api/v2/sync/runs/*`` answer for the caller's owner; the run-summary
  upsert never overwrites another owner's row.
* Owner-scoped v2 reads take ``?owner=``: an admin may name anyone, a
  participant read key only itself, an ingest key nothing.
* ``/api/v2/owners`` lists the people this Observatory holds data for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from server.api import deps, sync, v2_export, v2_owners, v2_readiness
from server.api.status import apple_status
from server.api.swr import owner_cache_key, v2_read_cache
from server.db.session import get_session
from server.ingestion.owner import DEFAULT_OWNER_ID
from server.main import app
from storage.timescale import sync_receipts
from storage.timescale.api_keys import hash_api_key

ALICE = UUID("7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00")
BOB = UUID("2f4a9c1e-6d3b-4e8f-8a2c-5b7d9e0f1a2b")
LEGACY = "legacy-admin-key"
KEYS = {
    "alice-ingest": ("ingest", ALICE),
    "alice-read": ("read", ALICE),
}


class _Result:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows if rows is not None else ([] if row is None else [row])

    def first(self):
        return self.row

    def fetchone(self):
        return self.row

    def all(self):
        return self.rows

    def mappings(self):
        return self


class _Session:
    """Answers the api_keys lookup and the status counts; records the rest."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if "FROM api_keys WHERE key_hash" in sql:
            for key, (scope, owner) in KEYS.items():
                if (params or {}).get("key_hash") == hash_api_key(key):
                    return _Result(
                        SimpleNamespace(
                            _mapping={
                                "id": UUID(int=1),
                                "label": "Alice",
                                "scope": scope,
                                "owner_id": owner,
                                "created_at": None,
                                "revoked_at": None,
                            }
                        )
                    )
            return _Result()
        if sql.startswith("SELECT count(*)"):
            return _Result((0, None, None))
        return _Result()

    async def rollback(self):
        pass

    async def commit(self):
        pass


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setattr(deps, "API_KEY", LEGACY)
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", False)
    fake = _Session()
    app.dependency_overrides[get_session] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_session, None)


def _client(key: str) -> TestClient:
    return TestClient(app, headers={"x-api-key": key})


def _owner_params(fake: _Session, needle: str) -> set[str]:
    return {params.get("owner_id") for sql, params in fake.calls if needle in sql}


# ─── T0 status: same shape, the key's owner ───────────────────────────


def test_status_answers_for_the_participant_owner(session) -> None:
    body = _client("alice-ingest").get("/api/apple/status").json()
    legacy_body = _client(LEGACY).get("/api/apple/status").json()
    assert body == legacy_body  # identical shape (and zero counts here)
    assert set(body) == {
        "heart_rate",
        "hrv",
        "blood_oxygen",
        "daily_activity",
        "sleep_sessions",
        "workouts",
        "quantity_samples",
    }
    status_owners = [p.get("owner_id") for sql, p in session.calls if "count(*)" in sql]
    assert status_owners.count(str(ALICE)) == 7
    assert status_owners.count(str(DEFAULT_OWNER_ID)) == 7


async def test_status_direct_call_is_unchanged() -> None:
    fake = _Session()
    await apple_status(SimpleNamespace(headers={}), fake)
    assert {p["owner_id"] for _, p in fake.calls} == {str(DEFAULT_OWNER_ID)}


def test_coverage_answers_for_the_participant_owner(session, monkeypatch) -> None:
    from server.api import coverage

    seen: list[UUID] = []

    async def _canonical(sess, *, owner_id):
        seen.append(owner_id)
        return []

    monkeypatch.setattr(coverage._COVERAGE_REPO, "fetch_canonical_coverage", _canonical)
    response = _client("alice-ingest").get("/api/apple/coverage")
    assert response.status_code == 200
    assert seen == [ALICE]
    assert _owner_params(session, "SELECT max(") <= {str(ALICE)}


# ─── sync runs ─────────────────────────────────────────────────────────


class _Runs:
    def __init__(self):
        self.calls: list[tuple] = []

    async def latest_sync_run(self, session, owner_id=None):
        self.calls.append(("latest", owner_id))
        return {"status": "empty", "message": "none"}

    async def sync_run(self, session, sync_run_id, owner_id=None):
        self.calls.append(("run", sync_run_id, owner_id))
        return {"status": "empty", "sync_run_id": sync_run_id, "message": "none"}


def test_sync_runs_answer_for_the_callers_owner(session, monkeypatch) -> None:
    runs = _Runs()
    monkeypatch.setattr(sync, "_SYNC_RECEIPTS", runs)
    assert _client("alice-ingest").get("/api/v2/sync/runs/latest").status_code == 200
    assert _client("alice-ingest").get("/api/v2/sync/runs/r-1").status_code == 200
    assert _client(LEGACY).get("/api/v2/sync/runs/latest").status_code == 200
    assert runs.calls == [("latest", ALICE), ("run", "r-1", ALICE), ("latest", DEFAULT_OWNER_ID)]


async def test_sync_run_direct_calls_keep_the_unscoped_query(monkeypatch) -> None:
    runs = _Runs()
    monkeypatch.setattr(sync, "_SYNC_RECEIPTS", runs)
    await sync.latest_sync_run(object())
    await sync.sync_run("r-2", object())
    assert runs.calls == [("latest", None), ("run", "r-2", None)]


class _SqlSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        return _Result()


async def test_receipt_reads_filter_by_owner_and_keep_pre_024_rows_for_default() -> None:
    participant = _SqlSession()
    await sync_receipts.latest_sync_run(participant, ALICE)
    await sync_receipts.sync_run(participant, "r-1", ALICE)
    for sql, params in participant.calls:
        assert "owner_id = CAST(:owner_id AS UUID)" in sql, sql
        assert "owner_id IS NULL" not in sql
        assert params["owner_id"] == str(ALICE)

    default = _SqlSession()
    await sync_receipts.latest_sync_run(default, DEFAULT_OWNER_ID)
    assert all("owner_id IS NULL" in sql for sql, _ in default.calls)

    unscoped = _SqlSession()
    await sync_receipts.latest_sync_run(unscoped)
    await sync_receipts.sync_run(unscoped, "r-1")
    assert not any("owner_id" in sql for sql, _ in unscoped.calls)


async def test_run_summary_upsert_never_overwrites_another_owners_row() -> None:
    fake = _SqlSession()
    ack = await sync_receipts.record_sync_run_summary(
        fake,
        owner_id=ALICE,
        sync_run_id="someone-elses-run",
        outcome="completed",
        delivery="none",
        records_sent=0,
        metrics_checked=[],
        metrics_with_changes=[],
        trigger=None,
        intent=None,
        error_class=None,
        client_platform=None,
        client_app_version=None,
        client_started_at=None,
        client_completed_at=None,
    )
    sql = fake.calls[0][0]
    assert "WHERE healthsave_sync_run_summaries.owner_id = EXCLUDED.owner_id" in sql
    # No row back = the conflict belonged to another owner; nothing was written.
    assert ack["recorded"] is False
    assert set(ack) == {"status", "sync_run_id", "recorded", "received_at", "updated_at"}


# ─── owner-scoped v2 reads ─────────────────────────────────────────────


class _ExportRepo:
    def __init__(self):
        self.owners: list[UUID] = []

    async def list_available_metrics(self, session, *, owner_id):
        self.owners.append(owner_id)
        return []


@pytest.fixture
def export_repo(monkeypatch):
    repo = _ExportRepo()
    monkeypatch.setattr(v2_export, "_EXPORT_REPO", repo)
    return repo


def test_admin_reads_the_default_owner_unless_it_names_one(session, export_repo) -> None:
    assert _client(LEGACY).get("/api/v2/export/metrics").status_code == 200
    assert _client(LEGACY).get(f"/api/v2/export/metrics?owner={ALICE}").status_code == 200
    assert export_repo.owners == [DEFAULT_OWNER_ID, ALICE]


def test_malformed_owner_is_a_deterministic_422(session, export_repo) -> None:
    assert _client(LEGACY).get("/api/v2/export/metrics?owner=not-a-uuid").status_code == 422
    assert export_repo.owners == []


def test_read_key_reads_its_own_owner_only(session, export_repo) -> None:
    client = _client("alice-read")
    assert client.get("/api/v2/export/metrics").status_code == 200
    assert client.get(f"/api/v2/export/metrics?owner={ALICE}").status_code == 200
    forbidden = client.get(f"/api/v2/export/metrics?owner={BOB}")
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"].startswith("owner_not_allowed")
    assert export_repo.owners == [ALICE, ALICE]


def test_ingest_key_cannot_read(session, export_repo) -> None:
    assert _client("alice-ingest").get("/api/v2/export/metrics").status_code == 403
    assert export_repo.owners == []


async def test_direct_calls_keep_the_default_owner(export_repo) -> None:
    await v2_export.list_export_metrics(session=object())
    assert export_repo.owners == [DEFAULT_OWNER_ID]


def test_every_owner_read_route_declares_the_owner_query() -> None:
    from server.api.access import OWNER_READ_ROUTES

    paths = app.openapi()["paths"]
    for method, path in sorted(OWNER_READ_ROUTES):
        params = paths[path][method.lower()].get("parameters", [])
        owner = [p for p in params if p["name"] == "owner" and p["in"] == "query"]
        assert owner and owner[0]["required"] is False, f"{method} {path}"


async def test_readiness_caches_each_owner_under_its_own_key() -> None:
    default_keys = [key for key, _ in v2_readiness._owner_loaders(DEFAULT_OWNER_ID)]
    alice_keys = [key for key, _ in v2_readiness._owner_loaders(ALICE)]
    assert default_keys == ["canonical_coverage", "canonical_sources"]
    assert alice_keys == [f"canonical_coverage:{ALICE}", f"canonical_sources:{ALICE}"]
    assert owner_cache_key("canonical_coverage", ALICE) == alice_keys[0]


async def test_readiness_reads_the_named_owner(monkeypatch) -> None:
    seen: list[UUID] = []

    async def _coverage(session, *, owner_id):
        seen.append(owner_id)
        return []

    async def _sources(session, *, owner_id):
        seen.append(owner_id)
        return []

    class _Ctx:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(v2_readiness, "async_session", lambda: _Ctx())
    monkeypatch.setattr(v2_readiness._READINESS_REPO, "fetch_canonical_coverage", _coverage)
    monkeypatch.setattr(v2_readiness._READINESS_REPO, "fetch_canonical_sources", _sources)
    v2_read_cache.clear()
    body = await v2_readiness.readiness(owner_id=ALICE)
    assert seen == [ALICE, ALICE]
    assert body["metrics"] == []


# ─── /api/v2/owners ────────────────────────────────────────────────────


def test_owners_lists_people_for_the_admin(session, monkeypatch) -> None:
    async def _owners(sess):
        return [
            {
                "id": str(DEFAULT_OWNER_ID),
                "label": None,
                "is_default": True,
                "active": True,
                "scopes": [],
                "created_at": None,
                "last_ingest_at": datetime(2026, 11, 2, tzinfo=UTC),
            },
            {
                "id": str(ALICE),
                "label": "Alice",
                "is_default": False,
                "active": True,
                "scopes": ["ingest"],
                "created_at": datetime(2026, 11, 1, tzinfo=UTC),
                "last_ingest_at": None,
            },
        ]

    monkeypatch.setattr(v2_owners, "list_owners", _owners)
    body = _client(LEGACY).get("/api/v2/owners").json()
    assert body["count"] == 2
    assert [owner["label"] for owner in body["owners"]] == [None, "Alice"]
    assert body["owners"][0]["is_default"] is True


@pytest.mark.parametrize("key", ["alice-ingest", "alice-read"])
def test_owners_is_admin_only(session, key) -> None:
    assert _client(key).get("/api/v2/owners").status_code == 403
