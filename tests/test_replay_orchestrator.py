"""Replay orchestrator (ADR-0001 Decision H) — re-normalize stored raw payloads.

Pure orchestration over injected fakes: no database. Proves the backfill path
(including the `blood_oxygen` rows the wire alias unlocked), honest accounting,
run-id lineage, and the raw reader's JSONB-shape handling.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from contracts._base import DEFAULT_OWNER_ID
from replay.orchestrator import ReplayReport, replay_apple_raw_payloads
from storage.timescale.ingest import fetch_raw_payloads

_SOURCE_ID = UUID("00000000-0000-0000-0000-0000000000aa")
_RUN_ID = UUID("00000000-0000-0000-0000-0000000000bb")

_HR = {
    "metric": "heart_rate",
    "samples": [
        {"date": "2026-05-28T08:00:00Z", "qty": 61, "source": "Apple Watch"},
        {"date": "2026-05-28T08:01:00Z", "qty": 64, "source": "Apple Watch"},
    ],
}
_BLOOD_OX = {
    "metric": "blood_oxygen",  # the wire alias added this foundation pass
    "samples": [{"date": "2026-05-28T08:00:00Z", "qty": 98, "source": "Apple Watch"}],
}


class _FakeRepo:
    """Records what the orchestrator submits; mimics idempotent insert_many."""

    def __init__(self) -> None:
        self.written: list[Any] = []

    async def insert_many(self, session: Any, observations: list[Any]) -> int:
        self.written.extend(observations)
        return len(observations)


def _reader(rows: list[tuple[int, dict]]):
    async def read(session: Any, *, after_id: int = 0, limit: int = 500):
        return rows

    return read


@pytest.mark.asyncio
async def test_replay_backfills_canonical_observations() -> None:
    repo = _FakeRepo()
    report = await replay_apple_raw_payloads(
        session=None,
        raw_reader=_reader([(1, _HR), (2, _BLOOD_OX)]),
        repo=repo,
        run_id=_RUN_ID,
        source_id=_SOURCE_ID,
        owner_id=DEFAULT_OWNER_ID,
    )
    assert report.payloads_scanned == 2
    assert report.observations_produced == 3
    assert report.observations_submitted == 3
    # blood_oxygen now reaches the canonical store via the wire alias.
    assert {o.metric_id for o in repo.written} == {"vital.heart_rate", "vital.blood_oxygen"}
    # Every observation carries the run id (lineage for a future supersede pass).
    assert all(str(o.normalization_run_id) == str(_RUN_ID) for o in repo.written)
    # raw_id is preserved in provenance so replay can trace back to exact bytes.
    assert {o.provenance.raw_payload_ref for o in repo.written} == {"1", "2"}


@pytest.mark.asyncio
async def test_replay_unmapped_metric_produces_and_submits_nothing() -> None:
    repo = _FakeRepo()
    report = await replay_apple_raw_payloads(
        session=None,
        raw_reader=_reader(
            [
                (
                    1,
                    {
                        "metric": "not_a_real_metric",
                        "samples": [{"date": "2026-05-28T08:00:00Z", "qty": 1}],
                    },
                )
            ]
        ),
        repo=repo,
        run_id=_RUN_ID,
        source_id=_SOURCE_ID,
    )
    assert report.observations_produced == 0
    assert report.observations_rejected == 1
    assert report.observations_submitted == 0
    assert repo.written == []


@pytest.mark.asyncio
async def test_replay_empty_scan_is_a_clean_noop() -> None:
    repo = _FakeRepo()
    report = await replay_apple_raw_payloads(
        session=None,
        raw_reader=_reader([]),
        repo=repo,
        run_id=_RUN_ID,
        source_id=_SOURCE_ID,
    )
    assert report == ReplayReport(
        run_id=str(_RUN_ID),
        payloads_scanned=0,
        observations_produced=0,
        observations_rejected=0,
        observations_submitted=0,
    )
    assert repo.written == []


# ──────────────────────────────────────────────────────────────
#  fetch_raw_payloads — the storage-zone reader (str + dict JSONB)
# ──────────────────────────────────────────────────────────────


class _RawRowsSession:
    """Fake AsyncSession returning canned raw_ingestion_log rows."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def execute(self, statement: Any, params: Any = None) -> Any:
        rows = self._rows

        class _Result:
            def mappings(self) -> Any:
                class _Mappings:
                    def all(self) -> list[dict]:
                        return rows

                return _Mappings()

        return _Result()


@pytest.mark.asyncio
async def test_fetch_raw_payloads_handles_dict_and_str_jsonb() -> None:
    session = _RawRowsSession(
        [
            {"id": 1, "raw_payload": {"metric": "heart_rate", "samples": []}},  # asyncpg dict
            {"id": 2, "raw_payload": '{"metric": "blood_oxygen", "samples": []}'},  # str fallback
        ]
    )
    out = await fetch_raw_payloads(session)
    assert out == [
        (1, {"metric": "heart_rate", "samples": []}),
        (2, {"metric": "blood_oxygen", "samples": []}),
    ]
