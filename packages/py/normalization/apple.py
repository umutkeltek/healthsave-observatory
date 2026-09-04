"""Apple Health -> canonical Observation normalizer (ontology-driven).

Takes a ``POST /api/apple/batch`` payload (the locked v1 wire shape the
HealthSave iOS app sends) and emits canonical Observations. The wire metric
name is resolved to a canonical metric through the registry's apple_healthkit
source mappings, and the metric's value_type decides how each sample is shaped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID, Provenance
from contracts.observation import Observation, build_dedup_key
from contracts.ontology import REGISTRY, MetricDefinition
from contracts.values import CodedValue, EventValue, ObservationValue, QuantityValue

from . import identity
from .fusion import AggregationScope
from .fusion import exact_ingest_key as build_exact_ingest_key
from .parsers import sample_device_name

NORMALIZER_ID = "apple_health"
NORMALIZER_VERSION = "0.4.0"

# HealthSave's iOS client sends the daily activity-ring totals bundled into a
# single wire metric ("activity_summaries") rather than as per-metric quantity
# batches (the shape every other wire metric — including the *same* totals
# sent individually, e.g. `active_energy_burned` — uses). Because
# `_apple_wire_index()` only indexes source_metric names declared on
# individual MetricDefinitions, "activity_summaries" itself never resolves to
# a canonical metric, so `normalize_apple_batch` silently produced zero
# observations for it (BUG-2026-08: dual-write divergence, canonical_accepted
# always 0 while the daily_activity projection kept writing correctly).
#
# Fix: unpack each activity_summaries sample into its constituent wire-metric
# fields and re-run them through the normal per-metric path below, so they
# land in canonical_observations exactly like a standalone quantity batch for
# the same wire name would.
_ACTIVITY_SUMMARY_WIRE = "activity_summaries"
# Only fields whose HealthKit semantics match the canonical metric's unit
# 1:1 are auto-expanded here. `appleStandHours` is a 0-24 COUNT of hours with
# any standing activity (matches the iOS Activity ring's "Stand" number), not
# a minutes total — mapping it straight into `activity.stand_minutes` (unit
# "min") would silently corrupt the value (e.g. reporting 9 hours as "9 min
# stood"). That needs its own canonical metric/ontology fix, not a blind
# field rename, so it is intentionally left unmapped here.
_ACTIVITY_SUMMARY_FIELD_TO_WIRE_METRIC: dict[str, str] = {
    "activeEnergyBurned": "active_energy_burned",
    "appleExerciseTime": "apple_exercise_time",
}

_HEALTHKIT_STATISTICS_ORIGIN = "HealthKit Statistics"
_HEALTHKIT_STATISTICS_ORIGIN_KEY = identity.normalize_origin(_HEALTHKIT_STATISTICS_ORIGIN)
_DAILY_TOTAL_OBJECT_TYPE = "apple_healthkit_daily_total"

_TIME_KEYS = ("date", "startDate", "start", "start_date")
_END_KEYS = ("endDate", "end", "end_date")
_VALUE_KEYS = ("qty", "value")
_MEDICATION_STATUSES = {
    "taken",
    "skipped",
    "not_interacted",
    "snoozed",
    "notification_not_sent",
    "not_logged",
    "unknown",
}
_MEDICATION_EVENT_STATUS = {
    "taken": "completed",
    "skipped": "completed",
    "not_interacted": "in_progress",
    "snoozed": "in_progress",
    "notification_not_sent": "in_progress",
    "not_logged": "planned",
    "unknown": "planned",
}


def _apple_wire_index() -> dict[str, MetricDefinition]:
    """wire metric name -> canonical metric, via apple_healthkit source mappings."""
    index: dict[str, MetricDefinition] = {}
    for metric in REGISTRY.values():
        for mapping in metric.source_mappings:
            if mapping.source == "apple_healthkit":
                index[mapping.source_metric] = metric
    return index


_WIRE_INDEX = _apple_wire_index()


def mapped_apple_wire_metrics() -> set[str]:
    """Apple wire metric names the normalizer can map to a canonical metric.

    Any metric the v1 ingest path accepts that is NOT in this set silently
    writes zero canonical observations — the dual-write coverage gap that
    ``server.ingestion.coverage`` surfaces (ADR-0001 divergence risk).
    """
    return set(_WIRE_INDEX)


def apple_wire_metric(wire: str) -> MetricDefinition | None:
    """Resolve an Apple wire metric name to its canonical definition.

    Public seam for wire-level gates that need the ontology's per-metric
    contract (the v2 ingest route's unit gate reads ``allowed_units``,
    Plan 2026-09-03 Slice 2). Returns None for wire names the ontology
    does not know — callers stay lenient on unmapped metrics, exactly
    like ``normalize_apple_batch`` (unmapped batches become per-sample
    rejections, never a route-level 422).
    """
    return _WIRE_INDEX.get(wire)


@dataclass
class Rejection:
    """One sample the normalizer could not turn into an observation."""

    reason: str
    sample: dict[str, Any]


@dataclass
class NormalizeResult:
    """Honest accounting: what became canonical, what was rejected and why."""

    observations: list[Observation] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def accepted(self) -> int:
        return len(self.observations)

    @property
    def rejected(self) -> int:
        return len(self.rejections)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # DATA-001: assume UTC for offset-less inputs so canonical Observations never
    # carry a naive interval_start/end (TIMESTAMPTZ). No-op for the normal Z path.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _first(sample: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if sample.get(key) is not None:
            return sample[key]
    return None


def _epoch_microseconds(value: datetime) -> int:
    """Absolute timestamp identity without depending on its serialized UTC offset."""
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value.astimezone(UTC) - epoch
    return ((delta.days * 86_400 + delta.seconds) * 1_000_000) + delta.microseconds


def _map_code(metric: MetricDefinition, raw: Any) -> str | None:
    """Resolve a raw categorical value to a canonical code.

    Accepts either a source-vocabulary value (mapped via value_map) or a value
    that is already a canonical code. Matching is **case-insensitive**: Apple
    HealthKit emits capitalized sleep stages (``"Core"``/``"Deep"``/``"REM"``)
    while the ontology codes are lowercase, and a case-sensitive lookup silently
    rejected every real sleep sample (``unmappable_code``) — a data-loss bug.
    Exact matches are tried first so any intentionally case-distinct mapping wins.
    """
    raw_str = str(raw)
    folded = raw_str.casefold()
    for mapping in metric.source_mappings:
        if mapping.source != "apple_healthkit":
            continue
        if raw_str in mapping.value_map:
            return mapping.value_map[raw_str]
        for key, code in mapping.value_map.items():
            if key.casefold() == folded:
                return code
    for code in metric.allowed_codes:
        if code.code.casefold() == folded:
            return code.code
    return None


def _label_for(metric: MetricDefinition, code: str) -> str | None:
    for definition in metric.allowed_codes:
        if definition.code == code:
            return definition.label
    return None


def _build_value(
    metric: MetricDefinition, sample: dict[str, Any]
) -> tuple[ObservationValue | None, str]:
    """Return (value, reason). value is None when the sample is unusable."""
    if metric.value_type == "quantity":
        qty = _to_float(_first(sample, *_VALUE_KEYS))
        if qty is None:
            return None, "missing_value"
        unit = str(_first(sample, "unit") or metric.canonical_unit)
        return (
            QuantityValue(
                type="quantity",
                value=qty,
                unit=unit,
                canonical_value=qty,
                canonical_unit=metric.canonical_unit or unit,
            ),
            "",
        )
    if metric.value_type == "categorical":
        raw = _first(sample, "value", "code", "category")
        if raw is None:
            return None, "missing_value"
        code = _map_code(metric, raw)
        if code is None:
            return None, f"unmappable_code:{raw}"
        return CodedValue(type="categorical", code=code, label=_label_for(metric, code)), ""
    if metric.value_type == "event":
        if metric.id == "medication.dose_event":
            status = str(_first(sample, "status", "medication_status") or "").strip()
            if status not in _MEDICATION_STATUSES:
                return None, f"unmappable_medication_status:{status}"
            summary = {
                key: value for key, value in sample.items() if key not in (*_TIME_KEYS, *_END_KEYS)
            }
            summary["status"] = status
            return (
                EventValue(
                    type="event",
                    label=str(_first(sample, "medication_name") or metric.display_name),
                    status=_MEDICATION_EVENT_STATUS[status],
                    summary=summary,
                ),
                "",
            )
        summary = {
            key: value for key, value in sample.items() if key not in (*_TIME_KEYS, *_END_KEYS)
        }
        return EventValue(type="event", label=metric.display_name, summary=summary), ""
    return None, f"unsupported_value_type:{metric.value_type}"


def _normalize_sample(
    sample: dict[str, Any],
    metric: MetricDefinition,
    *,
    source_id: UUID,
    provenance: Provenance,
    owner_id: UUID,
    workspace_id: UUID,
    device_id: UUID | None,
    raw_payload_id: UUID | None,
) -> Observation | Rejection:
    start = _parse_ts(_first(sample, *_TIME_KEYS))
    if start is None:
        return Rejection("missing_or_unparseable_time", sample)
    end = _parse_ts(_first(sample, *_END_KEYS)) or start

    value, reason = _build_value(metric, sample)
    if value is None:
        return Rejection(reason, sample)

    # Resolve the per-sample stream identity from its origin. Use sample_device_name
    # so the stream_id stored on the observation is byte-identical to the registry's
    # source_device_streams.id for the same emitter (record_origins uses the same key).
    sample_origin = sample_device_name(sample)
    stream = identity.resolve_apple_origin(owner_id, sample_origin)
    source_record_uid = _first(sample, "uuid", "id", "source_record_uid")
    exact_ingest_key: str | None = None
    aggregation_scope = AggregationScope.INTERVAL_COMPONENT.value

    # v2 capture context (Eric's asks #4 + #5): the wire's per-sample local
    # UTC offset and heart-rate motion context ride onto THIS observation's
    # provenance, not the batch-level one. The ingest route builds one
    # batch-scoped Provenance; we copy it and fill what this sample carried
    # so the values survive into canonical_observations.provenance JSONB and
    # become queryable. Samples that omitted the keys keep None (v1 and the
    # non-HR families).
    sample_tz = sample.get("tzOffsetMinutes")
    sample_motion = sample.get("motionContext")
    if sample_tz is not None or sample_motion is not None:
        provenance = provenance.model_copy(
            update={
                "tz_offset_minutes": sample_tz if isinstance(sample_tz, int) else None,
                "motion_context": sample_motion if isinstance(sample_motion, str) else None,
            }
        )

    # HealthSave's cumulative extractor sends one HealthKit-deduplicated, all-source
    # total per local calendar day. A later sync may revise that same total, so its
    # source-local identity must exclude the value while preserving the exact local-
    # midnight instant (04:00Z/05:00Z across New York DST, for example).
    if (
        metric.aggregation.kind == "daily_total"
        and value.type == "quantity"
        and stream.origin_key == _HEALTHKIT_STATISTICS_ORIGIN_KEY
    ):
        aggregation_scope = AggregationScope.OWNER_ALL_SOURCE_DAY_TOTAL.value
        exact_ingest_key = build_exact_ingest_key(
            owner_id,
            source_id,
            _DAILY_TOTAL_OBJECT_TYPE,
            fallback_fields=(
                workspace_id,
                metric.id,
                _epoch_microseconds(start),
                device_id or "",
                stream.stream_id,
            ),
        )
        dedup_key = build_dedup_key(
            owner_id=owner_id,
            workspace_id=workspace_id,
            source_id=source_id,
            metric_id=metric.id,
            interval_start=start,
            interval_end=end,
            device_id=device_id,
            source_record_uid=exact_ingest_key,
        )
    else:
        dedup_key = build_dedup_key(
            owner_id=owner_id,
            workspace_id=workspace_id,
            source_id=source_id,
            metric_id=metric.id,
            interval_start=start,
            interval_end=end,
            device_id=device_id,
            source_record_uid=source_record_uid,
            value_repr=value.model_dump_json(),
        )

    return Observation(
        owner_id=owner_id,
        workspace_id=workspace_id,
        metric_id=metric.id,
        value=value,
        interval_start=start,
        interval_end=end,
        source_id=source_id,
        device_id=device_id,
        stream_id=stream.stream_id,
        exact_ingest_key=exact_ingest_key,
        aggregation_scope=aggregation_scope,
        raw_payload_id=raw_payload_id,
        source_record_uid=str(source_record_uid) if source_record_uid else None,
        provenance=provenance,
        normalizer_id=NORMALIZER_ID,
        normalizer_version=NORMALIZER_VERSION,
        dedup_key=dedup_key,
    )


def _expand_activity_summary_sample(sample: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Split one activity_summaries sample into (wire_metric, single-field sample) pairs.

    Each HealthKit "*Goal" companion field and unrecognized keys are dropped —
    they carry no canonical metric of their own. The date/source keys are
    preserved on every derived sample so ``_normalize_sample`` sees the same
    timestamp/origin it would for a standalone quantity batch.

    The bundled activity summary is HealthKit's own deduplicated, all-source
    daily rollup (identical in kind to the `step_count`/`active_energy_burned`
    batches the client sends tagged ``source: "HealthKit Statistics"``), but
    the summary payload omits that source tag. We stamp it on so the derived
    samples take the stable daily-total identity path in ``_normalize_sample``
    — otherwise a later sync that revises the day's total would append a second
    observation instead of replacing the first (value_repr-based dedup_key).
    """
    shared_keys = {*_TIME_KEYS, *_END_KEYS, "source", "sourceName", "device", "deviceName"}
    shared = {key: value for key, value in sample.items() if key in shared_keys}
    if not any(shared.get(k) for k in ("source", "sourceName", "device", "deviceName")):
        shared["source"] = _HEALTHKIT_STATISTICS_ORIGIN
    expanded: list[tuple[str, dict[str, Any]]] = []
    for field_name, wire_metric in _ACTIVITY_SUMMARY_FIELD_TO_WIRE_METRIC.items():
        if sample.get(field_name) is None:
            continue
        expanded.append((wire_metric, {**shared, "qty": sample[field_name]}))
    return expanded


def normalize_apple_batch(
    payload: dict[str, Any],
    *,
    source_id: UUID,
    provenance: Provenance,
    owner_id: UUID = DEFAULT_OWNER_ID,
    workspace_id: UUID = DEFAULT_WORKSPACE_ID,
    device_id: UUID | None = None,
    raw_payload_id: UUID | None = None,
) -> NormalizeResult:
    """Normalize one Apple batch payload into canonical Observations."""
    result = NormalizeResult()
    payload = payload or {}
    wire = payload.get("metric")
    samples = payload.get("samples") or []

    # activity_summaries bundles several daily totals into one sample per day
    # instead of one wire metric per field; unpack before the normal single-
    # metric routing below so each total still resolves to its own canonical
    # metric (see _ACTIVITY_SUMMARY_FIELD_TO_WIRE_METRIC for why this exists).
    if wire == _ACTIVITY_SUMMARY_WIRE:
        for sample in samples:
            if not isinstance(sample, dict):
                result.rejections.append(Rejection("sample_not_object", {"raw": sample}))
                continue
            derived = _expand_activity_summary_sample(sample)
            if not derived:
                result.rejections.append(Rejection("activity_summary_no_known_fields", sample))
                continue
            for wire_metric, derived_sample in derived:
                metric = _WIRE_INDEX.get(wire_metric)
                if metric is None:
                    result.rejections.append(
                        Rejection(f"unmapped_metric:{wire_metric}", derived_sample)
                    )
                    continue
                outcome = _normalize_sample(
                    derived_sample,
                    metric,
                    source_id=source_id,
                    provenance=provenance,
                    owner_id=owner_id,
                    workspace_id=workspace_id,
                    device_id=device_id,
                    raw_payload_id=raw_payload_id,
                )
                if isinstance(outcome, Rejection):
                    result.rejections.append(outcome)
                else:
                    result.observations.append(outcome)
        return result

    metric = _WIRE_INDEX.get(wire) if isinstance(wire, str) else None

    if metric is None:
        for sample in samples:
            result.rejections.append(Rejection(f"unmapped_metric:{wire}", sample))
        return result

    for sample in samples:
        if not isinstance(sample, dict):
            result.rejections.append(Rejection("sample_not_object", {"raw": sample}))
            continue
        outcome = _normalize_sample(
            sample,
            metric,
            source_id=source_id,
            provenance=provenance,
            owner_id=owner_id,
            workspace_id=workspace_id,
            device_id=device_id,
            raw_payload_id=raw_payload_id,
        )
        if isinstance(outcome, Rejection):
            result.rejections.append(outcome)
        else:
            result.observations.append(outcome)
    return result
