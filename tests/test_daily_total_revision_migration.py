from pathlib import Path

from db.migrate import _migration_sql

MIGRATION = (
    Path(__file__).resolve().parents[1] / "db/migrations/024_apple_daily_total_revisions.sql"
)


def test_daily_total_revision_repair_is_scoped_idempotent_and_history_preserving() -> None:
    assert MIGRATION.exists(), "daily-total correction needs a tracked production repair"
    sql = MIGRATION.read_text()
    upper_sql = sql.upper()

    assert "registry_proven" in sql
    assert "raw_proven" in sql
    assert "raw_ingestion_log" in sql
    assert "raw.source_type = 'healthsave'" in sql
    assert "raw.endpoint = '/api/apple/batch'" in sql
    assert "jsonb_array_length" in sql
    assert "NOT EXISTS" in sql
    assert "expected_stream_id" in sql
    assert "9e1b7c34-5a2d-4f6e-8b0a-3c7d9f1e2a64" in sql
    assert "source_device_streams" in sql
    assert "origin_key = 'healthkit statistics'" in sql
    assert "normalizer_id = 'apple_health'" in sql
    assert "status = 'active'" in sql
    assert "ROW_NUMBER() OVER" in upper_sql
    assert "raw_payload_ref" in sql
    assert "apple_healthkit_daily_total" in sql
    assert "owner_all_source_day_total" in sql
    assert "exact_ingest_key" in sql
    assert "dedup_key" in sql
    assert "status = 'superseded'" in sql
    assert "stream_id = repair.expected_stream_id" in sql
    assert "pg_input_is_valid" in sql
    assert upper_sql.index("BEGIN;") < upper_sql.index("CREATE EXTENSION")
    assert "ADD COLUMN IF NOT EXISTS owner_id UUID" in sql
    assert "ADD COLUMN IF NOT EXISTS response_payload JSONB" in sql
    assert "uq_healthsave_sync_receipts_owner_batch_id" in sql
    assert "uq_healthsave_sync_receipts_owner_idempotency_key" in sql
    runner_sql = _migration_sql(MIGRATION)
    assert not runner_sql.startswith("BEGIN;")
    assert not runner_sql.endswith("COMMIT;")
    assert "DELETE" not in upper_sql
