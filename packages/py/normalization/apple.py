"""Apple Health -> canonical Observation normalizer (ontology-driven).

Takes a ``POST /api/apple/batch`` payload (the locked v1 wire shape the
HealthSave iOS app sends) and emits canonical Observations. The wire metric
name is resolved to a canonical metric through the registry's apple_healthkit
source mappings, and the metric's value_type decides how each sample is shaped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID, Provenance
from contracts.observation import Observation, build_dedup_key
from contracts.ontology import REGISTRY, MetricDefinition
from contracts.values import CodedValue, EventValue, ObservationValue, QuantityValue

NORMALIZER_ID = "apple_health"
NORMALIZER_VERSION = "0.1.0"

_TIME_KEYS = ("date", "startDate", "start", "start_date")
_END_KEYS = ("endDate", "end", "end_date")
_VALUE_KEYS = ("qty", "value")


def _apple_wire_index() -> dict[str, MetricDefinition]:
    """wire metric name -> canonical metric, via apple_healthkit source mappings."""
    index: dict[str, MetricDefinition] = {}
    for metric in REGISTRY.values():
        for mapping in metric.source_mappings:
            if mapping.source == "apple_healthkit":
                index[mapping.source_metric] = metric
    return index


_WIRE_INDEX = _apple_wire_index()


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
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _first(sample: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if sample.get(key) is not None:
            return sample[key]
    return None


def _map_code(metric: MetricDefinition, raw: Any) -> str | None:
    """Resolve a raw categorical value to a canonical code.

    Accepts either a source-vocabulary value (mapped via value_map) or a value
    that is already a canonical code (e.g. iOS sends short ``"core"`` directly).
    """
    raw_str = str(raw)
    for mapping in metric.source_mappings:
        if mapping.source == "apple_healthkit" and raw_str in mapping.value_map:
            return mapping.value_map[raw_str]
    if any(code.code == raw_str for code in metric.allowed_codes):
        return raw_str
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
    return Observation(
        owner_id=owner_id,
        workspace_id=workspace_id,
        metric_id=metric.id,
        value=value,
        interval_start=start,
        interval_end=end,
        source_id=source_id,
        device_id=device_id,
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
