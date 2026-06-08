# SPDX-License-Identifier: Apache-2.0
"""Tagged value shapes for canonical health observations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

# pydantic-core 2.9 only special-cases ``typing_extensions.TypeAliasType`` for
# recursive schema generation; the ``typing`` variant (Python 3.12 native)
# raises PydanticSchemaGenerationError here. ruff's UP035 "import from typing"
# is therefore suppressed on this line — it would break the runtime.
from typing_extensions import TypeAliasType  # noqa: UP035

from ._base import V2Model
from .ontology import ExternalCoding, MetricId

# Recursive JSON shape for free-form payloads. Built with ``TypeAliasType``
# (not the PEP 695 ``type`` statement, and not a bare alias): pydantic-core
# 2.9 needs a *named* recursive type so it can emit a definition reference and
# break the cycle. A plain alias recurses forever (RecursionError) and the
# ``type JsonData = ...`` form fails schema generation outright in this
# pydantic version (PydanticSchemaGenerationError) — so ruff's UP040 autofix
# would reintroduce a runtime bug and is suppressed here on purpose. The
# classes embedding ``JsonData`` resolve the forward ref via
# ``model_rebuild()`` below.
JsonData = TypeAliasType(  # noqa: UP040
    "JsonData",
    "str | int | float | bool | None | list[JsonData] | dict[str, JsonData]",
)


class QuantityValue(V2Model):
    """A scalar numeric value with explicit source and canonical units."""

    type: Literal["quantity"]
    value: float
    unit: str
    canonical_value: float
    canonical_unit: str


class CodedValue(V2Model):
    """A categorical value resolved to one canonical code."""

    type: Literal["categorical"]
    code: str
    label: str
    coding: list[ExternalCoding] = Field(default_factory=list)


class BooleanValue(V2Model):
    """A boolean yes/no value."""

    type: Literal["boolean"]
    value: bool


class ObservationComponent(V2Model):
    """One named component within a composite observation value."""

    metric_id: MetricId
    value: ObservationValue


class ComponentValue(V2Model):
    """A composite value such as blood pressure with named sub-values."""

    type: Literal["components"]
    components: list[ObservationComponent] = Field(min_length=1)


class EventValue(V2Model):
    """An interval or session-like observation without a scalar payload."""

    type: Literal["event"]
    label: str | None = None
    status: Literal["planned", "in_progress", "completed", "cancelled"] | None = None
    summary: dict[str, JsonData] = Field(default_factory=dict)


class WaveformValue(V2Model):
    """A blob-backed waveform with metadata but no inline sample array."""

    type: Literal["waveform"]
    blob_ref: str
    content_type: str
    sample_rate_hz: float
    channel_count: int
    duration_ms: int
    summary: dict[str, JsonData] = Field(default_factory=dict)


class JsonValue(V2Model):
    """A structured JSON payload when no stronger canonical shape exists."""

    type: Literal["json"]
    value: JsonData


ObservationValue = Annotated[
    QuantityValue
    | CodedValue
    | BooleanValue
    | ComponentValue
    | EventValue
    | WaveformValue
    | JsonValue,
    Field(discriminator="type"),
]

ObservationComponent.model_rebuild()
ComponentValue.model_rebuild()
EventValue.model_rebuild()
WaveformValue.model_rebuild()
JsonValue.model_rebuild()

__all__ = [
    "BooleanValue",
    "CodedValue",
    "ComponentValue",
    "EventValue",
    "JsonValue",
    "ObservationComponent",
    "ObservationValue",
    "QuantityValue",
    "WaveformValue",
]
