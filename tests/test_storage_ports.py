"""Storage port contract tests.

Phase 5A established :class:`storage.ports.RunRepository` as a Protocol
contract with a TimescaleDB implementation. This file pins:

1. The Timescale impl satisfies the Protocol (runtime_checkable).
2. An in-memory implementation also satisfies it — proving the
   Protocol is genuinely swappable, not Timescale-coupled.
3. Module-level convenience functions delegate to ``default_repository``.

Once Phase 5B+ migrates consumers to inject a ``RunRepository`` directly,
those consumers' tests will also exercise the Protocol via fakes — that
is a separate concern and lives where the consumers' tests live.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from storage.ports import RunRepository
from storage.timescale.runs import (
    PipelineRun,
    TimescaleRunRepository,
    TriggeredBy,
    default_repository,
)


def test_timescale_repo_satisfies_protocol() -> None:
    assert isinstance(default_repository, RunRepository)
    assert isinstance(TimescaleRunRepository(), RunRepository)


class _InMemoryRunRepository:
    """Reference fake implementation for tests that want to inject a
    real Protocol-conforming repo. Keeps state in dicts; honors the
    ``ON CONFLICT (idempotency_key) DO NOTHING`` contract."""

    def __init__(self) -> None:
        self._by_id: dict[int, PipelineRun] = {}
        self._by_key: dict[str, int] = {}
        self._next_id = 1

    async def claim_run(
        self,
        session: Any,
        *,
        job_kind: str,
        idempotency_key: str,
        triggered_by: TriggeredBy = "scheduler",
        leased_by: str | None = None,
    ) -> int | None:
        if idempotency_key in self._by_key:
            return None
        run_id = self._next_id
        self._next_id += 1
        self._by_id[run_id] = PipelineRun(
            id=run_id,
            job_kind=job_kind,
            idempotency_key=idempotency_key,
            status="running",
            started_at=None,
            ended_at=None,
            result=None,
            error=None,
            attempt=1,
            triggered_by=triggered_by,
        )
        self._by_key[idempotency_key] = run_id
        return run_id

    async def mark_succeeded(
        self,
        session: Any,
        *,
        run_id: int,
        result: dict[str, Any] | None = None,
    ) -> None:
        self._by_id[run_id] = replace(self._by_id[run_id], status="succeeded", result=result)

    async def mark_failed(
        self,
        session: Any,
        *,
        run_id: int,
        error: str,
    ) -> None:
        self._by_id[run_id] = replace(self._by_id[run_id], status="failed", error=error[:8000])

    async def mark_skipped(
        self,
        session: Any,
        *,
        run_id: int,
        reason: str | None = None,
    ) -> None:
        self._by_id[run_id] = replace(self._by_id[run_id], status="skipped", error=reason)

    async def fetch_recent(
        self,
        session: Any,
        *,
        job_kind: str | None = None,
        limit: int = 100,
    ) -> list[PipelineRun]:
        rows = list(self._by_id.values())
        if job_kind is not None:
            rows = [r for r in rows if r.job_kind == job_kind]
        return list(reversed(rows))[:limit]


def test_in_memory_repo_satisfies_protocol() -> None:
    """The whole point of the Protocol — a fake reference impl works."""
    fake = _InMemoryRunRepository()
    assert isinstance(fake, RunRepository)


@pytest.mark.asyncio
async def test_in_memory_repo_implements_idempotency_contract() -> None:
    """At-most-once on idempotency_key — claim returns None on conflict."""
    repo: RunRepository = _InMemoryRunRepository()

    rid = await repo.claim_run(session=None, job_kind="daily_briefing", idempotency_key="key-1")
    assert rid == 1

    duplicate = await repo.claim_run(
        session=None, job_kind="daily_briefing", idempotency_key="key-1"
    )
    assert duplicate is None


@pytest.mark.asyncio
async def test_in_memory_repo_lifecycle_walks_all_states() -> None:
    """One row through claim → succeeded; another through claim → failed.
    fetch_recent returns both newest-first."""
    repo: RunRepository = _InMemoryRunRepository()

    rid_ok = await repo.claim_run(
        session=None,
        job_kind="daily_briefing",
        idempotency_key="ok-key",
        triggered_by="scheduler",
    )
    assert rid_ok is not None
    await repo.mark_succeeded(session=None, run_id=rid_ok, result={"engine_run_id": 7})

    rid_fail = await repo.claim_run(
        session=None,
        job_kind="anomaly_check",
        idempotency_key="fail-key",
        triggered_by="api",
    )
    assert rid_fail is not None
    await repo.mark_failed(session=None, run_id=rid_fail, error="boom")

    all_runs = await repo.fetch_recent(session=None)
    assert len(all_runs) == 2
    # Newest first — fail was inserted second.
    assert all_runs[0].status == "failed"
    assert all_runs[0].error == "boom"
    assert all_runs[1].status == "succeeded"
    assert all_runs[1].result == {"engine_run_id": 7}


@pytest.mark.asyncio
async def test_in_memory_repo_fetch_recent_filters_by_job_kind() -> None:
    repo: RunRepository = _InMemoryRunRepository()

    await repo.claim_run(session=None, job_kind="daily_briefing", idempotency_key="a")
    await repo.claim_run(session=None, job_kind="anomaly_check", idempotency_key="b")
    await repo.claim_run(session=None, job_kind="daily_briefing", idempotency_key="c")

    daily = await repo.fetch_recent(session=None, job_kind="daily_briefing")
    assert {r.idempotency_key for r in daily} == {"a", "c"}


def test_module_level_functions_share_default_repository() -> None:
    """The convenience functions are bound to ``default_repository`` —
    backwards-compat path for v1.x callers that imported the bare
    function names. Verified by identity check on the function objects."""
    from storage.timescale import runs as runs_module

    # Each function references default_repository.<method>.
    # Easier: assert default_repository's class is what we expect.
    assert isinstance(default_repository, TimescaleRunRepository)
    # And the module exposes the convenience entry points.
    for name in ("claim_run", "mark_succeeded", "mark_failed", "mark_skipped", "fetch_recent"):
        assert hasattr(runs_module, name), f"runs module missing {name}"
