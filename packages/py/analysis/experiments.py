"""Experiment runtime — composes time-series ports, pure ABAB stats, and persistence.

Brain-1 orchestration for the n-of-1 engine: pull an experiment's outcome (and
lever) daily series from the canonical store, run the pure
:mod:`analysis.statistical.experiments` analysis, and persist the result. No LLM
in this layer — a result is structured evidence; narration is a later, optional
brain. The two-brain seal holds: the stats are pure, the storage is the storage
zone, and this orchestrator only glues them.

Two entry points, one per result ``kind``:

* :meth:`ExperimentRunner.run_retrospective` — the instant observational read
  over existing history (lever median split). Best-effort: returns ``None`` when
  there isn't enough overlapping history yet (nothing persisted).
* :meth:`ExperimentRunner.run_controlled` — the ABAB result over the experiment
  window, plus an adherence read on the lever. Always persists (an early/thin
  run is honestly recorded as ``insufficient``), and flips the experiment to
  ``completed`` once its window has fully elapsed.

Storage is supplied through ports. Production construction uses
``storage.defaults``; tests can inject in-memory fakes or run with
``persist=False`` to exercise the full analysis without writing results.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID

from .statistical import experiments as stats

if TYPE_CHECKING:
    from storage.ports import ExperimentRepository, TimeSeriesQueryService

log = logging.getLogger("healthsave.analysis")

_RETROSPECTIVE_LOOKBACK_DAYS = 90
_SERIES_LIMIT = 50_000


def _default_time_series() -> TimeSeriesQueryService:
    from storage.defaults import time_series_query_service

    return time_series_query_service()


def _default_experiment_repository() -> ExperimentRepository:
    from storage.defaults import experiment_repository

    return experiment_repository()


def _midnight(d: date) -> datetime:
    """UTC midnight at the start of ``d`` — the half-open bounds the series SQL wants."""
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _pc_dict(pc: stats.PhaseComparison) -> dict[str, Any]:
    """Full PhaseComparison for the JSONB payload (powers the 'show calculation' view)."""
    return {
        "status": pc.status,
        "n_a": pc.n_a,
        "n_b": pc.n_b,
        "mean_a": pc.mean_a,
        "mean_b": pc.mean_b,
        "diff": pc.diff,
        "pooled_sd": pc.pooled_sd,
        "effect_size": pc.effect_size,
        "direction": pc.direction,
        "p_value": pc.p_value,
        "inference": pc.inference,
        "n_blocks_used": pc.n_blocks_used,
        "caveat": pc.caveat,
    }


def _adherence_dict(a: stats.AdherenceCheck) -> dict[str, Any]:
    return {
        "status": a.status,
        "lever_diff": a.lever_diff,
        "lever_effect_size": a.lever_effect_size,
        "note": a.note,
    }


@dataclass(frozen=True, slots=True)
class ComputedExperimentResult:
    """A computed experiment result before optional persistence."""

    kind: str
    direction: str | None
    diff: float | None
    effect_size: float | None
    p_value: float | None
    inference: str | None
    summary: str | None
    structured_data: dict[str, Any]


class ExperimentRunner:
    """Orchestrates one experiment's analysis against the canonical store.

    Stateless apart from the session factory; safe to construct per request.
    """

    def __init__(
        self,
        session_factory,
        *,
        time_series: TimeSeriesQueryService | None = None,
        experiment_repository: ExperimentRepository | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.time_series = time_series or _default_time_series()
        self.experiment_repository = experiment_repository or _default_experiment_repository()

    async def _series(
        self, session, metric_id: str, start: datetime, end: datetime
    ) -> dict[date, float]:
        """``{day: daily_mean}`` for a metric over ``[start, end)`` via the time-series port."""
        rows = await self.time_series.query_series(
            session,
            owner_id=DEFAULT_OWNER_ID,
            workspace_id=DEFAULT_WORKSPACE_ID,
            metric_id=metric_id,
            start=start,
            end=end,
            limit=_SERIES_LIMIT,
        )
        values_by_day: dict[date, list[float]] = {}
        for row in rows:
            value = getattr(row, "value", None)
            t = getattr(row, "t", None)
            if value is None or t is None:
                continue
            day = t.date() if isinstance(t, datetime) else t
            values_by_day.setdefault(day, []).append(float(value))
        return {day: statistics.fmean(values) for day, values in values_by_day.items()}

    async def _persist_result(self, session, experiment_id, result: ComputedExperimentResult):
        return await self.experiment_repository.insert_result(
            session,
            experiment_id=experiment_id,
            kind=result.kind,
            direction=result.direction,
            diff=result.diff,
            effect_size=result.effect_size,
            p_value=result.p_value,
            inference=result.inference,
            summary=result.summary,
            structured_data=result.structured_data,
        )

    async def run_retrospective(
        self,
        experiment,
        *,
        as_of: date,
        lookback_days: int = _RETROSPECTIVE_LOOKBACK_DAYS,
        persist: bool = True,
    ):
        """Observational read over trailing history (lever median split).

        Returns the persisted :class:`ExperimentResultRow`, or ``None`` when
        there isn't enough overlapping history to compare high- vs low-lever days
        (nothing is written).
        """
        end_dt = _midnight(as_of + timedelta(days=1))  # include today
        start_dt = end_dt - timedelta(days=lookback_days)

        async with self.session_factory() as session:
            outcome = await self._series(session, experiment.outcome_metric_id, start_dt, end_dt)
            lever = await self._series(session, experiment.lever_metric_id, start_dt, end_dt)

            pc = stats.analyze_median_split(outcome, lever)
            if pc.status != "ok":
                return None

            summary = stats.summarize(
                pc,
                outcome_short=stats._short(experiment.outcome_metric_id),
                period_phrase=f"high-{stats._short(experiment.lever_metric_id)} days",
            )
            computed = ComputedExperimentResult(
                kind="retrospective",
                direction=pc.direction,
                diff=pc.diff,
                effect_size=pc.effect_size,
                p_value=pc.p_value,
                inference=pc.inference,
                summary=summary,
                structured_data={
                    "outcome": _pc_dict(pc),
                    "lookback_days": lookback_days,
                    "method": "lever_median_split",
                },
            )
            if not persist:
                return computed

            result = await self._persist_result(session, experiment.id, computed)
            await session.commit()
            return result

    async def run_controlled(self, experiment, *, as_of: date, persist: bool = True):
        """Controlled ABAB result over the experiment window + a lever adherence read.

        Always persists a ``controlled`` result (a thin/early run records
        ``insufficient`` honestly). Flips ``collecting`` → ``completed`` once the
        window has fully elapsed.
        """
        calendar = stats.build_phase_calendar(
            experiment.start_date, experiment.block_days, experiment.design
        )
        window_start, window_end = stats.experiment_window(calendar)
        prog = stats.progress(calendar, as_of)

        # Read only within the window, up to and including today.
        effective_end = window_end if prog.is_complete else (as_of + timedelta(days=1))
        start_dt = _midnight(window_start)
        end_dt = _midnight(min(window_end, effective_end))

        async with self.session_factory() as session:
            outcome = await self._series(session, experiment.outcome_metric_id, start_dt, end_dt)
            lever = await self._series(session, experiment.lever_metric_id, start_dt, end_dt)

            pc = stats.analyze_abab(outcome, calendar)
            adherence = stats.adherence_from_lever(lever, calendar)
            summary = stats.summarize(
                pc,
                outcome_short=stats._short(experiment.outcome_metric_id),
                period_phrase="intervention blocks",
            )
            computed = ComputedExperimentResult(
                kind="controlled",
                direction=pc.direction,
                diff=pc.diff,
                effect_size=pc.effect_size,
                p_value=pc.p_value,
                inference=pc.inference,
                summary=summary,
                structured_data={
                    "outcome": _pc_dict(pc),
                    "adherence": _adherence_dict(adherence),
                    "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
                    "design": experiment.design,
                    "block_days": experiment.block_days,
                },
            )
            if not persist:
                return computed

            result = await self._persist_result(session, experiment.id, computed)
            if prog.is_complete and experiment.status == "collecting":
                await self.experiment_repository.set_status(
                    session, experiment_id=experiment.id, status="completed"
                )
            await session.commit()
            return result
