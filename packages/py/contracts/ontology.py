"""Versioned metric ontology registry for canonical health observations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ._base import V2Model

MetricId = str
OntologyVersion = str
ValueType = Literal[
    "quantity",
    "categorical",
    "boolean",
    "components",
    "event",
    "waveform",
    "json",
]


class ExternalCoding(V2Model):
    """A standards or vendor coding attached to a canonical concept."""

    system: str
    code: str
    display: str | None = None


class NumericRange(V2Model):
    """A numeric guardrail for metrics expressed on a scalar axis."""

    min_value: float | None = None
    max_value: float | None = None


class CodeDefinition(V2Model):
    """A canonical categorical code the metric may emit."""

    code: str
    label: str
    description: str | None = None
    codings: list[ExternalCoding] = Field(default_factory=list)


class AggregationSpec(V2Model):
    """Default rollup semantics for charting and summaries."""

    kind: Literal["instant", "daily_total", "summary", "event"]
    default_rollup: Literal["latest", "mean", "sum", "min", "max", "count", "none"]


class SourceVocabularyMapping(V2Model):
    """Maps a source-specific metric or code onto a canonical metric."""

    source: str
    source_metric: str
    value_map: dict[str, str] = Field(default_factory=dict)


class FusionPolicy(V2Model):
    """Default multi-source merge policy for the metric."""

    strategy: Literal["ranked_source", "weighted", "aggregate", "dedup"]
    source_priority: list[str] = Field(default_factory=list)
    weight_by_source: dict[str, float] = Field(default_factory=dict)
    aggregate_fn: Literal["latest", "mean", "sum", "min", "max"] | None = None


class MetricComponent(V2Model):
    """One named component within a multi-part metric."""

    metric_id: MetricId
    label: str
    canonical_unit: str | None = None


class MetricDefinition(V2Model):
    """One canonical registry entry describing a metric."""

    id: MetricId
    ontology_version: OntologyVersion
    display_name: str
    category: str
    value_type: ValueType
    canonical_unit: str | None = None
    allowed_units: list[str] = Field(default_factory=list)
    valid_range: NumericRange | None = None
    allowed_codes: list[CodeDefinition] = Field(default_factory=list)
    components: list[MetricComponent] = Field(default_factory=list)
    aggregation: AggregationSpec
    fusion: FusionPolicy
    source_mappings: list[SourceVocabularyMapping] = Field(default_factory=list)
    standards_mappings: list[ExternalCoding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_value_shape(self) -> MetricDefinition:
        """Keep the registry internally consistent for each value type."""

        if self.value_type == "quantity":
            if self.canonical_unit is None:
                msg = "quantity metrics require canonical_unit"
                raise ValueError(msg)
            if self.allowed_codes:
                msg = "quantity metrics cannot define allowed_codes"
                raise ValueError(msg)
            if self.components:
                msg = "quantity metrics cannot define components"
                raise ValueError(msg)
        elif self.value_type == "categorical":
            if self.allowed_codes == []:
                msg = "categorical metrics require allowed_codes"
                raise ValueError(msg)
            if self.canonical_unit is not None:
                msg = "categorical metrics cannot define canonical_unit"
                raise ValueError(msg)
            if self.components:
                msg = "categorical metrics cannot define components"
                raise ValueError(msg)
        elif self.value_type == "components":
            if self.components == []:
                msg = "components metrics require components"
                raise ValueError(msg)
            if self.canonical_unit is not None:
                msg = "components metrics cannot define canonical_unit"
                raise ValueError(msg)
            if self.allowed_codes:
                msg = "components metrics cannot define allowed_codes"
                raise ValueError(msg)
        elif self.value_type == "event":
            if self.canonical_unit is not None:
                msg = "event metrics cannot define canonical_unit"
                raise ValueError(msg)
            if self.allowed_codes:
                msg = "event metrics cannot define allowed_codes"
                raise ValueError(msg)
        else:
            if self.canonical_unit is not None:
                msg = f"{self.value_type} metrics cannot define canonical_unit"
                raise ValueError(msg)
            if self.allowed_codes:
                msg = f"{self.value_type} metrics cannot define allowed_codes"
                raise ValueError(msg)
            if self.components:
                msg = f"{self.value_type} metrics cannot define components"
                raise ValueError(msg)
        return self


ONTOLOGY_VERSION: OntologyVersion = "2026.05.0"

DEFAULT_FUSION = FusionPolicy(
    strategy="ranked_source",
    source_priority=["apple_healthkit", "oura", "whoop", "fitbit", "manual", "computed"],
)

SLEEP_STAGE_CODES = [
    CodeDefinition(code="awake", label="Awake"),
    CodeDefinition(code="rem", label="REM"),
    CodeDefinition(code="core", label="Core"),
    CodeDefinition(code="deep", label="Deep"),
]

REGISTRY: dict[MetricId, MetricDefinition] = {
    "vital.heart_rate": MetricDefinition(
        id="vital.heart_rate",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Heart Rate",
        category="vital",
        value_type="quantity",
        canonical_unit="bpm",
        allowed_units=["bpm"],
        valid_range=NumericRange(min_value=20.0, max_value=240.0),
        aggregation=AggregationSpec(kind="instant", default_rollup="mean"),
        fusion=DEFAULT_FUSION,
        source_mappings=[
            SourceVocabularyMapping(source="apple_healthkit", source_metric="HeartRate")
        ],
        standards_mappings=[ExternalCoding(system="loinc", code="8867-4", display="Heart rate")],
    ),
    "vital.hrv.sdnn": MetricDefinition(
        id="vital.hrv.sdnn",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Heart Rate Variability (SDNN)",
        category="vital",
        value_type="quantity",
        canonical_unit="ms",
        allowed_units=["ms"],
        valid_range=NumericRange(min_value=0.0, max_value=500.0),
        aggregation=AggregationSpec(kind="summary", default_rollup="mean"),
        fusion=DEFAULT_FUSION,
    ),
    "vital.resting_heart_rate": MetricDefinition(
        id="vital.resting_heart_rate",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Resting Heart Rate",
        category="vital",
        value_type="quantity",
        canonical_unit="bpm",
        allowed_units=["bpm"],
        valid_range=NumericRange(min_value=20.0, max_value=140.0),
        aggregation=AggregationSpec(kind="summary", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
    ),
    "vital.respiratory_rate": MetricDefinition(
        id="vital.respiratory_rate",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Respiratory Rate",
        category="vital",
        value_type="quantity",
        canonical_unit="breaths/min",
        allowed_units=["breaths/min"],
        valid_range=NumericRange(min_value=4.0, max_value=60.0),
        aggregation=AggregationSpec(kind="instant", default_rollup="mean"),
        fusion=DEFAULT_FUSION,
    ),
    "blood_oxygen": MetricDefinition(
        id="blood_oxygen",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Blood Oxygen Saturation",
        category="vital",
        value_type="quantity",
        canonical_unit="%",
        allowed_units=["%"],
        valid_range=NumericRange(min_value=0.0, max_value=100.0),
        aggregation=AggregationSpec(kind="instant", default_rollup="mean"),
        fusion=DEFAULT_FUSION,
        standards_mappings=[
            ExternalCoding(system="loinc", code="59408-5", display="Oxygen saturation")
        ],
    ),
    "sleep.stage": MetricDefinition(
        id="sleep.stage",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Sleep Stage",
        category="sleep",
        value_type="categorical",
        allowed_codes=SLEEP_STAGE_CODES,
        aggregation=AggregationSpec(kind="event", default_rollup="none"),
        fusion=FusionPolicy(
            strategy="dedup",
            source_priority=["apple_healthkit", "oura", "whoop", "fitbit"],
        ),
        source_mappings=[
            SourceVocabularyMapping(
                source="apple_healthkit",
                source_metric="SleepAnalysis",
                value_map={
                    "HKCategoryValueSleepAnalysisAwake": "awake",
                    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
                    "HKCategoryValueSleepAnalysisAsleepCore": "core",
                    "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
                },
            )
        ],
    ),
    "sleep.session": MetricDefinition(
        id="sleep.session",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Sleep Session",
        category="sleep",
        value_type="event",
        aggregation=AggregationSpec(kind="event", default_rollup="count"),
        fusion=FusionPolicy(
            strategy="ranked_source",
            source_priority=["oura", "whoop", "apple_healthkit", "fitbit", "manual"],
        ),
    ),
    "sleep.duration": MetricDefinition(
        id="sleep.duration",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Sleep Duration",
        category="sleep",
        value_type="quantity",
        canonical_unit="min",
        allowed_units=["min", "h"],
        valid_range=NumericRange(min_value=0.0, max_value=1440.0),
        aggregation=AggregationSpec(kind="summary", default_rollup="sum"),
        fusion=DEFAULT_FUSION,
    ),
    "activity.steps": MetricDefinition(
        id="activity.steps",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Steps",
        category="activity",
        value_type="quantity",
        canonical_unit="count",
        allowed_units=["count"],
        valid_range=NumericRange(min_value=0.0, max_value=100000.0),
        aggregation=AggregationSpec(kind="daily_total", default_rollup="sum"),
        fusion=FusionPolicy(
            strategy="aggregate",
            source_priority=["apple_healthkit", "fitbit", "garmin", "manual"],
            aggregate_fn="sum",
        ),
    ),
    "activity.energy.active": MetricDefinition(
        id="activity.energy.active",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Active Energy",
        category="activity",
        value_type="quantity",
        canonical_unit="kcal",
        allowed_units=["kcal", "kJ"],
        valid_range=NumericRange(min_value=0.0, max_value=20000.0),
        aggregation=AggregationSpec(kind="daily_total", default_rollup="sum"),
        fusion=DEFAULT_FUSION,
    ),
    "activity.distance": MetricDefinition(
        id="activity.distance",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Distance",
        category="activity",
        value_type="quantity",
        canonical_unit="m",
        allowed_units=["m", "km", "mi"],
        valid_range=NumericRange(min_value=0.0, max_value=500000.0),
        aggregation=AggregationSpec(kind="daily_total", default_rollup="sum"),
        fusion=DEFAULT_FUSION,
    ),
    "activity.floors_climbed": MetricDefinition(
        id="activity.floors_climbed",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Floors Climbed",
        category="activity",
        value_type="quantity",
        canonical_unit="count",
        allowed_units=["count"],
        valid_range=NumericRange(min_value=0.0, max_value=500.0),
        aggregation=AggregationSpec(kind="daily_total", default_rollup="sum"),
        fusion=DEFAULT_FUSION,
    ),
    "workout.session": MetricDefinition(
        id="workout.session",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Workout Session",
        category="activity",
        value_type="event",
        aggregation=AggregationSpec(kind="event", default_rollup="count"),
        fusion=FusionPolicy(
            strategy="dedup",
            source_priority=["apple_healthkit", "garmin", "strava", "manual"],
        ),
    ),
    "body.weight": MetricDefinition(
        id="body.weight",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Body Weight",
        category="body",
        value_type="quantity",
        canonical_unit="kg",
        allowed_units=["kg", "lb"],
        valid_range=NumericRange(min_value=0.0, max_value=500.0),
        aggregation=AggregationSpec(kind="summary", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
        standards_mappings=[ExternalCoding(system="loinc", code="29463-7", display="Body weight")],
    ),
    "body.fat_percent": MetricDefinition(
        id="body.fat_percent",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Body Fat Percentage",
        category="body",
        value_type="quantity",
        canonical_unit="%",
        allowed_units=["%"],
        valid_range=NumericRange(min_value=0.0, max_value=100.0),
        aggregation=AggregationSpec(kind="summary", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
    ),
    "blood_pressure.systolic": MetricDefinition(
        id="blood_pressure.systolic",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Systolic Blood Pressure",
        category="vital",
        value_type="quantity",
        canonical_unit="mmHg",
        allowed_units=["mmHg"],
        valid_range=NumericRange(min_value=40.0, max_value=300.0),
        aggregation=AggregationSpec(kind="instant", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
    ),
    "blood_pressure.diastolic": MetricDefinition(
        id="blood_pressure.diastolic",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Diastolic Blood Pressure",
        category="vital",
        value_type="quantity",
        canonical_unit="mmHg",
        allowed_units=["mmHg"],
        valid_range=NumericRange(min_value=20.0, max_value=200.0),
        aggregation=AggregationSpec(kind="instant", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
    ),
    "blood_pressure": MetricDefinition(
        id="blood_pressure",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Blood Pressure",
        category="vital",
        value_type="components",
        components=[
            MetricComponent(
                metric_id="blood_pressure.systolic",
                label="Systolic",
                canonical_unit="mmHg",
            ),
            MetricComponent(
                metric_id="blood_pressure.diastolic",
                label="Diastolic",
                canonical_unit="mmHg",
            ),
        ],
        aggregation=AggregationSpec(kind="instant", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
        standards_mappings=[
            ExternalCoding(system="loinc", code="85354-9", display="Blood pressure panel")
        ],
    ),
    "body_temperature": MetricDefinition(
        id="body_temperature",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Body Temperature",
        category="body",
        value_type="quantity",
        canonical_unit="degC",
        allowed_units=["degC", "degF"],
        valid_range=NumericRange(min_value=25.0, max_value=45.0),
        aggregation=AggregationSpec(kind="instant", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
    ),
    "recovery.score": MetricDefinition(
        id="recovery.score",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Recovery Score",
        category="recovery",
        value_type="quantity",
        canonical_unit="score",
        allowed_units=["score"],
        valid_range=NumericRange(min_value=0.0, max_value=100.0),
        aggregation=AggregationSpec(kind="summary", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
    ),
    "readiness.score": MetricDefinition(
        id="readiness.score",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Readiness Score",
        category="recovery",
        value_type="quantity",
        canonical_unit="score",
        allowed_units=["score"],
        valid_range=NumericRange(min_value=0.0, max_value=100.0),
        aggregation=AggregationSpec(kind="summary", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
    ),
}


def get_metric(metric_id: MetricId) -> MetricDefinition | None:
    """Return one registry entry, or ``None`` when it is unknown."""

    return REGISTRY.get(metric_id)


def all_metrics() -> list[MetricDefinition]:
    """Return every metric definition in registry order."""

    return list(REGISTRY.values())


def export_registry() -> dict[str, object]:
    """Return the registry as plain JSON-safe Python data."""

    metrics = {metric_id: metric.model_dump(mode="json") for metric_id, metric in REGISTRY.items()}
    return {
        "ontology_version": ONTOLOGY_VERSION,
        "metrics": metrics,
    }


__all__ = [
    "AggregationSpec",
    "CodeDefinition",
    "ExternalCoding",
    "FusionPolicy",
    "MetricComponent",
    "MetricDefinition",
    "MetricId",
    "NumericRange",
    "ONTOLOGY_VERSION",
    "OntologyVersion",
    "REGISTRY",
    "SourceVocabularyMapping",
    "ValueType",
    "all_metrics",
    "export_registry",
    "get_metric",
]
