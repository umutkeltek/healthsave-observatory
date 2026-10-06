"""Black-box psql proof for the bounded, null-only activity-summary repair.

Run against a disposable PostgreSQL container with
``ACTIVITY_REPAIR_TEST_CONTAINER=<name> pytest -q <this file>``.
The script runs unchanged through psql; these tests never target live data.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

CONTAINER = os.getenv("ACTIVITY_REPAIR_TEST_CONTAINER")
REPAIR = (
    Path(__file__).resolve().parents[2]
    / "packages/py/storage/timescale/activity_summary_repair.sql"
)
OWNER = "00000000-0000-0000-0000-000000000001"
OTHER_OWNER = "00000000-0000-0000-0000-000000000002"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not CONTAINER, reason="set ACTIVITY_REPAIR_TEST_CONTAINER to a test DB"),
]


def _psql(sql: str, **variables: object) -> str:
    command = [
        "docker",
        "exec",
        "-i",
        str(CONTAINER),
        "psql",
        "-X",
        "-q",
        "-t",
        "-A",
        "-U",
        "healthsave",
        "-d",
        "healthsave",
        "-v",
        "ON_ERROR_STOP=1",
    ]
    for key, value in variables.items():
        command.extend(["-v", f"{key}={value}"])
    result = subprocess.run(command, input=sql, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def schema():
    name = "summary_repair_" + uuid4().hex
    _psql(
        f"CREATE SCHEMA {name}; SET search_path TO {name};"
        + """
        CREATE TABLE daily_activity (
            date DATE, device_id INT, owner_id UUID, steps INT, distance_m FLOAT,
            floors_climbed INT, active_calories FLOAT, total_calories FLOAT,
            active_minutes INT, stand_hours INT, avg_hr FLOAT, max_hr FLOAT,
            source_id TEXT, PRIMARY KEY (date, device_id, owner_id)
        );
        CREATE TABLE raw_ingestion_log (
            id BIGINT, device_id INT, source_type TEXT, ingested_at TIMESTAMPTZ,
            raw_payload JSONB, processed BOOLEAN
        );
        CREATE TABLE healthsave_sync_receipts (owner_id UUID, raw_log_id BIGINT, status TEXT);
    """
    )
    _psql(
        f"SET search_path TO {name};"
        + f"""
        INSERT INTO daily_activity VALUES
        ('2026-09-07', 1, '{OWNER}', 5000, 4100, 3, NULL, 1800, NULL, 8, 65, 155, 'keep'),
        ('2026-09-07', 1, '{OTHER_OWNER}', 6000, 4500, 4, 990, 1900, 19, 12, 66, 156, 'other'),
        ('2026-09-08', 1, '{OWNER}', 7000, 4900, 5, NULL, 2000, NULL, 9, 67, 157, 'later');
    """
    )
    cases = [
        (1, OWNER, "processed", True, "2026-09-07", 100, 9),
        (2, OWNER, "processed", True, "2026-09-07", 0, 0),
        (3, OWNER, "failed", True, "2026-09-07", 333, 33),
        (4, OTHER_OWNER, "processed", True, "2026-09-07", 444, 44),
        (5, OWNER, "processed", False, "2026-09-07", 555, 55),
        (6, OWNER, "processed", True, "2026-09-08", 666, 66),
    ]
    for raw_id, owner, status, processed, day, energy, exercise in cases:
        payload = json.dumps(
            {
                "metric": "activity_summaries",
                "samples": [
                    {
                        "date": day + "T00:00:00Z",
                        "activeEnergyBurned": energy,
                        "appleExerciseTime": exercise,
                        "appleStandHours": 2,
                    }
                ],
            }
        ).replace("'", "''")
        _psql(
            f"SET search_path TO {name};"
            + f"""
            INSERT INTO raw_ingestion_log VALUES
            ({raw_id}, 1, 'healthsave', '2026-10-01T00:00:00Z', '{payload}', {str(processed)});
            INSERT INTO healthsave_sync_receipts VALUES ('{owner}', {raw_id}, '{status}');
        """
        )
    try:
        yield name
    finally:
        _psql(f"DROP SCHEMA {name} CASCADE;")


def _run_repair(schema: str, *, apply: bool | None = None, through_raw_id: int = 6) -> dict:
    variables = {
        "owner_id": OWNER,
        "start_date": "2026-09-07",
        "end_date": "2026-09-07",
        "through_raw_id": through_raw_id,
    }
    if apply is not None:
        variables["apply"] = str(apply).lower()
    result = _psql(
        f"SET search_path TO {schema};\n" + REPAIR.read_text(encoding="utf-8"),
        **variables,
    )
    return json.loads(result)


def _daily_rows(schema: str) -> list[dict]:
    return json.loads(
        _psql(f"""
        SET search_path TO {schema};
        SELECT json_agg(rows) FROM
        (SELECT * FROM daily_activity ORDER BY date, owner_id) rows;
    """)
    )


def test_preview_reports_missing_fields_without_writing(schema):
    before = _daily_rows(schema)

    result = _run_repair(schema)

    assert result["mode"] == "dry_run"
    assert result["rows_to_repair"] == 1
    assert result["active_calories_to_fill"] == 1
    assert result["active_minutes_to_fill"] == 1
    assert result["stand_hours_to_fill"] == 0
    assert result["newest_source_raw_id"] == 2
    assert _daily_rows(schema) == before


def test_repair_uses_latest_processed_raw_and_preserves_existing_fields(schema):
    before = _daily_rows(schema)

    result = _run_repair(schema, apply=True)
    after = _daily_rows(schema)

    assert result == {"mode": "apply", "rows_updated": 1}
    assert after[0] == {**before[0], "active_calories": 0, "active_minutes": 0}
    assert after[1:] == before[1:]
    assert _run_repair(schema, apply=True)["rows_updated"] == 0


def test_repair_stops_at_the_reviewed_raw_log_snapshot(schema):
    before = _daily_rows(schema)

    _run_repair(schema, apply=True, through_raw_id=1)

    assert _daily_rows(schema)[0] == {
        **before[0],
        "active_calories": 100,
        "active_minutes": 9,
    }
