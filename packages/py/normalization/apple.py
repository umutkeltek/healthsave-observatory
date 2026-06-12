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
from .parsers import sample_device_name

NORMALIZER_ID = "apple_health"
NORMALIZER_VERSION = "0.1.0"

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
                key: value
                for key, value in sample.items()
                if key not in (*_TIME_KEYS, *_END_KEYS)
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

    source_record_uid = _first(sample, "uuid", "id", "source_record_uid")
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
    # Resolve the per-sample stream identity from its origin. Use sample_device_name
    # so the stream_id stored on the observation is byte-identical to the registry's
    # source_device_streams.id for the same emitter (record_origins uses the same key).
    stream = identity.resolve_apple_origin(owner_id, sample_device_name(sample))
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
        raw_payload_id=raw_payload_id,
        source_record_uid=str(source_record_uid) if source_record_uid else None,
        provenance=provenance,
        normalizer_id=NORMALIZER_ID,
        normalizer_version=NORMALIZER_VERSION,
        dedup_key=dedup_key,
    )


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
