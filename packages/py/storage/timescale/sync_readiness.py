"""Decision-readiness projection for HealthSave sync coverage.

This module deliberately derives readiness from existing receipt and destination
coverage. It does not create another persistence surface; callers get one
machine-readable answer to "can this metric safely drive an automation now?"
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from normalization.mappers import DAILY_ACTIVITY_QUANTITY_FIELDS

DAILY_CUMULATIVE_METRICS = frozenset(
    {
        "activity_summaries",
        "apple_move_time",
        "apple_stand_hour",
        "apple_stand_time",
        *DAILY_ACTIVITY_QUANTITY_FIELDS.keys(),
    }
)

SLOW_SAMPLE_METRICS = frozenset(
    {
        "body_fat_percentage",
        "body_mass",
        "bmi",
        "lean_body_mass",
        "waist_circumference",
    }
)

SESSION_EVENT_METRICS = frozenset(
    {
        "sleep_analysis",
        "workouts",
        "medication_dose_event",
    }
)

DEFAULT_LATEST_SAMPLE_SLA = timedelta(hours=6)
DAILY_CUMULATIVE_SLA = timedelta(minutes=45)
SLOW_SAMPLE_SLA = timedelta(days=7)
SESSION_EVENT_SLA = timedelta(hours=36)


@dataclass(frozen=True)
class MetricReadinessPolicy:
    category: str
    window_key: str
    freshness_sla: timedelta


def policy_for_metric(metric: str) -> MetricReadinessPolicy:
    if metric in DAILY_CUMULATIVE_METRICS:
        return MetricReadinessPolicy(
            category="daily_cumulative",
            window_key="today_local",
            freshness_sla=DAILY_CUMULATIVE_SLA,
        )
    if metric in SLOW_SAMPLE_METRICS:
        return MetricReadinessPolicy(
            category="latest_slow_sample",
            window_key="latest",
            freshness_sla=SLOW_SAMPLE_SLA,
        )
    if metric in SESSION_EVENT_METRICS:
        return MetricReadinessPolicy(
            category="session_event",
            window_key="latest_completed",
            freshness_sla=SESSION_EVENT_SLA,
        )
    return MetricReadinessPolicy(
        category="latest_sample",
        window_key="latest",
        freshness_sla=DEFAULT_LATEST_SAMPLE_SLA,
    )


def build_decision_readiness(
    coverage_rows: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    known_metrics: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build per-metric decision readiness from sync coverage rows."""

    generated_at = _as_utc(now or datetime.now(UTC))
    rows_by_metric = {str(row["metric"]): row for row in coverage_rows}
    metrics = sorted(set(known_metrics or known_contract_metrics()) | set(rows_by_metric))
    per_metric = [
        _readiness_for_metric(metric, rows_by_metric.get(metric), generated_at)
        for metric in metrics
    ]
    ready_count = sum(1 for row in per_metric if row["ready"])
    return {
        "schema_version": "2026-07-01",
        "generated_at": generated_at,
        "summary": {
            "metrics_known": len(per_metric),
            "metrics_ready": ready_count,
            "metrics_not_ready": len(per_metric) - ready_count,
        },
        "per_metric": per_metric,
    }


def _readiness_for_metric(
    metric: str,
    row: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    policy = policy_for_metric(metric)
    if row is None:
        return _readiness_row(
            metric=metric,
            policy=policy,
            ready=False,
            status="missing",
            reason="no_receipt_or_destination_data",
        )

    receipt_at = _parse_time(row.get("newest_receipt_at"))
    sample_window = row.get("receipt_sample_window") or {}
    source_window_start = _parse_time(sample_window.get("min_sample_time"))
    source_window_end = _parse_time(sample_window.get("max_sample_time"))
    materialized_at = _parse_time(row.get("latest_destination_sample_time"))
    coverage_state = row.get("freshness_state") or "unknown"
    observed_at = _observed_at_for_policy(
        policy=policy,
        coverage_state=str(coverage_state),
        receipt_at=receipt_at,
        source_window_end=source_window_end,
        materialized_at=materialized_at,
    )
    freshness_seconds = _freshness_seconds(now, observed_at)

    if coverage_state == "receipt_only":
        status = "receipt_only"
        reason = "receipt_has_not_materialized_in_destination"
    elif coverage_state == "stale_payload":
        status = "pending_materialization"
        reason = "destination_is_behind_receipt_sample_window"
    elif coverage_state == "unknown":
        status = "unknown"
        reason = "coverage_state_unknown"
    elif row.get("batches_processed", 0) == 0 and row.get("batches_seen", 0) > 0:
        status = "pending_processing"
        reason = "receipt_seen_but_not_processed"
    elif observed_at is None:
        status = "missing"
        reason = "no_observed_sample_window"
    elif freshness_seconds is not None and freshness_seconds > policy.freshness_sla.total_seconds():
        status = "stale"
        reason = "observed_sample_outside_freshness_sla"
    elif materialized_at is None:
        status = "receipt_only"
        reason = "destination_materialization_missing"
    else:
        status = "ready"
        reason = None

    return _readiness_row(
        metric=metric,
        policy=policy,
        ready=status == "ready",
        status=status,
        reason=reason,
        freshness_seconds=freshness_seconds,
        observed_at=observed_at,
        receipt_at=receipt_at,
        materialized_at=materialized_at,
        source_window_start=source_window_start,
        source_window_end=source_window_end,
        coverage_state=coverage_state,
    )


def _readiness_row(
    *,
    metric: str,
    policy: MetricReadinessPolicy,
    ready: bool,
    status: str,
    reason: str | None,
    freshness_seconds: int | None = None,
    observed_at: datetime | None = None,
    receipt_at: datetime | None = None,
    materialized_at: datetime | None = None,
    source_window_start: datetime | None = None,
    source_window_end: datetime | None = None,
    coverage_state: str | None = None,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "window_key": policy.window_key,
        "value": None,
        "unit": None,
        "ready": ready,
        "status": status,
        "reason": reason,
        "freshness_seconds": freshness_seconds,
        "observed_at": observed_at,
        "receipt_at": receipt_at,
        "materialized_at": materialized_at,
        "source_window_start": source_window_start,
        "source_window_end": source_window_end,
        "coverage_state": coverage_state,
        "policy": {
            "category": policy.category,
            "freshness_sla_seconds": int(policy.freshness_sla.total_seconds()),
        },
    }


def _observed_at_for_policy(
    *,
    policy: MetricReadinessPolicy,
    coverage_state: str,
    receipt_at: datetime | None,
    source_window_end: datetime | None,
    materialized_at: datetime | None,
) -> datetime | None:
    if (
        policy.category == "daily_cumulative"
        and coverage_state == "fresh"
        and materialized_at is not None
    ):
        return receipt_at or materialized_at
    return source_window_end or materialized_at


def _freshness_seconds(now: datetime, observed_at: datetime | None) -> int | None:
    if observed_at is None:
        return None
    return max(0, int((now - observed_at).total_seconds()))


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return _as_utc(datetime.fromisoformat(raw))
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@lru_cache(maxsize=1)
def known_contract_metrics() -> tuple[str, ...]:
    override = os.getenv("HEALTHSAVE_PARITY_MANIFEST")
    if override:
        path = Path(override).expanduser()
    else:
        path = _default_parity_manifest_path()
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    metrics = data.get("metrics") or {}
    return tuple(sorted(str(metric) for metric in metrics))


def _default_parity_manifest_path() -> Path:
    here = Path(__file__).resolve()
    parent_roots = [
        # Source checkout: datahub/packages/py/storage/timescale/sync_readiness.py
        # -> datahub/contracts/parity.json
        _parent_at(here, 4),
        # Docker runtime: /app/storage/timescale/sync_readiness.py
        # -> /app/contracts/parity.json
        _parent_at(here, 2),
        Path.cwd() / "contracts" / "parity.json",
    ]
    candidates = [
        root / "contracts" / "parity.json" if root.is_dir() else root
        for root in parent_roots
        if root is not None
    ]
    for path in candidates:
        if path.is_file():
            return path
    searched = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"HealthSave parity manifest not found; searched: {searched}")


def _parent_at(path: Path, index: int) -> Path | None:
    try:
        return path.parents[index]
    except IndexError:
        return None
