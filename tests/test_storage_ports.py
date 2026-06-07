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

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from storage.ports import (
    AuditLog,
    BriefingRepository,
    IngestStorage,
    MeasurementProjectionRepository,
    MeasurementRepository,
    ReadinessRepository,
    RunRepository,
    SyncReceiptRepository,
    TimeSeriesQueryService,
)
from storage.timescale.briefings import (
    FindingRow,
    NarrativeRow,
    TimescaleBriefingRepository,
)
from storage.timescale.briefings import default_repository as briefing_default_repository
from storage.timescale.observations import SeriesPoint
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


# ──────────────────────────────────────────────────────────────
#  BriefingRepository (Phase 5B)
# ──────────────────────────────────────────────────────────────


def test_timescale_briefing_repo_satisfies_protocol() -> None:
    assert isinstance(briefing_default_repository, BriefingRepository)
    assert isinstance(TimescaleBriefingRepository(), BriefingRepository)


class _InMemoryBriefingRepository:
    """Reference fake implementation of :class:`BriefingRepository`."""

    def __init__(self) -> None:
        self.narratives: list[NarrativeRow] = []
        self.findings: list[tuple[str, FindingRow]] = []  # (finding_type, row)

    async def latest_narratives_by_type(
        self,
        session: Any,
        *,
        insight_types: Iterable[str] = ("daily_briefing", "weekly_summary"),
    ) -> dict[str, NarrativeRow]:
        wanted = set(insight_types)
        out: dict[str, NarrativeRow] = {}
        for row in self.narratives:
            if row.insight_type not in wanted:
                continue
            existing = out.get(row.insight_type)
            if existing is None or row.created_at > existing.created_at:
                out[row.insight_type] = row
        return out

    async def fetch_anomalies(
        self,
        session: Any,
        *,
        since: datetime | None = None,
        severities: Iterable[str] | None = None,
        limit: int = 200,
    ) -> list[FindingRow]:
        out = [r for ft, r in self.findings if ft == "anomaly"]
        if since is not None:
            out = [r for r in out if r.created_at >= since]
        if severities is not None:
            allow = set(severities)
            out = [r for r in out if r.severity in allow]
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out[:limit]

    async def fetch_trends(
        self,
        session: Any,
        *,
        period_days: str | None = None,
        limit: int = 200,
    ) -> list[FindingRow]:
        out = [r for ft, r in self.findings if ft == "trend"]
        if period_days is not None:
            out = [r for r in out if str(r.structured_data.get("period_days")) == period_days]
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out[:limit]

    async def fetch_correlations(
        self,
        session: Any,
        *,
        period_days: str | None = None,
        limit: int = 200,
    ) -> list[FindingRow]:
        out = [r for ft, r in self.findings if ft == "correlation"]
        if period_days is not None:
            out = [r for r in out if str(r.structured_data.get("period_days")) == period_days]
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out[:limit]

    async def fetch_findings(
        self,
        session: Any,
        *,
        finding_type: str | None = None,
        limit: int = 200,
    ) -> list[FindingRow]:
        out = [r for ft, r in self.findings if finding_type is None or ft == finding_type]
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out[:limit]


def test_in_memory_briefing_repo_satisfies_protocol() -> None:
    fake = _InMemoryBriefingRepository()
    assert isinstance(fake, BriefingRepository)


@pytest.mark.asyncio
async def test_in_memory_briefing_repo_walks_all_three_methods() -> None:
    """End-to-end: write narratives + findings, query each method,
    verify filters."""
    repo: BriefingRepository = _InMemoryBriefingRepository()

    repo.narratives.append(
        NarrativeRow(
            insight_type="daily_briefing",
            narrative="HRV stable",
            created_at=datetime(2026, 5, 10, 6, 0, tzinfo=UTC),
        )
    )
    # An older daily briefing — should be hidden by the newer one.
    repo.narratives.append(
        NarrativeRow(
            insight_type="daily_briefing",
            narrative="old",
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )

    repo.findings.append(
        (
            "anomaly",
            FindingRow(
                id=1,
                metric="hrv",
                severity="alert",
                structured_data={"magnitude": 2.4, "direction": "down"},
                created_at=datetime(2026, 5, 10, tzinfo=UTC),
            ),
        )
    )
    repo.findings.append(
        (
            "trend",
            FindingRow(
                id=2,
                metric="heart_rate",
                severity=None,
                structured_data={"slope": 0.42, "period_days": 30},
                created_at=datetime(2026, 5, 10, tzinfo=UTC),
            ),
        )
    )
    repo.findings.append(
        (
            "correlation",
            FindingRow(
                id=3,
                metric="vital.hrv_sdnn~vital.resting_heart_rate",
                severity=None,
                structured_data={"metric_a": "hrv", "metric_b": "rhr", "period_days": 90},
                created_at=datetime(2026, 5, 11, tzinfo=UTC),
            ),
        )
    )

    latest = await repo.latest_narratives_by_type(
        session=None, insight_types=("daily_briefing", "weekly_summary")
    )
    assert "daily_briefing" in latest
    assert latest["daily_briefing"].narrative == "HRV stable"
    assert "weekly_summary" not in latest

    anoms = await repo.fetch_anomalies(session=None)
    assert len(anoms) == 1 and anoms[0].metric == "hrv"

    trends = await repo.fetch_trends(session=None, period_days="30")
    assert len(trends) == 1 and trends[0].metric == "heart_rate"

    trends_none = await repo.fetch_trends(session=None, period_days="999")
    assert trends_none == []

    correlations = await repo.fetch_correlations(session=None, period_days="90")
    assert len(correlations) == 1 and correlations[0].id == 3

    findings = await repo.fetch_findings(session=None)
    assert [row.id for row in findings] == [3, 1, 2]

    only_trends = await repo.fetch_findings(session=None, finding_type="trend")
    assert [row.id for row in only_trends] == [2]


# ──────────────────────────────────────────────────────────────
#  IngestStorage + AuditLog + MeasurementRepository (Phase 5C)
# ──────────────────────────────────────────────────────────────


def test_postgres_ingest_storage_satisfies_protocol() -> None:
    from storage.timescale.ingest import (
        PostgresAuditLog,
        PostgresIngestStorage,
        default_audit_log,
        default_storage,
    )

    assert isinstance(default_storage, IngestStorage)
    assert isinstance(PostgresIngestStorage(), IngestStorage)
    assert isinstance(default_audit_log, AuditLog)
    assert isinstance(PostgresAuditLog(), AuditLog)


def test_v1_shim_re_exports_match_new_location() -> None:
    """The backwards-compat shim at ``server.ingestion.storage`` must
    re-export the same Protocol objects + default instances as the new
    home in ``storage.timescale.ingest``. Existing callers (registry,
    routes, tests) that import from the v1 path stay correct without
    churn."""
    from server.ingestion import storage as shim
    from storage.ports import AuditLog as PortAuditLog
    from storage.ports import IngestStorage as PortIngestStorage
    from storage.timescale.ingest import default_audit_log, default_storage

    assert shim.IngestStorage is PortIngestStorage
    assert shim.AuditLog is PortAuditLog
    assert shim.default_storage is default_storage
    assert shim.default_audit_log is default_audit_log


def test_measurement_repository_skeleton_satisfies_protocol() -> None:
    """Phase 5C ships an empty ``MeasurementRepository`` Protocol so
    consumers can begin depending on the type. Phase 5D fills in real
    methods. Today an empty class implements it because the Protocol
    has zero required methods."""
    from storage.timescale.measurements import (
        TimescaleMeasurementRepository,
        default_repository,
    )

    assert isinstance(default_repository, MeasurementRepository)
    assert isinstance(TimescaleMeasurementRepository(), MeasurementRepository)


def test_timescale_measurement_projection_repository_satisfies_protocol() -> None:
    from storage.timescale.measurements import (
        TimescaleMeasurementProjectionRepository,
        default_projection_repository,
    )

    assert isinstance(default_projection_repository, MeasurementProjectionRepository)
    assert isinstance(TimescaleMeasurementProjectionRepository(), MeasurementProjectionRepository)


@pytest.mark.asyncio
async def test_timescale_measurement_projection_projects_quantity_observations() -> None:
    from contracts._base import DEFAULT_OWNER_ID, Provenance
    from contracts.observation import Observation, build_dedup_key
    from contracts.values import QuantityValue
    from storage.timescale.measurements import TimescaleMeasurementProjectionRepository

    class _ProjectionResult:
        def __init__(self, row: dict[str, object]) -> None:
            self.row = row

        def mappings(self):
            return self

        def first(self):
            return self.row

    class _ProjectionSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        async def execute(self, statement, params=None):
            sql = " ".join(str(statement).split())
            self.calls.append((sql, params or {}))
            return _ProjectionResult({"inserted_new": True})

    observed_at = datetime(2026, 5, 11, 8, 0, tzinfo=UTC)
    obs = Observation(
        metric_id="vital.heart_rate",
        value=QuantityValue(
            type="quantity",
            value=72,
            unit="bpm",
            canonical_value=72,
            canonical_unit="bpm",
        ),
        interval_start=observed_at,
        interval_end=observed_at,
        source_id="a9b1e7e0-0000-4000-8000-000000000001",
        provenance=Provenance(
            source_plugin_id="apple-health-healthsave",
            sdk_version="test",
            captured_at=observed_at,
        ),
        normalizer_id="apple_health",
        normalizer_version="test",
        dedup_key=build_dedup_key(
            owner_id=DEFAULT_OWNER_ID,
            workspace_id=DEFAULT_OWNER_ID,
            source_id="a9b1e7e0-0000-4000-8000-000000000001",
            metric_id="vital.heart_rate",
            interval_start=observed_at,
            interval_end=observed_at,
            value_repr="72",
        ),
    )

    session = _ProjectionSession()
    result = await TimescaleMeasurementProjectionRepository().project_observations(
        session,
        7,
        "heart_rate",
        [obs],
        DEFAULT_OWNER_ID,
    )

    insert_params = next(params for sql, params in session.calls if "INSERT INTO heart_rate" in sql)
    assert result.accepted == 1
    assert insert_params["device_id"] == 7
    assert insert_params["time"] == observed_at
    assert insert_params["bpm"] == 72
    assert insert_params["owner_id"] == str(DEFAULT_OWNER_ID)


# ──────────────────────────────────────────────────────────────
#  Module-level convenience surface
# ──────────────────────────────────────────────────────────────


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


# ──────────────────────────────────────────────────────────────
#  Phase 5F: storage.timescale.analysis surface contract
# ──────────────────────────────────────────────────────────────


def test_analysis_module_exposes_expected_async_helpers() -> None:
    """Phase 5F lifts every analysis SQL function into
    ``storage.timescale.analysis``. This contract test pins the
    public function names + their async-ness so a future refactor
    cannot silently rename one out from under the analysis classes
    that import them via the lazy ``_sql()`` handle.
    """
    import inspect

    from storage.timescale import analysis as analysis_sql

    expected = {
        # analysis_runs lifecycle
        "begin_run",
        "mark_run_skipped",
        "mark_run_completed",
        "mark_run_failed",
        "insert_finding",
        "insert_insight",
        "within_cooldown",
        "fetch_recent_anomaly_findings",
        # period summaries
        "hr_summary_from_hourly",
        "hr_summary_from_raw",
        "hrv_summary",
        # anomaly observation fetches
        "fetch_hr_observations",
        "fetch_hrv_observations",
        "fetch_workouts",
        # trend daily-value fetches
        "fetch_heart_rate_daily_from_hourly",
        "fetch_heart_rate_daily_from_raw",
        "fetch_hrv_daily",
    }

    actual = {
        name
        for name in dir(analysis_sql)
        if not name.startswith("_") and callable(getattr(analysis_sql, name))
    }
    # Filter out anything that came in via stdlib re-exports (datetime,
    # etc.) — only count names defined in this module.
    actual_in_module = {
        name
        for name in actual
        if getattr(analysis_sql, name).__module__ == "storage.timescale.analysis"
    }

    missing = expected - actual_in_module
    assert not missing, f"storage.timescale.analysis is missing helpers: {sorted(missing)}"

    for name in expected:
        fn = getattr(analysis_sql, name)
        assert inspect.iscoroutinefunction(fn), (
            f"storage.timescale.analysis.{name} must be async — analysis classes await it"
        )


# ──────────────────────────────────────────────────────────────
#  TimeSeriesQueryService (Phase 5D) — the read port
# ──────────────────────────────────────────────────────────────


def test_canonical_repo_satisfies_timeseries_query_service() -> None:
    """The real read path — ``CanonicalObservationRepository.query_series``
    — satisfies the read port with no changes. This is the seam the
    analysis engine and the v2 API depend on."""
    from storage.timescale.observations import CanonicalObservationRepository

    assert isinstance(CanonicalObservationRepository(), TimeSeriesQueryService)


def test_canonical_repo_satisfies_observation_repository() -> None:
    """The canonical store adapter is also the ingest write port."""
    from storage.ports import ObservationRepository
    from storage.timescale.observations import CanonicalObservationRepository

    assert isinstance(CanonicalObservationRepository(), ObservationRepository)


class _InMemoryTimeSeriesQueryService:
    """Reference fake — proves the read port is genuinely swappable, not
    TimescaleDB-coupled. Mirrors the SQL window semantics: half-open
    ``[start, end)``, ascending, limit-capped."""

    def __init__(self) -> None:
        self.points: list[tuple[str, SeriesPoint]] = []  # (metric_id, point)

    async def query_series(
        self,
        session: Any,
        *,
        owner_id: Any,
        workspace_id: Any,
        metric_id: str,
        start: datetime,
        end: datetime,
        limit: int = 5000,
    ) -> list[SeriesPoint]:
        out = [p for mid, p in self.points if mid == metric_id and start <= p.t < end]
        out.sort(key=lambda p: p.t)
        return out[:limit]


def test_in_memory_timeseries_query_service_satisfies_protocol() -> None:
    """The whole point of the port — a fake reference impl conforms."""
    assert isinstance(_InMemoryTimeSeriesQueryService(), TimeSeriesQueryService)


@pytest.mark.asyncio
async def test_in_memory_timeseries_query_filters_window_and_metric() -> None:
    """Behavioral contract: half-open window ``[start, end)``, other metrics
    excluded, results ascending by ``t``."""
    repo: TimeSeriesQueryService = _InMemoryTimeSeriesQueryService()

    def point(day: int, value: float) -> SeriesPoint:
        t = datetime(2026, 5, day, tzinfo=UTC)
        return SeriesPoint(
            t=t,
            interval_end=t,
            value=value,
            code=None,
            unit="bpm",
            source_id="watch",
            confidence=None,
        )

    repo.points = [
        ("vital.heart_rate", point(5, 62.0)),
        ("vital.heart_rate", point(1, 60.0)),
        ("vital.heart_rate", point(20, 64.0)),  # outside the window
        ("sleep.stage", point(5, 1.0)),  # wrong metric
    ]

    got = await repo.query_series(
        session=None,
        owner_id=None,
        workspace_id=None,
        metric_id="vital.heart_rate",
        start=datetime(2026, 5, 1, tzinfo=UTC),
        end=datetime(2026, 5, 10, tzinfo=UTC),
    )

    assert [p.value for p in got] == [60.0, 62.0]


# ──────────────────────────────────────────────────────────────
#  Route read repositories (readiness + sync receipts)
# ──────────────────────────────────────────────────────────────


def test_timescale_readiness_repo_satisfies_protocol() -> None:
    from storage.timescale.analysis import (
        TimescaleReadinessRepository,
        default_readiness_repository,
    )

    assert isinstance(default_readiness_repository, ReadinessRepository)
    assert isinstance(TimescaleReadinessRepository(), ReadinessRepository)


def test_timescale_sync_receipt_repo_satisfies_protocol() -> None:
    from storage.timescale.sync_receipts import (
        TimescaleSyncReceiptRepository,
    )
    from storage.timescale.sync_receipts import (
        default_repository as sync_receipt_default_repository,
    )

    assert isinstance(sync_receipt_default_repository, SyncReceiptRepository)
    assert isinstance(TimescaleSyncReceiptRepository(), SyncReceiptRepository)
