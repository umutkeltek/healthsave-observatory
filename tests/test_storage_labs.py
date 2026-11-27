"""Unit tests for the lab_results repository (no database; fake session)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from storage.timescale.labs import LabResultWrite, TimescaleLabRepository

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db/migrations/028_lab_results.sql"
STREAM = UUID("11111111-1111-1111-1111-111111111111")
SOURCE = UUID("22222222-2222-2222-2222-222222222222")


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = list(rows or [])

    def first(self):
        return self._row

    def fetchall(self):
        return self._rows


class _Session:
    """Records every statement; answers upserts from a scripted outcome list."""

    def __init__(self, upsert_outcomes=(), list_rows=()):
        self.calls: list[tuple[str, dict]] = []
        self._outcomes = list(upsert_outcomes)
        self._list_rows = list(list_rows)

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if sql.startswith("INSERT INTO lab_results"):
            outcome = self._outcomes.pop(0)
            return _Result(row=None if outcome is None else SimpleNamespace(inserted=outcome))
        if sql.startswith("SELECT") and "FROM lab_results" in sql:
            return _Result(rows=self._list_rows)
        return _Result()


def _write(**over) -> LabResultWrite:
    base = {
        "id": uuid4(),
        "metric_id": "loinc:2276-4",
        "loinc_code": "2276-4",
        "marker_name": "Ferritin",
        "numeric_value": 41.0,
        "value_comparator": None,
        "canonical_unit": "ng/mL",
        "reference_low": 30.0,
        "reference_high": 400.0,
        "reference_text": "30-400",
        "specimen_at": datetime(2026, 3, 12, 8, 30, tzinfo=UTC),
        "lab_name": "Northfield Lab",
        "panel": "Iron studies",
        "source_id": SOURCE,
        "source_plugin_id": "labs-csv",
        "stream_id": STREAM,
        "dedup_key": "k1",
        "semantic_key": "s1",
        "normalizer_id": "labs-csv",
        "normalizer_version": "1",
        "quality_flags": ("date_only",),
        "provenance": {"row": 2, "file_sha256": "abc"},
    }
    base.update(over)
    return LabResultWrite(**base)


def _db_row(**over):
    base = {
        "id": uuid4(),
        "metric_id": "loinc:2276-4",
        "loinc_code": "2276-4",
        "marker_name": "Ferritin",
        "numeric_value": 41,
        "value_comparator": None,
        "canonical_unit": "ng/mL",
        "reference_low": 30,
        "reference_high": 400,
        "reference_text": "30-400",
        "specimen_at": datetime(2026, 3, 12, 8, 30, tzinfo=UTC),
        "lab_name": "Northfield Lab",
        "panel": None,
        "source_plugin_id": "labs-csv",
        "stream_id": str(STREAM),
        "quality_flags": ["date_only"],
    }
    base.update(over)
    return SimpleNamespace(**base)


async def test_import_registers_source_and_streams_before_upserting() -> None:
    session = _Session(upsert_outcomes=[True])
    await TimescaleLabRepository().import_results(session, [_write()], plugin_id="labs-csv")

    sqls = [sql for sql, _ in session.calls]
    assert sqls[0].startswith("INSERT INTO sources")
    assert sqls[1].startswith("INSERT INTO source_device_streams")
    assert sqls[2].startswith("INSERT INTO lab_results")
    assert session.calls[0][1]["plugin_id"] == "labs-csv"
    assert session.calls[1][1]["device_label"] == "Northfield Lab"


async def test_import_counts_inserted_updated_and_unchanged() -> None:
    # True = fresh insert, False = changed row updated, None = identical row (no-op).
    session = _Session(upsert_outcomes=[True, False, None])
    summary = await TimescaleLabRepository().import_results(
        session,
        [_write(dedup_key="a"), _write(dedup_key="b"), _write(dedup_key="c")],
        plugin_id="labs-csv",
    )
    assert (summary.inserted, summary.updated, summary.unchanged) == (1, 1, 1)
    assert summary.streams == 1


async def test_import_of_nothing_touches_nothing() -> None:
    session = _Session()
    summary = await TimescaleLabRepository().import_results(session, [], plugin_id="labs-csv")
    assert summary.inserted == summary.updated == summary.unchanged == 0
    assert session.calls == []


async def test_upsert_is_idempotent_on_dedup_key_and_skips_identical_rows() -> None:
    session = _Session(upsert_outcomes=[True])
    await TimescaleLabRepository().import_results(session, [_write()], plugin_id="labs-csv")
    sql, params = session.calls[-1]

    assert "ON CONFLICT (owner_id, workspace_id, dedup_key) DO UPDATE" in sql
    assert "IS DISTINCT FROM" in sql
    assert "RETURNING (xmax = 0) AS inserted" in sql
    assert params["stream_id"] == str(STREAM)
    assert params["source_id"] == str(SOURCE)
    assert params["quality_flags"] == ["date_only"]
    assert json.loads(params["provenance"]) == {"file_sha256": "abc", "row": 2}
    assert params["owner_id"] == "00000000-0000-0000-0000-000000000001"


async def test_list_results_reads_active_rows_typed_and_ordered() -> None:
    session = _Session(list_rows=[_db_row(), _db_row(numeric_value=22.5, reference_low=None)])
    rows = await TimescaleLabRepository().list_results(session, loinc_code="2276-4")

    sql, params = session.calls[0]
    assert "status = 'active'" in sql
    assert "ORDER BY loinc_code, interval_start, lab_name" in sql
    assert params["loinc_code"] == "2276-4"
    assert rows[0].stream_id == STREAM
    assert rows[1].numeric_value == 22.5
    assert rows[1].reference_low is None
    assert rows[0].quality_flags == ("date_only",)


def test_migration_is_additive_and_idempotent() -> None:
    sql = MIGRATION.read_text()
    upper = sql.upper()
    assert "CREATE TABLE IF NOT EXISTS LAB_RESULTS" in upper
    for forbidden in ("DROP ", "ALTER TABLE", "RENAME", "DELETE ", "TRUNCATE"):
        assert forbidden not in upper, forbidden
    assert "UNIQUE (OWNER_ID, WORKSPACE_ID, DEDUP_KEY)" in upper
    assert upper.count("CREATE INDEX IF NOT EXISTS") == 2
