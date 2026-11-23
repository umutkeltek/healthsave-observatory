"""One-metric back-fill (``replay.orchestrator.backfill_metric_from_raw``).

Before 1.5.2 the server stored RMSSD batches raw (``quantity_samples``) but had
no canonical metric for them, so nothing showed them. The back-fill turns those
stored batches into ``vital.hrv_rmssd`` readings. Pure orchestration over fakes:
it writes only the one metric, replays that metric's own deletions in order,
takes the owner from the batch's receipt, and never touches SDNN.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from contracts._base import DEFAULT_OWNER_ID, Provenance
from normalization import normalize_apple_batch
from replay.orchestrator import MetricBackfillReport, backfill_metric_from_raw

_SOURCE_ID = UUID("a9b1e7e0-0000-4000-8000-000000000001")
_RUN_ID = UUID("00000000-0000-0000-0000-0000000000bb")
_PARTICIPANT = UUID("7a1d2c3e-0000-4000-8000-0000000000aa")
_RMSSD = "vital.hrv_rmssd"


def _v2(metric: str, uuids: list[str], qty: float, deletions: list[str] = ()) -> dict:
    """An iOS v2 batch, keys as the resting_heart_rate golden carries them."""

    return {
        "schema_version": 2,
        "metric": metric,
        "batch_index": 0,
        "total_batches": 1,
        "samples": [
            {
                "uuid": uuid,
                "startDate": f"2026-11-2{i + 1}T03:10:00.000Z",
                "endDate": f"2026-11-2{i + 1}T03:10:00.000Z",
                "date": f"2026-11-2{i + 1}T03:10:00.000Z",
                "qty": qty + i,
                "unit": "ms",
                "tzOffsetMinutes": -300,
                "source": "Apple Watch",
                "motionContext": None,  # explicit null: the route drops it, so must replay
            }
            for i, uuid in enumerate(uuids)
        ],
        "deletions": [{"uuid": uuid} for uuid in deletions],
        "source_bundle_id": "com.healthsave.ios",
        "device": {"name": "iPhone", "model": "iPhone18,2"},
    }


RM_A = "D2C70000-0000-4000-8000-0000000198A1"
RM_B = "D2C70000-0000-4000-8000-0000000198A2"
SD_A = "D2C70000-0000-4000-8000-0000000198B1"


class _FakeRepo:
    def __init__(self) -> None:
        self.written: list[Any] = []

    async def insert_many(self, session: Any, observations: list[Any]) -> int:
        self.written.extend(observations)
        return len(observations)


class _FakeSuperseder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, session: Any, *, owner_id: UUID, metric_id: str, uuids: list[str]):
        self.calls.append({"owner_id": owner_id, "metric_id": metric_id, "uuids": list(uuids)})
        return len(uuids)


def _reader(rows: list[tuple[int, dict, UUID | None]]):
    async def read(session: Any, *, after_id: int = 0, limit: int = 500):
        return [row for row in rows if row[0] > after_id][:limit]

    return read


async def _run(rows, *, fallback=DEFAULT_OWNER_ID, after_id=0, limit=500):
    repo, superseder = _FakeRepo(), _FakeSuperseder()
    report = await backfill_metric_from_raw(
        None,
        raw_reader=_reader(rows),
        repo=repo,
        superseder=superseder,
        run_id=_RUN_ID,
        source_id=_SOURCE_ID,
        metric_id=_RMSSD,
        fallback_owner_id=fallback,
        after_id=after_id,
        limit=limit,
    )
    return report, repo, superseder


@pytest.mark.asyncio
async def test_stored_rmssd_batches_become_rmssd_readings_only() -> None:
    rows = [
        (11, _v2("heart_rate_variability_rmssd", [RM_A, RM_B], 61), None),
        # Even if an SDNN batch reached the reader, nothing of it is written.
        (12, _v2("heart_rate_variability", [SD_A], 48), None),
    ]
    report, repo, superseder = await _run(rows)
    assert {o.metric_id for o in repo.written} == {_RMSSD}
    assert sorted(o.source_record_uid.upper() for o in repo.written) == [RM_A, RM_B]
    assert sorted(o.value.value for o in repo.written) == [61.0, 62.0]
    assert all(o.normalization_run_id == _RUN_ID for o in repo.written)
    assert {o.provenance.raw_payload_ref for o in repo.written} == {"11"}
    assert all(o.owner_id == DEFAULT_OWNER_ID for o in repo.written)
    assert superseder.calls == []
    assert report == MetricBackfillReport(
        run_id=str(_RUN_ID),
        metric_id=_RMSSD,
        payloads_scanned=2,
        payloads_skipped_unknown_owner=0,
        observations_produced=2,
        observations_rejected=0,
        observations_submitted=2,
        deletions_applied=0,
        last_raw_id=12,
    )


@pytest.mark.asyncio
async def test_a_later_deletion_is_replayed_after_its_add_and_scoped_to_rmssd() -> None:
    rows = [
        (21, _v2("heart_rate_variability_rmssd", [RM_A, RM_B], 61), None),
        (22, _v2("heart_rate_variability_rmssd", [], 0, deletions=[RM_A]), None),
    ]
    report, repo, superseder = await _run(rows)
    assert report.deletions_applied == 1
    assert superseder.calls == [
        {"owner_id": DEFAULT_OWNER_ID, "metric_id": _RMSSD, "uuids": [RM_A]}
    ]


@pytest.mark.asyncio
async def test_the_receipt_owner_wins_and_receiptless_batches_are_skipped_without_fallback() -> (
    None
):
    rows = [
        (31, _v2("heart_rate_variability_rmssd", [RM_A], 61), _PARTICIPANT),
        (32, _v2("heart_rate_variability_rmssd", [RM_B], 70, deletions=[RM_A]), None),
    ]
    report, repo, superseder = await _run(rows, fallback=None)
    assert [o.owner_id for o in repo.written] == [_PARTICIPANT]
    assert report.payloads_skipped_unknown_owner == 1
    assert superseder.calls == [], "a skipped batch's deletions are skipped too"
    assert report.last_raw_id == 32, "the cursor still moves past a skipped batch"


@pytest.mark.asyncio
async def test_paging_resumes_after_the_cursor_and_an_empty_page_ends() -> None:
    rows = [(n, _v2("heart_rate_variability_rmssd", [RM_A], 60 + n), None) for n in (41, 42, 43)]
    first, _, _ = await _run(rows, limit=2)
    assert (first.payloads_scanned, first.last_raw_id) == (2, 42)
    rest, repo, _ = await _run(rows, after_id=first.last_raw_id, limit=2)
    assert (rest.payloads_scanned, rest.last_raw_id) == (1, 43)
    assert {o.provenance.raw_payload_ref for o in repo.written} == {"43"}
    done, _, _ = await _run(rows, after_id=43)
    assert done.payloads_scanned == 0 and done.last_raw_id == 43


@pytest.mark.asyncio
async def test_a_replayed_reading_has_the_live_dual_writes_dedup_key() -> None:
    """Same normalizer, source and owner as the live route: one key, never a twin."""

    payload = _v2("heart_rate_variability_rmssd", [RM_A], 61)
    _, repo, _ = await _run([(51, payload, None)])
    live_samples = [{k: v for k, v in s.items() if v is not None} for s in payload["samples"]]
    live = normalize_apple_batch(
        {"metric": payload["metric"], "samples": live_samples},
        source_id=_SOURCE_ID,
        provenance=Provenance(
            source_plugin_id="apple_health", sdk_version="2", captured_at=datetime.now(UTC)
        ),
        owner_id=DEFAULT_OWNER_ID,
    )
    assert [o.dedup_key for o in repo.written] == [o.dedup_key for o in live.observations]
