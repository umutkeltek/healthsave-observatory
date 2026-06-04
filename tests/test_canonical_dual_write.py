"""/api/apple/batch -> canonical_observations in-transaction write."""

from __future__ import annotations

import pytest
from contracts._base import DEFAULT_OWNER_ID
from server.api.ingest import _write_canonical_observations

_HR_SAMPLES = [
    {"date": "2026-05-28T08:00:00Z", "qty": 61, "source": "Apple Watch"},
    {"date": "2026-05-28T08:01:00Z", "qty": 64, "source": "Apple Watch"},
]


class _OkSession:
    def __init__(self) -> None:
        self.calls: list = []
        self.committed = 0
        self.rolled_back = 0

    async def execute(self, statement, params=None):
        self.calls.append((statement, params))

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class _FailSession:
    def __init__(self) -> None:
        self.rolled_back = 0

    async def execute(self, statement, params=None):
        raise RuntimeError("db down")

    async def commit(self) -> None:  # pragma: no cover - never reached
        pass

    async def rollback(self) -> None:
        self.rolled_back += 1


@pytest.mark.asyncio
async def test_canonical_write_persists_mapped_observations_without_committing() -> None:
    session = _OkSession()
    await _write_canonical_observations(
        session, metric="heart_rate", samples=_HR_SAMPLES, owner_id=DEFAULT_OWNER_ID, raw_log_id=7
    )
    assert session.committed == 0
    assert len(session.calls) == 1
    _, params = session.calls[0]
    assert len(params) == 2
    assert {p["metric_id"] for p in params} == {"vital.heart_rate"}


@pytest.mark.asyncio
async def test_canonical_write_failure_propagates_for_atomic_ingest() -> None:
    session = _FailSession()
    with pytest.raises(RuntimeError, match="db down"):
        await _write_canonical_observations(
            session,
            metric="heart_rate",
            samples=_HR_SAMPLES,
            owner_id=DEFAULT_OWNER_ID,
            raw_log_id=None,
        )
    assert session.rolled_back == 0


@pytest.mark.asyncio
async def test_dual_write_unmapped_metric_is_a_noop() -> None:
    session = _OkSession()
    await _write_canonical_observations(
        session,
        metric="not_a_real_metric",
        samples=[{"date": "2026-05-28T08:00:00Z", "qty": 1}],
        owner_id=DEFAULT_OWNER_ID,
        raw_log_id=None,
    )
    assert session.committed == 0
    assert session.calls == []
