"""PostgreSQL proofs for the daily-total repair and atomic receipt claims.

The normal unit suite only inspects migration text. This test executes migration
024 against isolated tables in the ephemeral E2E Postgres database. It also uses
independent transactions to prove same-key retries serialize before ingestion.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from contracts._base import Provenance
from normalization import identity, normalize_apple_batch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from storage.timescale import sync_receipts

DATABASE_URL = os.getenv("E2E_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "db/migrations/024_apple_daily_total_revisions.sql"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="set E2E_DATABASE_URL to run the migration proof (see `make e2e`)",
    ),
]

OWNER = UUID("00000000-0000-0000-0000-000000000001")
SECOND_OWNER = UUID("00000000-0000-0000-0000-000000000002")
WORKSPACE = UUID("00000000-0000-0000-0000-000000000001")
SOURCE = UUID("11111111-1111-1111-1111-111111111111")
DAY = datetime(2026, 8, 9, 4, tzinfo=UTC)
SECOND_DAY = datetime(2026, 8, 10, 4, tzinfo=UTC)
RETRY_DAY = datetime(2026, 8, 11, 4, tzinfo=UTC)
RECEIPT_METRIC = "step_count"
FROZEN_RESPONSE = {
    "status": "ok",
    "metric": RECEIPT_METRIC,
    "batch": 0,
    "total_batches": 1,
    "records": 1,
}

SCHEMA_SQL = """
CREATE TABLE canonical_observations (
    id UUID NOT NULL,
    owner_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    source_id UUID NOT NULL,
    metric_id TEXT NOT NULL,
    value_type TEXT NOT NULL,
    numeric_value DOUBLE PRECISION,
    interval_start TIMESTAMPTZ NOT NULL,
    device_id UUID,
    stream_id UUID,
    provenance JSONB NOT NULL,
    normalizer_id TEXT NOT NULL,
    status TEXT NOT NULL,
    aggregation_scope TEXT NOT NULL DEFAULT 'interval_component',
    exact_ingest_key TEXT,
    dedup_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX uq_canonical_obs_dedup
    ON canonical_observations (owner_id, workspace_id, dedup_key, interval_start);

CREATE TABLE sources (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    plugin_id TEXT NOT NULL,
    display_name TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, plugin_id)
);

CREATE TABLE source_device_streams (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    source_plugin_id TEXT NOT NULL,
    origin_key TEXT NOT NULL,
    device_label TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, source_plugin_id, origin_key)
);

CREATE TABLE raw_ingestion_log (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    endpoint TEXT,
    raw_payload JSONB NOT NULL,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE healthsave_sync_receipts (
    id BIGSERIAL PRIMARY KEY,
    sync_run_id TEXT,
    batch_id TEXT,
    idempotency_key TEXT,
    payload_hash TEXT,
    metric TEXT NOT NULL,
    batch_index INTEGER,
    total_batches INTEGER,
    sync_mode TEXT,
    anchor_present BOOLEAN,
    lower_bound_reason TEXT,
    full_export BOOLEAN,
    query_lower_bound_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    records_received INTEGER NOT NULL DEFAULT 0,
    records_accepted INTEGER NOT NULL DEFAULT 0,
    records_skipped INTEGER NOT NULL DEFAULT 0,
    records_inserted_new INTEGER,
    records_deduped_existing INTEGER,
    storage_result_level TEXT NOT NULL DEFAULT 'accepted_only',
    sample_min_at TIMESTAMPTZ,
    sample_max_at TIMESTAMPTZ,
    error_message TEXT,
    raw_log_id BIGINT REFERENCES raw_ingestion_log(id),
    source_endpoint TEXT NOT NULL DEFAULT '/api/apple/batch',
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT healthsave_sync_receipts_status_check
        CHECK (status IN ('processed', 'empty', 'failed'))
);

CREATE UNIQUE INDEX uq_healthsave_sync_receipts_batch_id
    ON healthsave_sync_receipts (batch_id)
    WHERE batch_id IS NOT NULL;
CREATE UNIQUE INDEX uq_healthsave_sync_receipts_idempotency_key
    ON healthsave_sync_receipts (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE modeled_ingest_writes (
    id BIGSERIAL PRIMARY KEY,
    claimant TEXT NOT NULL,
    payload_hash TEXT NOT NULL
);
"""


def _payload(
    value: float,
    source: str = "HealthKit Statistics",
    day: datetime = DAY,
) -> str:
    return json.dumps(
        {
            "metric": "distance_walking_running",
            "samples": [{"date": day.isoformat(), "qty": value, "source": source}],
        }
    )


async def _insert_observation(
    connection: asyncpg.Connection,
    *,
    row_id: UUID,
    owner_id: UUID,
    value: float,
    interval_start: datetime,
    stream_id: UUID | None,
    raw_ref: int | str | None,
    captured_at: datetime | str,
    created_at: datetime,
    dedup_key: str,
) -> None:
    provenance = {
        "source_plugin_id": "apple-healthkit-ios",
        "captured_at": (
            captured_at.isoformat() if isinstance(captured_at, datetime) else captured_at
        ),
        "raw_payload_ref": str(raw_ref) if raw_ref is not None else None,
    }
    await connection.execute(
        """
        INSERT INTO canonical_observations (
            id, owner_id, workspace_id, source_id, metric_id, value_type,
            numeric_value, interval_start, stream_id, provenance, normalizer_id,
            status, aggregation_scope, dedup_key, created_at
        ) VALUES (
            $1, $2, $3, $4, 'activity.distance_walking_running', 'quantity',
            $5, $6, $7, $8::jsonb, 'apple_health', 'active',
            'interval_component', $9, $10
        )
        """,
        row_id,
        owner_id,
        WORKSPACE,
        SOURCE,
        value,
        interval_start,
        stream_id,
        json.dumps(provenance),
        dedup_key,
        created_at,
    )


def _async_database_url() -> str:
    assert DATABASE_URL is not None
    if DATABASE_URL.startswith("postgresql://"):
        return DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    if DATABASE_URL.startswith("postgres://"):
        return DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    return DATABASE_URL


async def _create_migrated_test_schema(prefix: str) -> tuple[str, AsyncEngine]:
    assert DATABASE_URL is not None
    schema = f"{prefix}_{uuid4().hex}"
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        await connection.execute(f'SET search_path TO "{schema}", public')
        await connection.execute(SCHEMA_SQL)
        await connection.execute(MIGRATION.read_text())
    except Exception:
        await connection.execute("ROLLBACK")
        await connection.execute("SET search_path TO public")
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        raise
    finally:
        await connection.close()

    engine = create_async_engine(
        _async_database_url(),
        connect_args={"server_settings": {"search_path": f"{schema}, public"}},
    )
    return schema, engine


async def _drop_test_schema(schema: str, engine: AsyncEngine) -> None:
    assert DATABASE_URL is not None
    await engine.dispose()
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        await connection.close()


async def _claim_receipt(
    session: AsyncSession,
    *,
    payload_hash: str,
) -> dict[str, object] | None:
    return await sync_receipts.claim_receipt_idempotency(
        session,
        owner_id=OWNER,
        idempotency_key="issue18-concurrent-key",
        payload_hash=payload_hash,
        metric=RECEIPT_METRIC,
        batch_index=0,
        total_batches=1,
    )


async def _complete_receipt(
    session: AsyncSession,
    *,
    payload_hash: str,
    raw_log_id: int | None = None,
) -> None:
    await sync_receipts.complete_receipt_idempotency(
        session,
        owner_id=OWNER,
        idempotency_key="issue18-concurrent-key",
        payload_hash=payload_hash,
        status="processed",
        response_payload=FROZEN_RESPONSE,
        raw_log_id=raw_log_id,
        records_received=1,
        records_accepted=1,
        records_skipped=0,
        records_inserted_new=1,
        records_deduped_existing=0,
        storage_result_level="inserted_vs_existing",
        sample_min_at="2026-08-10T10:00:00Z",
        sample_max_at="2026-08-10T10:00:00Z",
    )


async def _record_failed_receipt(
    session: AsyncSession,
    *,
    payload_hash: str,
    raw_log_id: int | None = None,
    error_message: str = "late deterministic failure",
) -> None:
    await sync_receipts.record_sync_receipt(
        session,
        owner_id=OWNER,
        sync_run_id="issue18-failed-run",
        batch_id="issue18-failed-batch",
        idempotency_key="issue18-concurrent-key",
        payload_hash=payload_hash,
        metric=RECEIPT_METRIC,
        batch_index=0,
        total_batches=1,
        sync_mode="incremental",
        anchor_present=True,
        lower_bound_reason=None,
        full_export=False,
        query_lower_bound_at=None,
        status="failed",
        records_received=1,
        records_accepted=0,
        records_skipped=0,
        sample_min_at="2026-08-10T10:00:00Z",
        sample_max_at="2026-08-10T10:00:00Z",
        raw_log_id=raw_log_id,
        error_message=error_message,
    )


async def _record_failed_receipt_and_commit(
    session: AsyncSession,
    *,
    payload_hash: str,
) -> None:
    await _record_failed_receipt(session, payload_hash=payload_hash)
    await session.commit()


async def _claim_then_model_ingest(
    session: AsyncSession,
    *,
    claimant: str,
    payload_hash: str,
) -> tuple[str, dict[str, object] | None]:
    try:
        replay = await _claim_receipt(session, payload_hash=payload_hash)
    except sync_receipts.ReceiptIdempotencyConflict:
        await session.rollback()
        return "conflict", None

    if replay is None:
        await session.execute(
            text(
                """
                INSERT INTO modeled_ingest_writes (claimant, payload_hash)
                VALUES (:claimant, :payload_hash)
                """
            ),
            {"claimant": claimant, "payload_hash": payload_hash},
        )
        outcome = "claimed"
    else:
        outcome = "replayed"
    await session.commit()
    return outcome, replay


async def _wait_for_backend_lock(
    backend_pid: int,
    contender: asyncio.Task[object],
) -> None:
    """Wait until PostgreSQL, not Python scheduling, is holding the loser."""

    assert DATABASE_URL is not None
    observer = await asyncpg.connect(DATABASE_URL)
    deadline = asyncio.get_running_loop().time() + 5
    last_state: asyncpg.Record | None = None
    try:
        while asyncio.get_running_loop().time() < deadline:
            if contender.done():
                outcome = contender.result()
                raise AssertionError(
                    f"contender completed before the winning transaction committed: {outcome!r}"
                )
            last_state = await observer.fetchrow(
                """
                SELECT state, wait_event_type, wait_event, query
                FROM pg_stat_activity
                WHERE pid = $1
                """,
                backend_pid,
            )
            if (
                last_state is not None
                and last_state["wait_event_type"] == "Lock"
                and "healthsave_sync_receipts" in last_state["query"]
            ):
                return
            await asyncio.sleep(0.01)
    finally:
        await observer.close()

    raise AssertionError(f"contender never blocked on the receipt claim: {last_state!r}")


@pytest.mark.asyncio
async def test_daily_total_revision_migration_repairs_only_proven_rows() -> None:
    assert DATABASE_URL is not None
    schema = f"issue18_revision_{uuid4().hex}"
    connection = await asyncpg.connect(DATABASE_URL)
    expected_stream = identity.resolve_apple_origin(OWNER, "HealthKit Statistics").stream_id
    second_stream = identity.resolve_apple_origin(SECOND_OWNER, "HealthKit Statistics").stream_id

    try:
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        await connection.execute(f'SET search_path TO "{schema}", public')
        await connection.execute(SCHEMA_SQL)
        await connection.execute(
            """
            INSERT INTO healthsave_sync_receipts (
                batch_id, idempotency_key, payload_hash, metric, status
            ) VALUES (
                'legacy-batch', 'legacy-key', 'sha256:legacy',
                'distance_walking_running', 'processed'
            )
            """
        )

        raw_rows = [
            (1, _payload(7_100.0)),
            (2, _payload(7_698.1, "  healthkit   STATISTICS ")),
            (3, _payload(8_200.0)),
            (4, _payload(8_200.0, "Apple Watch")),
            (
                5,
                json.dumps(
                    {
                        "metric": "distance_walking_running",
                        "samples": [
                            {
                                "date": DAY.isoformat(),
                                "qty": 8_200,
                                "source": "HealthKit Statistics",
                            },
                            {"date": DAY.isoformat(), "qty": 10, "source": "Apple Watch"},
                        ],
                    }
                ),
            ),
            (
                6,
                json.dumps(
                    {
                        "metric": "distance_walking_running",
                        "samples": [
                            {
                                "date": SECOND_DAY.isoformat(),
                                "qty": 9_000,
                                "source": "HealthKit Statistics",
                            }
                        ],
                    }
                ),
            ),
            (7, _payload(7_100.0, day=RETRY_DAY)),
            (8, _payload(7_698.1, day=RETRY_DAY)),
            (9, _payload(7_100.0, day=RETRY_DAY)),
        ]
        await connection.executemany(
            """
            INSERT INTO raw_ingestion_log (id, source_type, endpoint, raw_payload)
            VALUES ($1, 'healthsave', '/api/apple/batch', $2::jsonb)
            """,
            raw_rows,
        )

        for index, (raw_ref, value) in enumerate(((1, 7_100.0), (2, 7_698.1), (3, 8_200.0))):
            await _insert_observation(
                connection,
                row_id=UUID(f"10000000-0000-0000-0000-00000000000{index + 1}"),
                owner_id=OWNER,
                value=value,
                interval_start=DAY,
                stream_id=None,
                raw_ref=raw_ref,
                captured_at=datetime(2026, 8, 9, 10 + index, tzinfo=UTC),
                created_at=datetime(2026, 8, 9, 10 + index, tzinfo=UTC),
                dedup_key=f"legacy-healthkit-{index}",
            )

        # Identical metric/time/value is not enough: Apple Watch and a mixed-origin
        # batch must remain untouched without unambiguous per-observation lineage.
        await _insert_observation(
            connection,
            row_id=UUID("20000000-0000-0000-0000-000000000001"),
            owner_id=OWNER,
            value=8_200,
            interval_start=DAY,
            stream_id=None,
            raw_ref=4,
            captured_at=datetime(2026, 8, 9, 13, tzinfo=UTC),
            created_at=datetime(2026, 8, 9, 13, tzinfo=UTC),
            dedup_key="apple-watch",
        )
        await _insert_observation(
            connection,
            row_id=UUID("20000000-0000-0000-0000-000000000002"),
            owner_id=OWNER,
            value=8_200,
            interval_start=DAY,
            stream_id=None,
            raw_ref=5,
            captured_at=datetime(2026, 8, 9, 14, tzinfo=UTC),
            created_at=datetime(2026, 8, 9, 14, tzinfo=UTC),
            dedup_key="mixed-origin",
        )

        # A deterministic stream may be present even when the fail-soft registry
        # upsert failed; raw proof must still repair it and restore the registry.
        await _insert_observation(
            connection,
            row_id=UUID("30000000-0000-0000-0000-000000000001"),
            owner_id=OWNER,
            value=9_000,
            interval_start=SECOND_DAY,
            stream_id=expected_stream,
            raw_ref=6,
            captured_at=datetime(2026, 8, 10, 10, tzinfo=UTC),
            created_at=datetime(2026, 8, 10, 10, tzinfo=UTC),
            dedup_key="unregistered-stream",
        )

        # Pre-stable-identity behavior updates A's value-dependent row in place
        # on an exact retry. Its raw/captured provenance therefore looks newer
        # than B even though immutable row creation proves A preceded B.
        await _insert_observation(
            connection,
            row_id=UUID("60000000-0000-0000-0000-000000000001"),
            owner_id=OWNER,
            value=7_100,
            interval_start=RETRY_DAY,
            stream_id=None,
            raw_ref=9,
            captured_at=datetime(2026, 8, 11, 15, tzinfo=UTC),
            created_at=datetime(2026, 8, 11, 10, tzinfo=UTC),
            dedup_key="retry-sequence-a",
        )
        await _insert_observation(
            connection,
            row_id=UUID("60000000-0000-0000-0000-000000000002"),
            owner_id=OWNER,
            value=7_698.1,
            interval_start=RETRY_DAY,
            stream_id=None,
            raw_ref=8,
            captured_at=datetime(2026, 8, 11, 11, tzinfo=UTC),
            created_at=datetime(2026, 8, 11, 11, tzinfo=UTC),
            dedup_key="retry-sequence-b",
        )

        # Registry-proven rows use immutable creation order even when mutable
        # provenance points the other way.
        await connection.execute(
            """
            INSERT INTO source_device_streams (
                id, owner_id, source_plugin_id, origin_key, device_label
            ) VALUES ($1, $2, 'apple-healthkit-ios', 'healthkit statistics',
                      'HealthKit Statistics')
            """,
            second_stream,
            SECOND_OWNER,
        )
        for row_id, value, captured_hour, created_hour, key, raw_ref in (
            (
                UUID("40000000-0000-0000-0000-000000000001"),
                100.0,
                13,
                14,
                "captured-old",
                "9" * 100,
            ),
            (
                UUID("40000000-0000-0000-0000-000000000002"),
                200.0,
                12,
                15,
                "captured-new",
                None,
            ),
        ):
            await _insert_observation(
                connection,
                row_id=row_id,
                owner_id=SECOND_OWNER,
                value=value,
                interval_start=DAY,
                stream_id=second_stream,
                raw_ref=raw_ref,
                captured_at=datetime(2026, 8, 9, captured_hour, tzinfo=UTC),
                created_at=datetime(2026, 8, 9, created_hour, tzinfo=UTC),
                dedup_key=key,
            )

        # When neither row has a valid raw id or captured timestamp, created_at
        # is the deterministic fallback. Malformed provenance must never abort
        # the migration.
        for row_id, value, created_hour, key, raw_ref, captured_at in (
            (
                UUID("50000000-0000-0000-0000-000000000001"),
                300.0,
                11,
                "fallback-old",
                "not-a-bigint",
                "not-a-timestamp",
            ),
            (
                UUID("50000000-0000-0000-0000-000000000002"),
                400.0,
                12,
                "fallback-new",
                "9" * 100,
                "still-not-a-timestamp",
            ),
        ):
            await _insert_observation(
                connection,
                row_id=row_id,
                owner_id=SECOND_OWNER,
                value=value,
                interval_start=SECOND_DAY,
                stream_id=second_stream,
                raw_ref=raw_ref,
                captured_at=captured_at,
                created_at=datetime(2026, 8, 10, created_hour, tzinfo=UTC),
                dedup_key=key,
            )

        migration_sql = MIGRATION.read_text()
        await connection.execute(migration_sql)
        await connection.executemany(
            """
            INSERT INTO healthsave_sync_receipts (
                owner_id, batch_id, idempotency_key, payload_hash, metric, status
            ) VALUES (
                $1, 'shared-batch', 'shared-key', 'sha256:same',
                'distance_walking_running', 'processed'
            )
            """,
            [(OWNER,), (SECOND_OWNER,)],
        )

        repaired = await connection.fetch(
            """
            SELECT numeric_value, status, stream_id, exact_ingest_key, dedup_key
            FROM canonical_observations
            WHERE owner_id = $1 AND dedup_key <> ALL($2::text[])
              AND interval_start = $3
            ORDER BY numeric_value
            """,
            OWNER,
            ["apple-watch", "mixed-origin"],
            DAY,
        )
        assert [row["status"] for row in repaired] == ["superseded", "superseded", "active"]
        assert {row["stream_id"] for row in repaired} == {expected_stream}
        assert len({row["exact_ingest_key"] for row in repaired}) == 1

        expected = normalize_apple_batch(
            {
                "metric": "distance_walking_running",
                "samples": [
                    {"date": DAY.isoformat(), "qty": 8_200, "source": "HealthKit Statistics"}
                ],
            },
            source_id=SOURCE,
            provenance=Provenance(
                source_plugin_id="apple-healthkit-ios",
                sdk_version="test",
                captured_at=datetime(2026, 8, 9, 12, tzinfo=UTC),
                raw_payload_ref="3",
            ),
            owner_id=OWNER,
            workspace_id=WORKSPACE,
        ).observations[0]
        active = repaired[-1]
        assert active["numeric_value"] == 8_200
        assert active["exact_ingest_key"] == expected.exact_ingest_key
        assert active["dedup_key"] == expected.dedup_key

        untouched = await connection.fetch(
            """
            SELECT dedup_key, aggregation_scope, stream_id, exact_ingest_key
            FROM canonical_observations
            WHERE dedup_key = ANY($1::text[])
            ORDER BY dedup_key
            """,
            ["apple-watch", "mixed-origin"],
        )
        assert [row["dedup_key"] for row in untouched] == ["apple-watch", "mixed-origin"]
        assert all(row["aggregation_scope"] == "interval_component" for row in untouched)
        assert all(row["stream_id"] is None for row in untouched)
        assert all(row["exact_ingest_key"] is None for row in untouched)

        captured_winner = await connection.fetchrow(
            """
            SELECT numeric_value FROM canonical_observations
            WHERE owner_id = $1 AND interval_start = $2 AND status = 'active'
            """,
            SECOND_OWNER,
            DAY,
        )
        assert captured_winner["numeric_value"] == 200

        fallback_winner = await connection.fetchrow(
            """
            SELECT numeric_value FROM canonical_observations
            WHERE owner_id = $1 AND interval_start = $2 AND status = 'active'
            """,
            SECOND_OWNER,
            SECOND_DAY,
        )
        assert fallback_winner["numeric_value"] == 400

        retry_winner = await connection.fetchrow(
            """
            SELECT numeric_value FROM canonical_observations
            WHERE owner_id = $1 AND interval_start = $2 AND status = 'active'
            """,
            OWNER,
            RETRY_DAY,
        )
        assert retry_winner["numeric_value"] == pytest.approx(7_698.1)

        legacy_receipt = await connection.fetchrow(
            """
            SELECT owner_id, response_payload
            FROM healthsave_sync_receipts
            WHERE idempotency_key = 'legacy-key'
            """
        )
        assert legacy_receipt["owner_id"] is None
        assert legacy_receipt["response_payload"] is None

        assert (
            await connection.fetchval(
                """
            SELECT count(*) FROM source_device_streams
            WHERE owner_id = $1 AND id = $2 AND origin_key = 'healthkit statistics'
            """,
                OWNER,
                expected_stream,
            )
            == 1
        )

        snapshot_before = await connection.fetch(
            """
            SELECT id, status, aggregation_scope, stream_id, exact_ingest_key, dedup_key
            FROM canonical_observations ORDER BY id
            """
        )
        await connection.execute(migration_sql)
        snapshot_after = await connection.fetch(
            """
            SELECT id, status, aggregation_scope, stream_id, exact_ingest_key, dedup_key
            FROM canonical_observations ORDER BY id
            """
        )
        assert snapshot_after == snapshot_before
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM healthsave_sync_receipts WHERE idempotency_key = 'shared-key'"
            )
            == 2
        )
        assert (
            await connection.fetchval(
                """
                SELECT count(*) FROM healthsave_sync_receipts
                WHERE idempotency_key = 'legacy-key'
                  AND owner_id IS NULL
                  AND response_payload IS NULL
                """
            )
            == 1
        )
    finally:
        await connection.execute("SET search_path TO public")
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()


@pytest.mark.asyncio
async def test_concurrent_exact_retries_have_one_claim_and_one_frozen_replay() -> None:
    schema, engine = await _create_migrated_test_schema("issue18_same_hash")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    payload_hash = "sha256:exact-retry"

    try:
        async with session_factory() as winner, session_factory() as contender:
            assert await _claim_receipt(winner, payload_hash=payload_hash) is None
            winner_pid = await winner.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(winner_pid, int)
            await winner.execute(
                text(
                    """
                    INSERT INTO modeled_ingest_writes (claimant, payload_hash)
                    VALUES ('winner', :payload_hash)
                    """
                ),
                {"payload_hash": payload_hash},
            )

            contender_pid = await contender.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(contender_pid, int)
            assert contender_pid != winner_pid
            contender_task = asyncio.create_task(
                _claim_then_model_ingest(
                    contender,
                    claimant="exact-retry",
                    payload_hash=payload_hash,
                )
            )
            try:
                await _wait_for_backend_lock(contender_pid, contender_task)
                await _complete_receipt(winner, payload_hash=payload_hash)
                await winner.commit()
                outcome, replay = await asyncio.wait_for(contender_task, timeout=5)
            finally:
                if not contender_task.done():
                    contender_task.cancel()
                    await asyncio.gather(contender_task, return_exceptions=True)

            assert outcome == "replayed"
            assert replay == FROZEN_RESPONSE

        async with session_factory() as verifier:
            receipt = (
                (
                    await verifier.execute(
                        text(
                            """
                        SELECT status, payload_hash, response_payload
                        FROM healthsave_sync_receipts
                        WHERE owner_id = CAST(:owner_id AS UUID)
                          AND idempotency_key = 'issue18-concurrent-key'
                        """
                        ),
                        {"owner_id": str(OWNER)},
                    )
                )
                .mappings()
                .one()
            )
            modeled_writes = await verifier.scalar(
                text("SELECT count(*) FROM modeled_ingest_writes")
            )

        assert receipt["status"] == "processed"
        assert receipt["payload_hash"] == payload_hash
        assert receipt["response_payload"] == FROZEN_RESPONSE
        assert modeled_writes == 1
    finally:
        await _drop_test_schema(schema, engine)


@pytest.mark.asyncio
async def test_concurrent_different_hash_conflicts_before_loser_ingest() -> None:
    schema, engine = await _create_migrated_test_schema("issue18_different_hash")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    winning_hash = "sha256:payload-a"
    losing_hash = "sha256:payload-b"

    try:
        async with session_factory() as winner, session_factory() as contender:
            assert await _claim_receipt(winner, payload_hash=winning_hash) is None
            winner_pid = await winner.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(winner_pid, int)
            await winner.execute(
                text(
                    """
                    INSERT INTO modeled_ingest_writes (claimant, payload_hash)
                    VALUES ('winner', :payload_hash)
                    """
                ),
                {"payload_hash": winning_hash},
            )

            contender_pid = await contender.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(contender_pid, int)
            assert contender_pid != winner_pid
            contender_task = asyncio.create_task(
                _claim_then_model_ingest(
                    contender,
                    claimant="different-hash-loser",
                    payload_hash=losing_hash,
                )
            )
            try:
                await _wait_for_backend_lock(contender_pid, contender_task)
                await _complete_receipt(winner, payload_hash=winning_hash)
                await winner.commit()
                outcome, replay = await asyncio.wait_for(contender_task, timeout=5)
            finally:
                if not contender_task.done():
                    contender_task.cancel()
                    await asyncio.gather(contender_task, return_exceptions=True)

            assert outcome == "conflict"
            assert replay is None

        async with session_factory() as verifier:
            receipt = (
                (
                    await verifier.execute(
                        text(
                            """
                        SELECT status, payload_hash, response_payload
                        FROM healthsave_sync_receipts
                        WHERE owner_id = CAST(:owner_id AS UUID)
                          AND idempotency_key = 'issue18-concurrent-key'
                        """
                        ),
                        {"owner_id": str(OWNER)},
                    )
                )
                .mappings()
                .one()
            )
            modeled_writes = (
                (
                    await verifier.execute(
                        text(
                            """
                        SELECT claimant, payload_hash
                        FROM modeled_ingest_writes
                        ORDER BY id
                        """
                        )
                    )
                )
                .mappings()
                .all()
            )

        assert receipt["status"] == "processed"
        assert receipt["payload_hash"] == winning_hash
        assert receipt["response_payload"] == FROZEN_RESPONSE
        assert [dict(row) for row in modeled_writes] == [
            {"claimant": "winner", "payload_hash": winning_hash}
        ]
    finally:
        await _drop_test_schema(schema, engine)


@pytest.mark.asyncio
async def test_late_failed_writer_cannot_overwrite_completed_claim() -> None:
    schema, engine = await _create_migrated_test_schema("issue18_late_failure")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    payload_hash = "sha256:late-failure"

    try:
        async with session_factory() as winner, session_factory() as late_writer:
            assert await _claim_receipt(winner, payload_hash=payload_hash) is None
            winner_pid = await winner.scalar(text("SELECT pg_backend_pid()"))
            late_writer_pid = await late_writer.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(winner_pid, int)
            assert isinstance(late_writer_pid, int)
            assert late_writer_pid != winner_pid

            late_writer_task = asyncio.create_task(
                _record_failed_receipt_and_commit(
                    late_writer,
                    payload_hash=payload_hash,
                )
            )
            try:
                await _wait_for_backend_lock(late_writer_pid, late_writer_task)
                await _complete_receipt(winner, payload_hash=payload_hash)
                await winner.commit()
                await asyncio.wait_for(late_writer_task, timeout=5)
            finally:
                if not late_writer_task.done():
                    late_writer_task.cancel()
                    await asyncio.gather(late_writer_task, return_exceptions=True)

        async with session_factory() as verifier:
            receipt = (
                (
                    await verifier.execute(
                        text(
                            """
                        SELECT
                            status,
                            payload_hash,
                            response_payload,
                            records_accepted,
                            error_message,
                            completed_at
                        FROM healthsave_sync_receipts
                        WHERE owner_id = CAST(:owner_id AS UUID)
                          AND idempotency_key = 'issue18-concurrent-key'
                        """
                        ),
                        {"owner_id": str(OWNER)},
                    )
                )
                .mappings()
                .one()
            )

        assert receipt["status"] == "processed"
        assert receipt["payload_hash"] == payload_hash
        assert receipt["response_payload"] == FROZEN_RESPONSE
        assert receipt["records_accepted"] == 1
        assert receipt["error_message"] is None
        assert receipt["completed_at"] is not None
    finally:
        await _drop_test_schema(schema, engine)


@pytest.mark.asyncio
async def test_rolled_back_raw_audit_is_repersisted_with_a_valid_failed_receipt_fk() -> None:
    schema, engine = await _create_migrated_test_schema("issue18_raw_audit")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    payload_hash = "sha256:deterministic-failure"
    raw_payload = json.dumps(
        {
            "metric": RECEIPT_METRIC,
            "samples": [{"date": "2026-08-10T10:00:00Z", "qty": 1_234}],
        }
    )

    try:
        async with session_factory() as failed_ingest:
            assert await _claim_receipt(failed_ingest, payload_hash=payload_hash) is None
            await failed_ingest.execute(
                text(
                    """
                    INSERT INTO raw_ingestion_log (
                        source_type, endpoint, raw_payload, processed
                    ) VALUES (
                        'healthsave', '/api/apple/batch', CAST(:raw_payload AS JSONB), FALSE
                    )
                    """
                ),
                {"raw_payload": raw_payload},
            )
            await failed_ingest.execute(
                text(
                    """
                    INSERT INTO modeled_ingest_writes (claimant, payload_hash)
                    VALUES ('rolled-back-data', :payload_hash)
                    """
                ),
                {"payload_hash": payload_hash},
            )
            await failed_ingest.rollback()

        async with session_factory() as rollback_verifier:
            assert (
                await rollback_verifier.scalar(
                    text("SELECT count(*) FROM healthsave_sync_receipts")
                )
                == 0
            )
            assert (
                await rollback_verifier.scalar(text("SELECT count(*) FROM raw_ingestion_log")) == 0
            )
            assert (
                await rollback_verifier.scalar(text("SELECT count(*) FROM modeled_ingest_writes"))
                == 0
            )

        async with session_factory() as evidence_writer:
            raw_log_id = await evidence_writer.scalar(
                text(
                    """
                    INSERT INTO raw_ingestion_log (
                        source_type, endpoint, raw_payload, processed
                    ) VALUES (
                        'healthsave', '/api/apple/batch', CAST(:raw_payload AS JSONB), FALSE
                    )
                    RETURNING id
                    """
                ),
                {"raw_payload": raw_payload},
            )
            assert isinstance(raw_log_id, int)
            await _record_failed_receipt(
                evidence_writer,
                payload_hash=payload_hash,
                raw_log_id=raw_log_id,
                error_message="deterministic modeled failure",
            )
            await evidence_writer.commit()

        async with session_factory() as verifier:
            evidence = (
                (
                    await verifier.execute(
                        text(
                            """
                        SELECT
                            receipt.status,
                            receipt.raw_log_id,
                            raw.processed,
                            raw.raw_payload
                        FROM healthsave_sync_receipts AS receipt
                        JOIN raw_ingestion_log AS raw ON raw.id = receipt.raw_log_id
                        WHERE receipt.owner_id = CAST(:owner_id AS UUID)
                          AND receipt.idempotency_key = 'issue18-concurrent-key'
                        """
                        ),
                        {"owner_id": str(OWNER)},
                    )
                )
                .mappings()
                .one()
            )

        assert evidence["status"] == "failed"
        assert evidence["raw_log_id"] == raw_log_id
        assert evidence["processed"] is False
        assert evidence["raw_payload"] == json.loads(raw_payload)
    finally:
        await _drop_test_schema(schema, engine)
