"""Regenerate the golden HealthSave iOS *response* corpus.

The request direction of the iOS wire contract is pinned by
``tests/fixtures/apple_healthsave/`` (what the app sends). This script
pins the *response* direction: what the server's real handlers return
for the five endpoints the shipped iOS binary calls. The fixtures are
mirrored byte-for-byte into
``ios_app/Tests/HealthSyncTests/Fixtures/Responses/`` where
``BackendResponseCorpusTests.swift`` decodes them through the app's
real parsing paths.

Drift chain: a handler change fails ``--check`` in datahub CI → regen
here → ``tests/contract/test_ios_response_corpus_in_sync.py`` stays red
until the iOS mirror is updated → the iOS decode tests fail if the new
shape actually breaks the app.

Every response is produced by calling the real route handler functions
in-process with fixed inputs (constant idempotency/run/batch IDs and
sample windows) against a deterministic fake DB session, so the output
is reproducible on any machine. The only normalization applied is
dropping pydantic's version-volatile ``url`` field from 422 error
bodies; anything scrubbed is by definition not contract.

Each fixture is an envelope::

    {"endpoint": "...", "method": "GET|POST", "status": 200, "body": {...}}

Usage:
    python -m scripts.generate_ios_response_corpus          # writes fixtures
    python -m scripts.generate_ios_response_corpus --check  # exits 1 on drift
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "py"))

from fastapi import HTTPException  # noqa: E402
from fastapi.encoders import jsonable_encoder  # noqa: E402

REQUEST_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "apple_healthsave"
OUT_DIR = REPO_ROOT / "tests" / "fixtures" / "apple_healthsave_responses"

# Fixed wire identifiers so receipt echoes are reproducible.
CORPUS_SYNC_RUN_ID = "corpus-run-001"
# A second run that checked everything and sent NOTHING — known to the server
# only through its closing summary (PUT /api/v2/sync/runs/{id}/summary).
CORPUS_ZERO_DELIVERY_RUN_ID = "corpus-run-002"
CORPUS_SUMMARY_RECEIVED_AT = "2026-01-01T06:20:05+00:00"
CORPUS_SAMPLE_MIN = "2026-01-01T00:00:00.000Z"
CORPUS_SAMPLE_MAX = "2026-01-01T06:00:00.000Z"


class _FakeResult:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows if rows is not None else ([] if row is None else [row])

    def fetchone(self):
        return self.row

    def first(self):
        return self.row

    def all(self):
        return self.rows

    def fetchall(self):
        return self.rows

    def mappings(self):
        return self

    def scalar(self):
        return 1


# /api/apple/coverage scenario: what a sync on 2026-09-14 in Berlin (+02:00) leaves behind.
# HRV measured at 14:08:00.503 local (12:08Z); the day's step total starts at local
# midnight (22:00Z the day before).
_COVERAGE_LEGACY_LATEST: dict[str, Any] = {
    "heart_rate": datetime(2026, 9, 14, 12, 6, tzinfo=UTC),
    "hrv": datetime(2026, 9, 14, 12, 8, 0, 503000, tzinfo=UTC),
    "daily_activity": "2026-09-14",
    "sleep_sessions": datetime(2026, 9, 13, 21, 40, tzinfo=UTC),
    "quantity_samples": datetime(2026, 9, 14, 12, 10, tzinfo=UTC),
}
_COVERAGE_CANONICAL_ROWS: list[Any] = [
    SimpleNamespace(
        metric_id="vital.hrv_sdnn",
        observation_count=121,
        days_with_data=9,
        first_at=datetime(2026, 9, 6, 7, 0, tzinfo=UTC),
        last_at=datetime(2026, 9, 14, 12, 8, 0, 503000, tzinfo=UTC),
        last_ingested_at=datetime(2026, 9, 14, 12, 16, tzinfo=UTC),
    ),
    SimpleNamespace(
        metric_id="activity.steps",
        observation_count=9,
        days_with_data=9,
        first_at=datetime(2026, 9, 5, 22, 0, tzinfo=UTC),
        last_at=datetime(2026, 9, 13, 22, 0, tzinfo=UTC),
        last_ingested_at=datetime(2026, 9, 14, 12, 16, tzinfo=UTC),
    ),
]


class CorpusSession:
    """Deterministic stand-in for the DB session.

    Ingest INSERTs are accepted and discarded (same behavior the unit
    suite's FakeSession relies on); the receipt SELECTs used by the
    sync-run endpoints return the canned rows configured per scenario.
    NOTE: row keys for the sync-run queries mirror the SQL aliases in
    ``storage/timescale/sync_receipts.py``; those aliases are pinned by
    ``tests/contract/test_ios_v2_surface.py``.
    """

    def __init__(
        self,
        receipt_hash_row: dict[str, Any] | None = None,
        latest_run_rows: list[dict[str, Any]] | None = None,
        run_metric_rows: list[dict[str, Any]] | None = None,
        run_summary_rows: list[dict[str, Any]] | None = None,
        coverage_latest: dict[str, Any] | None = None,
        canonical_coverage_rows: list[Any] | None = None,
    ):
        self.receipt_hash_row = receipt_hash_row
        self.latest_run_rows = latest_run_rows or []
        self.run_metric_rows = run_metric_rows or []
        # healthsave_sync_run_summaries (migration 026): the client's closing
        # summary per run. Empty ⇒ pre-026 / no client has PUT one yet.
        self.run_summary_rows = run_summary_rows or []
        self.coverage_latest = coverage_latest
        self.canonical_coverage_rows = canonical_coverage_rows

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        # /api/apple/coverage scenario (only when configured, so every other fixture
        # is untouched): canonical per-metric coverage rows, then max(<time>) per
        # legacy table.
        if self.canonical_coverage_rows is not None and "FROM canonical_observations" in sql:
            return _FakeResult(rows=self.canonical_coverage_rows)
        if self.coverage_latest is not None and sql.startswith("SELECT max("):
            table = sql.split(" FROM ", 1)[1].split()[0]
            return _FakeResult(row=(self.coverage_latest.get(table),))
        if sql.startswith("INSERT INTO healthsave_sync_run_summaries"):
            return _FakeResult(
                row={
                    "received_at": CORPUS_SUMMARY_RECEIVED_AT,
                    "updated_at": CORPUS_SUMMARY_RECEIVED_AT,
                }
            )
        if "FROM healthsave_sync_run_summaries" in sql:
            if "WHERE sync_run_id = :sync_run_id" in sql:
                wanted = (params or {}).get("sync_run_id")
                row = next((r for r in self.run_summary_rows if r["sync_run_id"] == wanted), None)
                return _FakeResult(row=row)
            return _FakeResult(row=self.run_summary_rows[0] if self.run_summary_rows else None)
        if (
            "INSERT INTO healthsave_sync_receipts" in sql
            and "'processing'" in sql
            and "RETURNING payload_hash" in sql
        ):
            if self.receipt_hash_row is not None:
                return _FakeResult()
            return _FakeResult(
                row={
                    "payload_hash": (params or {}).get("payload_hash"),
                    "status": "processing",
                    "response_payload": None,
                }
            )
        if sql.startswith("SELECT payload_hash") and "FROM healthsave_sync_receipts" in sql:
            return _FakeResult(row=self.receipt_hash_row)
        if sql.startswith("UPDATE healthsave_sync_receipts") and "status = 'processing'" in sql:
            return _FakeResult(row=(1,))
        if sql.startswith("SELECT sync_run_id FROM healthsave_sync_receipts"):
            row = {"sync_run_id": CORPUS_SYNC_RUN_ID} if self.latest_run_rows else None
            return _FakeResult(row=row)
        if "GROUP BY sync_run_id" in sql:
            return _FakeResult(row=self.latest_run_rows[0] if self.latest_run_rows else None)
        if "GROUP BY metric" in sql:
            return _FakeResult(rows=self.run_metric_rows)
        if sql.startswith("SELECT id FROM devices"):
            return _FakeResult(row=(1,))
        if sql.startswith("SELECT count(*)"):
            return _FakeResult(row=(0, None, None))
        return _FakeResult()

    async def commit(self):
        pass

    async def rollback(self):
        pass


class CorpusRequest:
    """Minimal stand-in for fastapi.Request as the handlers use it."""

    def __init__(self, payload: Any = None, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = headers or {}

    async def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _batch_headers(metric: str) -> dict[str, str]:
    batch_id = f"corpus-{metric}-000"
    return {
        "Idempotency-Key": batch_id,
        "X-HealthSave-Sync-Run-ID": CORPUS_SYNC_RUN_ID,
        "X-HealthSave-Batch-ID": batch_id,
        "X-HealthSave-Payload-Hash": f"sha256:corpus-{metric}",
        "X-HealthSave-Metric": metric,
        "X-HealthSave-Batch-Index": "0",
        "X-HealthSave-Total-Batches": "1",
        "X-HealthSave-Sync-Mode": "incremental",
        "X-HealthSave-Anchor-Present": "true",
        "X-HealthSave-Lower-Bound-Reason": "anchor",
        "X-HealthSave-Full-Export": "false",
        "X-HealthSave-Sample-Min-Time": CORPUS_SAMPLE_MIN,
        "X-HealthSave-Sample-Max-Time": CORPUS_SAMPLE_MAX,
    }


# Receipt rows fed to the sync-run endpoints, keyed by the SQL aliases.
_LATEST_RUN_ROW = {
    "sync_run_id": CORPUS_SYNC_RUN_ID,
    "started_at": "2026-01-01T06:00:00+00:00",
    "completed_at": "2026-01-01T06:05:00+00:00",
    "batches_seen": 3,
    "batches_processed": 3,
    "batches_empty": 0,
    "batches_failed": 0,
    "records_received": 120,
    "records_accepted": 118,
    "records_inserted_new": 100,
    "records_deduped_existing": 18,
    "storage_result_level": "inserted_vs_existing",
    "records_skipped": 2,
    "sample_min_at": "2026-01-01T00:00:00+00:00",
    "sample_max_at": "2026-01-01T05:59:00+00:00",
    "metrics": ["heart_rate", "sleep_analysis", "step_count"],
}

_RUN_METRIC_ROWS = [
    {
        "metric": "heart_rate",
        "started_at": "2026-01-01T06:00:00+00:00",
        "completed_at": "2026-01-01T06:02:00+00:00",
        "batches_seen": 2,
        "batches_processed": 2,
        "batches_empty": 0,
        "batches_failed": 0,
        "records_received": 80,
        "records_accepted": 79,
        "records_inserted_new": 70,
        "records_deduped_existing": 9,
        "storage_result_level": "inserted_vs_existing",
        "records_skipped": 1,
        "sample_min_at": "2026-01-01T00:00:00+00:00",
        "sample_max_at": "2026-01-01T05:59:00+00:00",
        "latest_sample_at": "2026-01-01T05:59:00+00:00",
    },
    {
        "metric": "step_count",
        "started_at": "2026-01-01T06:02:00+00:00",
        "completed_at": "2026-01-01T06:05:00+00:00",
        "batches_seen": 1,
        "batches_processed": 1,
        "batches_empty": 0,
        "batches_failed": 0,
        "records_received": 40,
        "records_accepted": 39,
        "records_inserted_new": 30,
        "records_deduped_existing": 9,
        "storage_result_level": "inserted_vs_existing",
        "records_skipped": 1,
        "sample_min_at": "2026-01-01T01:00:00+00:00",
        "sample_max_at": "2026-01-01T05:30:00+00:00",
        "latest_sample_at": "2026-01-01T05:30:00+00:00",
    },
]


# The zero-delivery run's closing summary, keyed by the SQL columns of
# healthsave_sync_run_summaries (migration 026).
_ZERO_DELIVERY_SUMMARY_ROW = {
    "sync_run_id": CORPUS_ZERO_DELIVERY_RUN_ID,
    "client_platform": "ios",
    "client_app_version": "1.8.0",
    "trigger": "observer",
    "intent": "latest_changes",
    "outcome": "completed",
    "delivery": "none",
    "records_sent": 0,
    "metrics_checked": ["heart_rate", "sleep_analysis", "step_count"],
    "metrics_with_changes": [],
    "error_class": None,
    "client_started_at": "2026-01-01T06:20:00+00:00",
    "client_completed_at": "2026-01-01T06:20:04+00:00",
    "received_at": CORPUS_SUMMARY_RECEIVED_AT,
    "updated_at": CORPUS_SUMMARY_RECEIVED_AT,
}

# What the iOS app PUTs when it closes that run (DestinationRunSummarySink).
_ZERO_DELIVERY_SUMMARY_BODY = {
    "schema_version": 1,
    "outcome": "completed",
    "delivery": "none",
    "records_sent": 0,
    "metrics_checked": ["heart_rate", "sleep_analysis", "step_count"],
    "metrics_with_changes": [],
    "trigger": "observer",
    "intent": "latest_changes",
    "client_platform": "ios",
    "client_app_version": "1.8.0",
    "started_at": "2026-01-01T06:20:00.000Z",
    "completed_at": "2026-01-01T06:20:04.000Z",
}


def _scrub(value: Any) -> Any:
    """Drop pydantic's version-volatile ``url`` key from error bodies."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k != "url"}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _normalize_validation_detail(fixture: dict[str, Any]) -> dict[str, Any]:
    """Reduce pydantic validation errors to their version-stable parts.

    The ``msg`` wording and extra keys (``input``, ``ctx``) shift across
    pydantic minor versions (CI pins 2.9.2; dev machines may run newer).
    iOS never parses the 422 detail — it classifies on the status code —
    so the contract pinned here is: status 422, a ``detail`` list, and
    the stable ``loc``/``type`` of each error.
    """
    detail = fixture["body"].get("detail")
    if isinstance(detail, list):
        fixture["body"]["detail"] = [
            {"loc": err.get("loc"), "type": err.get("type")} for err in detail
        ]
    return fixture


async def _call(endpoint: str, method: str, coro) -> dict[str, Any]:
    try:
        body = await coro
        status = 200
    except HTTPException as exc:
        body = {"detail": exc.detail}
        status = exc.status_code
    return {
        "endpoint": endpoint,
        "method": method,
        "status": status,
        "body": _scrub(jsonable_encoder(body)),
    }


async def _generate() -> dict[str, dict[str, Any]]:
    from server.api.coverage import apple_coverage
    from server.api.health_routes import api_health
    from server.api.ingest import apple_batch
    from server.api.status import apple_status
    from server.api.sync import (
        SyncRunSummaryPayload,
        latest_sync_run,
        put_sync_run_summary,
        sync_run,
    )

    fixtures: dict[str, dict[str, Any]] = {}

    # POST /api/apple/batch — one receipt per golden request fixture.
    for path in sorted(REQUEST_FIXTURES_DIR.glob("*_batch.json")):
        payload = json.loads(path.read_text())
        metric = payload["metric"]
        request = CorpusRequest(payload, headers=_batch_headers(metric))
        fixtures[f"batch_receipt_{path.stem.removesuffix('_batch')}.json"] = await _call(
            "/api/apple/batch", "POST", apple_batch(request, CorpusSession())
        )

    # Idempotent replay: same key, same payload hash → normal 200 receipt.
    heart_rate = json.loads((REQUEST_FIXTURES_DIR / "heart_rate_batch.json").read_text())
    replay_session = CorpusSession(
        receipt_hash_row={
            "payload_hash": "sha256:corpus-heart_rate",
            "status": "processed",
            "response_payload": fixtures["batch_receipt_heart_rate.json"]["body"],
        }
    )
    fixtures["batch_receipt_duplicate.json"] = await _call(
        "/api/apple/batch",
        "POST",
        apple_batch(
            CorpusRequest(heart_rate, headers=_batch_headers("heart_rate")), replay_session
        ),
    )

    # Retry key reused with a different payload → 409 (iOS: terminal).
    conflict_session = CorpusSession(
        receipt_hash_row={
            "payload_hash": "sha256:other-payload",
            "status": "processed",
            "response_payload": fixtures["batch_receipt_heart_rate.json"]["body"],
        }
    )
    fixtures["batch_conflict_409.json"] = await _call(
        "/api/apple/batch",
        "POST",
        apple_batch(
            CorpusRequest(heart_rate, headers=_batch_headers("heart_rate")), conflict_session
        ),
    )

    # Malformed JSON body → 400 (iOS: terminal).
    bad_json = CorpusRequest(
        json.JSONDecodeError("Expecting value", "not json", 0),
        headers=_batch_headers("heart_rate"),
    )
    fixtures["batch_invalid_json_400.json"] = await _call(
        "/api/apple/batch", "POST", apple_batch(bad_json, CorpusSession())
    )

    # Schema-invalid payload → 422 with pydantic error list (iOS: terminal).
    invalid = CorpusRequest(
        {"metric": "heart_rate", "batch_index": 0, "total_batches": 1, "samples": "not-a-list"},
        headers=_batch_headers("heart_rate"),
    )
    fixtures["batch_rejected_422.json"] = _normalize_validation_detail(
        await _call("/api/apple/batch", "POST", apple_batch(invalid, CorpusSession()))
    )

    # GET /api/health — the liveness probe.
    fixtures["health.json"] = await _call("/api/health", "GET", api_health())

    # GET /api/apple/status — flat metric map (fresh install: all zero).
    fixtures["status.json"] = await _call(
        "/api/apple/status", "GET", apple_status(CorpusRequest(), CorpusSession())
    )

    # GET /api/apple/coverage — newest sample per metric. The flat table keys are the
    # legacy shape; ``metrics`` is what the iOS Recovery-lane attestation decodes
    # (``{wire metric: ISO 8601 UTC ms Z}``). HRV and steps come from the canonical
    # store; activity rings from the date-keyed legacy table; workouts have no data.
    fixtures["coverage.json"] = await _call(
        "/api/apple/coverage",
        "GET",
        apple_coverage(
            CorpusRequest(),
            CorpusSession(
                coverage_latest=_COVERAGE_LEGACY_LATEST,
                canonical_coverage_rows=_COVERAGE_CANONICAL_ROWS,
            ),
        ),
    )

    # GET /api/v2/sync/runs/latest — populated and empty.
    fixtures["sync_run_latest.json"] = await _call(
        "/api/v2/sync/runs/latest",
        "GET",
        latest_sync_run(CorpusSession(latest_run_rows=[_LATEST_RUN_ROW])),
    )
    fixtures["sync_run_latest_empty.json"] = await _call(
        "/api/v2/sync/runs/latest", "GET", latest_sync_run(CorpusSession())
    )

    # GET /api/v2/sync/runs/{sync_run_id} — populated and unknown-run.
    fixtures["sync_run_by_id.json"] = await _call(
        f"/api/v2/sync/runs/{CORPUS_SYNC_RUN_ID}",
        "GET",
        sync_run(CORPUS_SYNC_RUN_ID, CorpusSession(run_metric_rows=_RUN_METRIC_ROWS)),
    )
    fixtures["sync_run_unknown_empty.json"] = await _call(
        "/api/v2/sync/runs/corpus-run-missing",
        "GET",
        sync_run("corpus-run-missing", CorpusSession()),
    )

    # PUT /api/v2/sync/runs/{sync_run_id}/summary — the client closes a run that
    # sent nothing. The ack is what DestinationRunSummarySink decodes.
    fixtures["sync_run_summary_put.json"] = await _call(
        f"/api/v2/sync/runs/{CORPUS_ZERO_DELIVERY_RUN_ID}/summary",
        "PUT",
        put_sync_run_summary(
            CORPUS_ZERO_DELIVERY_RUN_ID,
            SyncRunSummaryPayload.model_validate(_ZERO_DELIVERY_SUMMARY_BODY),
            CorpusRequest(),
            CorpusSession(),
        ),
    )

    # GET /api/v2/sync/runs/latest — the newest run delivered nothing: it is
    # known only from its closing summary, and it MUST still be the latest run
    # (not the previous run that happened to send batches).
    zero_delivery = CorpusSession(
        latest_run_rows=[_LATEST_RUN_ROW],
        run_summary_rows=[_ZERO_DELIVERY_SUMMARY_ROW],
    )
    fixtures["sync_run_latest_zero_delivery.json"] = await _call(
        "/api/v2/sync/runs/latest", "GET", latest_sync_run(zero_delivery)
    )

    # GET /api/v2/sync/runs/{sync_run_id} — same run by id: complete, not
    # "empty" (iOS treats the empty sentinel as "no receipt yet").
    fixtures["sync_run_by_id_zero_delivery.json"] = await _call(
        f"/api/v2/sync/runs/{CORPUS_ZERO_DELIVERY_RUN_ID}",
        "GET",
        sync_run(
            CORPUS_ZERO_DELIVERY_RUN_ID,
            CorpusSession(run_summary_rows=[_ZERO_DELIVERY_SUMMARY_ROW]),
        ),
    )

    return fixtures


def _serialize(fixture: dict[str, Any]) -> str:
    return json.dumps(fixture, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on drift, write nothing")
    args = parser.parse_args()

    fixtures = asyncio.run(_generate())

    if args.check:
        drifted: list[str] = []
        for name, fixture in fixtures.items():
            path = OUT_DIR / name
            if not path.exists() or path.read_text() != _serialize(fixture):
                drifted.append(name)
        stale = {p.name for p in OUT_DIR.glob("*.json")} - set(fixtures)
        if drifted or stale:
            for name in sorted(drifted):
                print(f"DRIFT: {name}", file=sys.stderr)
            for name in sorted(stale):
                print(f"STALE (no longer generated): {name}", file=sys.stderr)
            print(
                "iOS response corpus drift. A handler changed a response the "
                "shipped iOS app decodes. Regenerate with "
                "`python -m scripts.generate_ios_response_corpus`, mirror to "
                "ios_app/Tests/HealthSyncTests/Fixtures/Responses/, and run "
                "the iOS BackendResponseCorpusTests before shipping.",
                file=sys.stderr,
            )
            return 1
        print(f"iOS response corpus up to date ({len(fixtures)} fixtures).")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, fixture in fixtures.items():
        (OUT_DIR / name).write_text(_serialize(fixture))
    print(f"Wrote {len(fixtures)} fixtures to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
