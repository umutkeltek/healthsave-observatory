"""Canonical Observation record tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from contracts._base import Provenance
from contracts.observation import Observation, build_dedup_key
from contracts.values import QuantityValue

_T = datetime(2026, 5, 28, 8, 0, tzinfo=UTC)
_PROV = Provenance(source_plugin_id="apple_health", sdk_version="0.1.0", captured_at=_T)
_SOURCE = UUID("11111111-1111-1111-1111-111111111111")


def _obs() -> Observation:
    return Observation(
        metric_id="vital.heart_rate",
        value=QuantityValue(
            type="quantity", value=61.0, unit="bpm", canonical_value=61.0, canonical_unit="bpm"
        ),
        interval_start=_T,
        interval_end=_T,
        source_id=_SOURCE,
        provenance=_PROV,
        normalizer_id="apple_health",
        normalizer_version="0.1.0",
        dedup_key="abc",
    )


def test_observation_defaults_owner_and_ontology() -> None:
    obs = _obs()
    assert obs.owner_id == UUID("00000000-0000-0000-0000-000000000001")
    assert obs.ontology_version == "2026.05.0"
    assert obs.value.type == "quantity"
    assert obs.value.value == 61.0


def test_observation_round_trips_through_json() -> None:
    obs = _obs()
    restored = Observation.model_validate_json(obs.model_dump_json())
    assert restored.metric_id == "vital.heart_rate"
    assert restored.value.type == "quantity"
    assert restored.value.canonical_unit == "bpm"


def test_build_dedup_key_is_deterministic_and_uid_preferring() -> None:
    common = dict(
        owner_id=_SOURCE,
        workspace_id=_SOURCE,
        source_id=_SOURCE,
        metric_id="vital.heart_rate",
        interval_start=_T,
        interval_end=_T,
    )
    a = build_dedup_key(**common, value_repr="61")
    b = build_dedup_key(**common, value_repr="61")
    c = build_dedup_key(**common, value_repr="62")
    assert a == b
    assert a != c
    # source_record_uid takes precedence and ignores value differences
    u1 = build_dedup_key(**common, source_record_uid="rec-1", value_repr="61")
    u2 = build_dedup_key(**common, source_record_uid="rec-1", value_repr="999")
    assert u1 == u2
