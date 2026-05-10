"""Multi-user / X-User-Id header behaviour."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402
from server.ingestion.owner import DEFAULT_OWNER_ID, OWNER_HEADER, resolve_owner_id  # noqa: E402
from tests.test_api_contract import FakeRequest, FakeSession  # noqa: E402

CUSTOM_OWNER = "11111111-2222-3333-4444-555555555555"


def test_resolve_owner_id_returns_sentinel_when_header_missing():
    assert resolve_owner_id(None) == DEFAULT_OWNER_ID
    assert resolve_owner_id("") == DEFAULT_OWNER_ID
    assert resolve_owner_id("   ") == DEFAULT_OWNER_ID


def test_resolve_owner_id_parses_valid_uuid():
    parsed = resolve_owner_id(CUSTOM_OWNER)
    assert str(parsed) == CUSTOM_OWNER


def test_resolve_owner_id_rejects_malformed_value():
    with pytest.raises(ValueError):
        resolve_owner_id("not-a-uuid")


@pytest.mark.asyncio
async def test_ingest_without_header_uses_sentinel_owner_id():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [
                {
                    "date": "2026-04-10T12:00:00+00:00",
                    "qty": 72,
                    "source": "Apple Watch",
                }
            ],
        }
    )

    result = await server.apple_batch(request, session)

    assert result["records"] == 1
    insert = session.insert_params_for("heart_rate")
    assert insert is not None
    assert insert["owner_id"] == str(DEFAULT_OWNER_ID)


@pytest.mark.asyncio
async def test_ingest_propagates_x_user_id_header_to_insert():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [
                {
                    "date": "2026-04-10T12:00:00+00:00",
                    "qty": 72,
                    "source": "Apple Watch",
                }
            ],
        },
        headers={OWNER_HEADER: CUSTOM_OWNER},
    )

    result = await server.apple_batch(request, session)

    assert result["records"] == 1
    insert = session.insert_params_for("heart_rate")
    assert insert is not None
    assert insert["owner_id"] == CUSTOM_OWNER
    # Same row must not also appear under the sentinel.
    assert str(DEFAULT_OWNER_ID) not in str(insert.get("owner_id"))


@pytest.mark.asyncio
async def test_ingest_propagates_owner_id_to_quantity_samples():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "made_up_metric",
            "samples": [
                {
                    "date": "2026-04-10T12:00:00+00:00",
                    "qty": 42,
                    "unit": "count",
                    "source": "Apple Watch",
                }
            ],
        },
        headers={OWNER_HEADER: CUSTOM_OWNER},
    )

    result = await server.apple_batch(request, session)

    assert result["records"] == 1
    insert = session.insert_params_for("quantity_samples")
    assert insert is not None
    assert insert["owner_id"] == CUSTOM_OWNER


@pytest.mark.asyncio
async def test_ingest_propagates_owner_id_to_daily_activity_quantity_metric():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "step_count",
            "samples": [
                {
                    "date": "2026-04-10T00:00:00Z",
                    "qty": 10000,
                    "source": "Apple Watch",
                }
            ],
        },
        headers={OWNER_HEADER: CUSTOM_OWNER},
    )

    result = await server.apple_batch(request, session)

    assert result["records"] == 1
    insert = session.insert_params_for("daily_activity")
    assert insert is not None
    assert insert["owner_id"] == CUSTOM_OWNER


@pytest.mark.asyncio
async def test_ingest_propagates_owner_id_to_workouts():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "workouts",
            "samples": [
                {
                    "start_date": "2026-04-10T07:00:00Z",
                    "end_date": "2026-04-10T07:30:00Z",
                    "duration": 1800,
                    "sport_type": "Running",
                    "source": "Apple Watch",
                }
            ],
        },
        headers={OWNER_HEADER: CUSTOM_OWNER},
    )

    result = await server.apple_batch(request, session)

    assert result["records"] == 1
    insert = session.insert_params_for("workouts")
    assert insert is not None
    assert insert["owner_id"] == CUSTOM_OWNER


@pytest.mark.asyncio
async def test_ingest_propagates_owner_id_to_sleep_stage_inserts():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "sleep_analysis",
            "samples": [
                {
                    "startDate": "2026-04-09T22:00:00Z",
                    "endDate": "2026-04-10T01:00:00Z",
                    "value": "deep",
                },
                {
                    "startDate": "2026-04-10T01:00:00Z",
                    "endDate": "2026-04-10T05:00:00Z",
                    "value": "light",
                },
            ],
        },
        headers={OWNER_HEADER: CUSTOM_OWNER},
    )

    result = await server.apple_batch(request, session)

    assert result["records"] == 1
    session_insert = session.insert_params_for("sleep_sessions")
    assert session_insert is not None
    assert session_insert["owner_id"] == CUSTOM_OWNER

    stage_inserts = session.all_insert_params_for("sleep_stages")
    assert stage_inserts
    assert all(insert["owner_id"] == CUSTOM_OWNER for insert in stage_inserts)


@pytest.mark.asyncio
async def test_ingest_rejects_malformed_x_user_id_header():
    from fastapi import HTTPException

    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "samples": [{"date": "2026-04-10T12:00:00Z", "qty": 72, "source": "Apple Watch"}],
        },
        headers={OWNER_HEADER: "definitely-not-a-uuid"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await server.apple_batch(request, session)

    assert exc_info.value.status_code == 400
    assert OWNER_HEADER in exc_info.value.detail


def test_schema_includes_owner_id_on_every_metric_table():
    schema = Path("schema.sql").read_text()

    expected_tables = [
        "heart_rate",
        "hrv",
        "blood_oxygen",
        "body_temperature",
        "daily_activity",
        "sleep_sessions",
        "sleep_stages",
        "workouts",
        "recovery",
        "stress",
        "quantity_samples",
    ]

    # Every metric table's CREATE statement must declare an owner_id column.
    for table in expected_tables:
        marker = f"CREATE TABLE {table}"
        start = schema.find(marker)
        assert start != -1, f"{table} missing from schema"
        body_end = schema.find(");", start)
        body = schema[start:body_end]
        assert "owner_id" in body, f"{table} missing owner_id column"


def test_migration_003_widens_unique_indexes_with_owner_id():
    migration = Path("migrations/003_multi_user.sql").read_text()

    assert "00000000-0000-0000-0000-000000000001" in migration
    assert "ALTER TABLE heart_rate" in migration
    assert "uq_heart_rate" in migration
    assert "ALTER TABLE quantity_samples" in migration
    assert "owner_id UUID NOT NULL" in migration
