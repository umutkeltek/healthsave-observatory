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
from pathlib import Path
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

    def mappings(self):
        return self

    def scalar(self):
        return 1


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
    ):
        self.receipt_hash_row = receipt_hash_row
        self.latest_run_rows = latest_run_rows or []
        self.run_metric_rows = run_metric_rows or []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        if sql.startswith("SELECT payload_hash FROM healthsave_sync_receipts"):
            return _FakeResult(row=self.receipt_hash_row)
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
    from server.api.health_routes import api_health
    from server.api.ingest import apple_batch
    from server.api.status import apple_status
    from server.api.sync import latest_sync_run, sync_run

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
    replay_session = CorpusSession(receipt_hash_row={"payload_hash": "sha256:corpus-heart_rate"})
    fixtures["batch_receipt_duplicate.json"] = await _call(
        "/api/apple/batch",
        "POST",
        apple_batch(
            CorpusRequest(heart_rate, headers=_batch_headers("heart_rate")), replay_session
        ),
    )

    # Retry key reused with a different payload → 409 (iOS: terminal).
    conflict_session = CorpusSession(receipt_hash_row={"payload_hash": "sha256:other-payload"})
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
