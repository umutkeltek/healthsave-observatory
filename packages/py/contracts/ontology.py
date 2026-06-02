"""Versioned metric ontology registry for canonical health observations.

Full-catalog coverage: every quantity metric HealthSave ingests
(``ios_app/Sources/HealthSync/HealthTypes.swift``) plus the category-type
metrics (sleep, cycle, mindfulness, sexual activity) and the research-derived
"computed" metrics (SRI, VILPA, K:Na ratio, wrist-temp deviation).

The uniform quantity metrics are declared via a compact ``_q(...)`` spec table
rather than 130 verbose constructor blocks — same MetricDefinition objects, far
fewer lines to review. Non-scalar and computed metrics are explicit.
"""

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

_SUM_FUSION = FusionPolicy(
    strategy="aggregate",
    source_priority=["apple_healthkit", "fitbit", "garmin", "manual"],
    aggregate_fn="sum",
)

SLEEP_STAGE_CODES = [
    CodeDefinition(code="awake", label="Awake"),
    CodeDefinition(code="rem", label="REM"),
    CodeDefinition(code="core", label="Core"),
    CodeDefinition(code="deep", label="Deep"),
]


def _q(
    metric_id: MetricId,
    wire: str,
    display: str,
    category: str,
    unit: str,
    *,
    lo: float | None = None,
    hi: float | None = None,
    kind: Literal["instant", "daily_total", "summary", "event"] = "instant",
    rollup: Literal["latest", "mean", "sum", "min", "max", "count", "none"] = "mean",
    allowed: list[str] | None = None,
    loinc: str | None = None,
    fusion: FusionPolicy | None = None,
    computed: bool = False,
    wire_aliases: list[str] | None = None,
) -> MetricDefinition:
    """Build a uniform quantity MetricDefinition from a compact spec.

    ``wire`` is the HealthSave/HealthKit wire metric name; it becomes the
    apple_healthkit source mapping so the normalizer can route it.
    ``wire_aliases`` adds extra apple_healthkit wire names that resolve to the
    same canonical metric (e.g. ``blood_oxygen`` alongside ``oxygen_saturation``).
    ``computed`` marks a research-derived metric (no raw source mapping).
    """
    rng = NumericRange(min_value=lo, max_value=hi) if (lo is not None or hi is not None) else None
    mappings = (
        []
        if computed
        else [
            SourceVocabularyMapping(source="apple_healthkit", source_metric=name)
            for name in (wire, *(wire_aliases or ()))
        ]
    )
    standards = [ExternalCoding(system="loinc", code=loinc)] if loinc else []
    return MetricDefinition(
        id=metric_id,
        ontology_version=ONTOLOGY_VERSION,
        display_name=display,
        category=category,
        value_type="quantity",
        canonical_unit=unit,
        allowed_units=allowed or [unit],
        valid_range=rng,
        aggregation=AggregationSpec(kind=kind, default_rollup=rollup),
        fusion=fusion or DEFAULT_FUSION,
        source_mappings=mappings,
        standards_mappings=standards,
    )


# --- Uniform quantity metrics: one row per HealthTypes.swift quantity type ----
_QUANTITY: list[MetricDefinition] = [
    # Heart & cardiovascular
    _q(
        "vital.heart_rate",
        "heart_rate",
        "Heart Rate",
        "vital",
        "bpm",
        lo=20,
        hi=240,
        loinc="8867-4",
    ),
    _q(
        "vital.resting_heart_rate",
        "resting_heart_rate",
        "Resting Heart Rate",
        "vital",
        "bpm",
        lo=20,
        hi=140,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "vital.walking_heart_rate_average",
        "walking_heart_rate_average",
        "Walking Heart Rate",
        "vital",
        "bpm",
        lo=40,
        hi=200,
        kind="summary",
    ),
    _q(
        "vital.hrv_sdnn",
        "heart_rate_variability",
        "Heart Rate Variability (SDNN)",
        "vital",
        "ms",
        lo=0,
        hi=500,
        kind="summary",
    ),
    _q(
        "vital.heart_rate_recovery",
        "heart_rate_recovery",
        "Heart Rate Recovery (1 min)",
        "vital",
        "bpm",
        lo=0,
        hi=100,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "cardio.afib_burden",
        "atrial_fibrillation_burden",
        "AFib Burden",
        "cardio",
        "%",
        lo=0,
        hi=100,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "cardio.vo2_max",
        "vo2_max",
        "VO2 Max",
        "cardio",
        "ml/kg/min",
        lo=10,
        hi=90,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "vital.blood_oxygen",
        "oxygen_saturation",
        "Blood Oxygen",
        "vital",
        "%",
        lo=50,
        hi=100,
        loinc="59408-5",
        wire_aliases=["blood_oxygen"],
    ),
    _q(
        "vital.respiratory_rate",
        "respiratory_rate",
        "Respiratory Rate",
        "vital",
        "breaths/min",
        lo=4,
        hi=60,
    ),
    _q(
        "cardio.perfusion_index",
        "peripheral_perfusion_index",
        "Peripheral Perfusion Index",
        "cardio",
        "%",
        lo=0,
        hi=20,
    ),
    # Blood pressure (components defined in _SPECIAL)
    _q(
        "blood_pressure.systolic",
        "blood_pressure_systolic",
        "Systolic Blood Pressure",
        "vital",
        "mmHg",
        lo=40,
        hi=300,
        kind="instant",
        rollup="latest",
        loinc="8480-6",
    ),
    _q(
        "blood_pressure.diastolic",
        "blood_pressure_diastolic",
        "Diastolic Blood Pressure",
        "vital",
        "mmHg",
        lo=20,
        hi=200,
        kind="instant",
        rollup="latest",
        loinc="8462-4",
    ),
    # Blood & metabolic
    _q(
        "metabolic.blood_glucose",
        "blood_glucose",
        "Blood Glucose",
        "metabolic",
        "mg/dL",
        lo=20,
        hi=600,
        loinc="2339-0",
    ),
    _q(
        "metabolic.blood_alcohol_content",
        "blood_alcohol_content",
        "Blood Alcohol Content",
        "metabolic",
        "%",
        lo=0,
        hi=1,
        rollup="latest",
    ),
    _q(
        "metabolic.insulin_delivery",
        "insulin_delivery",
        "Insulin Delivery",
        "metabolic",
        "IU",
        lo=0,
        hi=100,
        kind="daily_total",
        rollup="sum",
    ),
    # Activity & movement
    _q(
        "activity.steps",
        "step_count",
        "Steps",
        "activity",
        "count",
        lo=0,
        hi=100000,
        kind="daily_total",
        rollup="sum",
        fusion=_SUM_FUSION,
    ),
    _q(
        "activity.active_energy",
        "active_energy_burned",
        "Active Energy",
        "activity",
        "kcal",
        lo=0,
        hi=20000,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.basal_energy",
        "basal_energy_burned",
        "Resting Energy",
        "activity",
        "kcal",
        lo=0,
        hi=5000,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.exercise_minutes",
        "apple_exercise_time",
        "Exercise Minutes",
        "activity",
        "min",
        lo=0,
        hi=1440,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.stand_minutes",
        "apple_stand_time",
        "Stand Minutes",
        "activity",
        "min",
        lo=0,
        hi=1440,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.move_minutes",
        "apple_move_time",
        "Move Minutes",
        "activity",
        "min",
        lo=0,
        hi=1440,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.flights_climbed",
        "flights_climbed",
        "Flights Climbed",
        "activity",
        "count",
        lo=0,
        hi=500,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.distance_walking_running",
        "distance_walking_running",
        "Walking + Running Distance",
        "activity",
        "m",
        lo=0,
        hi=500000,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.distance_cycling",
        "distance_cycling",
        "Cycling Distance",
        "activity",
        "m",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.distance_swimming",
        "distance_swimming",
        "Swimming Distance",
        "activity",
        "m",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.distance_wheelchair",
        "distance_wheelchair",
        "Wheelchair Distance",
        "activity",
        "m",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.distance_downhill_snow_sports",
        "distance_downhill_snow_sports",
        "Downhill Snow Sports Distance",
        "activity",
        "m",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.distance_cross_country_skiing",
        "distance_cross_country_skiing",
        "Cross-Country Skiing Distance",
        "activity",
        "m",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.distance_paddle_sports",
        "distance_paddle_sports",
        "Paddle Sports Distance",
        "activity",
        "m",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.distance_rowing",
        "distance_rowing",
        "Rowing Distance",
        "activity",
        "m",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.distance_skating_sports",
        "distance_skating_sports",
        "Skating Sports Distance",
        "activity",
        "m",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.push_count",
        "push_count",
        "Push Count",
        "activity",
        "count",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.swimming_stroke_count",
        "swimming_stroke_count",
        "Swimming Strokes",
        "activity",
        "count",
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "activity.nike_fuel",
        "nike_fuel",
        "NikeFuel",
        "activity",
        "count",
        kind="daily_total",
        rollup="sum",
    ),
    _q("activity.physical_effort", "physical_effort", "Physical Effort", "activity", "kcal/kg/hr"),
    _q(
        "activity.workout_effort_score",
        "workout_effort_score",
        "Workout Effort Score",
        "activity",
        "score",
        lo=0,
        hi=10,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "activity.estimated_workout_effort_score",
        "estimated_workout_effort_score",
        "Estimated Workout Effort",
        "activity",
        "score",
        lo=0,
        hi=10,
        kind="summary",
        rollup="latest",
    ),
    # Walking & running dynamics, mobility
    _q(
        "mobility.walking_speed",
        "walking_speed",
        "Walking Speed",
        "mobility",
        "m/s",
        lo=0,
        hi=3,
        kind="summary",
    ),
    _q(
        "mobility.walking_step_length",
        "walking_step_length",
        "Walking Step Length",
        "mobility",
        "m",
        lo=0,
        hi=2,
        kind="summary",
    ),
    _q(
        "mobility.walking_asymmetry",
        "walking_asymmetry",
        "Walking Asymmetry",
        "mobility",
        "%",
        lo=0,
        hi=100,
        kind="summary",
    ),
    _q(
        "mobility.walking_double_support",
        "walking_double_support",
        "Double Support Time",
        "mobility",
        "%",
        lo=0,
        hi=100,
        kind="summary",
    ),
    _q(
        "mobility.walking_steadiness",
        "apple_walking_steadiness",
        "Walking Steadiness",
        "mobility",
        "%",
        lo=0,
        hi=100,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "mobility.running_speed",
        "running_speed",
        "Running Speed",
        "mobility",
        "m/s",
        kind="summary",
    ),
    _q(
        "mobility.running_stride_length",
        "running_stride_length",
        "Running Stride Length",
        "mobility",
        "m",
        kind="summary",
    ),
    _q(
        "mobility.running_vertical_oscillation",
        "running_vertical_oscillation",
        "Vertical Oscillation",
        "mobility",
        "cm",
        kind="summary",
    ),
    _q(
        "mobility.running_ground_contact_time",
        "running_ground_contact_time",
        "Ground Contact Time",
        "mobility",
        "ms",
        kind="summary",
    ),
    _q("mobility.running_power", "running_power", "Running Power", "mobility", "W", kind="summary"),
    _q(
        "mobility.six_minute_walk_distance",
        "six_minute_walk_test_distance",
        "Six-Minute Walk Distance",
        "mobility",
        "m",
        kind="summary",
        rollup="latest",
    ),
    _q(
        "mobility.stair_ascent_speed",
        "stair_ascent_speed",
        "Stair Ascent Speed",
        "mobility",
        "m/s",
        kind="summary",
    ),
    _q(
        "mobility.stair_descent_speed",
        "stair_descent_speed",
        "Stair Descent Speed",
        "mobility",
        "m/s",
        kind="summary",
    ),
    _q(
        "mobility.times_fallen",
        "number_of_times_fallen",
        "Number of Times Fallen",
        "mobility",
        "count",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    # Cycling & sport speeds
    _q("cycling.speed", "cycling_speed", "Cycling Speed", "activity", "m/s", kind="summary"),
    _q("cycling.cadence", "cycling_cadence", "Cycling Cadence", "activity", "rpm", kind="summary"),
    _q("cycling.power", "cycling_power", "Cycling Power", "activity", "W", kind="summary"),
    _q(
        "cycling.functional_threshold_power",
        "cycling_functional_threshold_power",
        "Functional Threshold Power",
        "activity",
        "W",
        kind="summary",
        rollup="latest",
    ),
    _q(
        "sport.cross_country_skiing_speed",
        "cross_country_skiing_speed",
        "Cross-Country Skiing Speed",
        "activity",
        "m/s",
        kind="summary",
    ),
    _q(
        "sport.paddle_sports_speed",
        "paddle_sports_speed",
        "Paddle Sports Speed",
        "activity",
        "m/s",
        kind="summary",
    ),
    _q("sport.rowing_speed", "rowing_speed", "Rowing Speed", "activity", "m/s", kind="summary"),
    # Body & vitals
    _q(
        "body.weight",
        "body_mass",
        "Body Weight",
        "body",
        "kg",
        lo=0,
        hi=500,
        kind="summary",
        rollup="latest",
        allowed=["kg", "lb"],
        loinc="29463-7",
    ),
    _q(
        "body.bmi",
        "bmi",
        "Body Mass Index",
        "body",
        "kg/m^2",
        lo=5,
        hi=100,
        kind="summary",
        rollup="latest",
        loinc="39156-5",
    ),
    _q(
        "body.fat_percent",
        "body_fat_percentage",
        "Body Fat Percentage",
        "body",
        "%",
        lo=0,
        hi=100,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "body.lean_mass",
        "lean_body_mass",
        "Lean Body Mass",
        "body",
        "kg",
        lo=0,
        hi=300,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "body.height",
        "height",
        "Height",
        "body",
        "m",
        lo=0.3,
        hi=2.5,
        kind="summary",
        rollup="latest",
        allowed=["m", "cm", "in"],
        loinc="8302-2",
    ),
    _q(
        "body.waist_circumference",
        "waist_circumference",
        "Waist Circumference",
        "body",
        "m",
        lo=0.3,
        hi=2.5,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "body.temperature",
        "body_temperature",
        "Body Temperature",
        "body",
        "degC",
        lo=25,
        hi=45,
        rollup="latest",
        allowed=["degC", "degF"],
        loinc="8310-5",
    ),
    _q(
        "body.basal_body_temperature",
        "basal_body_temperature",
        "Basal Body Temperature",
        "body",
        "degC",
        lo=30,
        hi=40,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "body.wrist_temperature",
        "wrist_temperature",
        "Wrist Temperature",
        "body",
        "degC",
        lo=25,
        hi=45,
        kind="summary",
    ),
    # Respiratory
    _q(
        "respiratory.fev1",
        "forced_expiratory_volume_1",
        "Forced Expiratory Volume (1s)",
        "respiratory",
        "L",
        lo=0,
        hi=8,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "respiratory.fvc",
        "forced_vital_capacity",
        "Forced Vital Capacity",
        "respiratory",
        "L",
        lo=0,
        hi=8,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "respiratory.peak_expiratory_flow",
        "peak_expiratory_flow_rate",
        "Peak Expiratory Flow",
        "respiratory",
        "L/min",
        lo=0,
        hi=900,
        kind="summary",
        rollup="latest",
    ),
    _q(
        "respiratory.inhaler_usage",
        "inhaler_usage",
        "Inhaler Usage",
        "respiratory",
        "count",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "respiratory.breathing_disturbances",
        "sleeping_breathing_disturbances",
        "Sleeping Breathing Disturbances",
        "respiratory",
        "count",
        lo=0,
        kind="summary",
    ),
    # Environment & audio, water
    _q(
        "environment.audio_exposure",
        "environmental_audio_exposure",
        "Environmental Audio Exposure",
        "environment",
        "dBASPL",
        lo=0,
        hi=140,
        kind="summary",
    ),
    _q(
        "environment.headphone_audio_exposure",
        "headphone_audio_exposure",
        "Headphone Audio Exposure",
        "environment",
        "dBASPL",
        lo=0,
        hi=140,
        kind="summary",
    ),
    _q(
        "environment.sound_reduction",
        "environmental_sound_reduction",
        "Environmental Sound Reduction",
        "environment",
        "dBASPL",
        lo=0,
        hi=140,
        kind="summary",
    ),
    _q(
        "environment.time_in_daylight",
        "time_in_daylight",
        "Time in Daylight",
        "environment",
        "min",
        lo=0,
        hi=1440,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "environment.uv_exposure",
        "uv_exposure",
        "UV Exposure",
        "environment",
        "index",
        lo=0,
        hi=20,
        rollup="max",
    ),
    _q(
        "environment.electrodermal_activity",
        "electrodermal_activity",
        "Electrodermal Activity",
        "environment",
        "uS",
    ),
    _q(
        "environment.underwater_depth",
        "underwater_depth",
        "Underwater Depth",
        "environment",
        "m",
        lo=0,
        rollup="max",
    ),
    _q(
        "environment.water_temperature",
        "water_temperature",
        "Water Temperature",
        "environment",
        "degC",
    ),
    # Nutrition — macros / energy
    _q(
        "nutrition.energy_consumed",
        "dietary_energy_consumed",
        "Dietary Energy",
        "nutrition",
        "kcal",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.carbohydrates",
        "dietary_carbohydrates",
        "Carbohydrates",
        "nutrition",
        "g",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.protein",
        "dietary_protein",
        "Protein",
        "nutrition",
        "g",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.fat_total",
        "dietary_fat_total",
        "Total Fat",
        "nutrition",
        "g",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.fat_saturated",
        "dietary_fat_saturated",
        "Saturated Fat",
        "nutrition",
        "g",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.fat_monounsaturated",
        "dietary_fat_monounsaturated",
        "Monounsaturated Fat",
        "nutrition",
        "g",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.fat_polyunsaturated",
        "dietary_fat_polyunsaturated",
        "Polyunsaturated Fat",
        "nutrition",
        "g",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.cholesterol",
        "dietary_cholesterol",
        "Cholesterol",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.fiber",
        "dietary_fiber",
        "Fiber",
        "nutrition",
        "g",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.sugar",
        "dietary_sugar",
        "Sugar",
        "nutrition",
        "g",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.water",
        "dietary_water",
        "Water",
        "nutrition",
        "mL",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.caffeine",
        "dietary_caffeine",
        "Caffeine",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    # Nutrition — minerals
    _q(
        "nutrition.calcium",
        "dietary_calcium",
        "Calcium",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.iron",
        "dietary_iron",
        "Iron",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.magnesium",
        "dietary_magnesium",
        "Magnesium",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.phosphorus",
        "dietary_phosphorus",
        "Phosphorus",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.potassium",
        "dietary_potassium",
        "Potassium",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.sodium",
        "dietary_sodium",
        "Sodium",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.chloride",
        "dietary_chloride",
        "Chloride",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.zinc",
        "dietary_zinc",
        "Zinc",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.copper",
        "dietary_copper",
        "Copper",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.manganese",
        "dietary_manganese",
        "Manganese",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.selenium",
        "dietary_selenium",
        "Selenium",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.iodine",
        "dietary_iodine",
        "Iodine",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.chromium",
        "dietary_chromium",
        "Chromium",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.molybdenum",
        "dietary_molybdenum",
        "Molybdenum",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    # Nutrition — vitamins
    _q(
        "nutrition.vitamin_a",
        "dietary_vitamin_a",
        "Vitamin A",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.vitamin_c",
        "dietary_vitamin_c",
        "Vitamin C",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.vitamin_d",
        "dietary_vitamin_d",
        "Vitamin D",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.vitamin_e",
        "dietary_vitamin_e",
        "Vitamin E",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.vitamin_k",
        "dietary_vitamin_k",
        "Vitamin K",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.thiamin",
        "dietary_thiamin",
        "Thiamin (B1)",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.riboflavin",
        "dietary_riboflavin",
        "Riboflavin (B2)",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.niacin",
        "dietary_niacin",
        "Niacin (B3)",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.pantothenic_acid",
        "dietary_pantothenic_acid",
        "Pantothenic Acid (B5)",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.vitamin_b6",
        "dietary_vitamin_b6",
        "Vitamin B6",
        "nutrition",
        "mg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.biotin",
        "dietary_biotin",
        "Biotin (B7)",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.folate",
        "dietary_folate",
        "Folate (B9)",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.vitamin_b12",
        "dietary_vitamin_b12",
        "Vitamin B12",
        "nutrition",
        "mcg",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    _q(
        "nutrition.alcoholic_beverages",
        "number_of_alcoholic_beverages",
        "Alcoholic Beverages",
        "nutrition",
        "count",
        lo=0,
        kind="daily_total",
        rollup="sum",
    ),
    # Body-composition quantity also used by sleep duration scalar
    _q(
        "sleep.duration",
        "sleep_duration",
        "Sleep Duration",
        "sleep",
        "min",
        lo=0,
        hi=1440,
        kind="summary",
        rollup="sum",
    ),
    # Research-derived (computed) metrics
    _q(
        "sleep.regularity_index",
        "sleep_regularity_index",
        "Sleep Regularity Index",
        "computed",
        "score",
        lo=0,
        hi=100,
        kind="summary",
        rollup="latest",
        computed=True,
    ),
    _q(
        "activity.vilpa_minutes",
        "vilpa_minutes",
        "Vigorous Intermittent Lifestyle Physical Activity",
        "computed",
        "min",
        lo=0,
        kind="daily_total",
        rollup="sum",
        computed=True,
    ),
    _q(
        "nutrition.k_na_ratio",
        "k_na_ratio",
        "Potassium:Sodium Ratio",
        "computed",
        "ratio",
        lo=0,
        kind="summary",
        rollup="mean",
        computed=True,
    ),
    _q(
        "nutrition.fiber_adequacy",
        "fiber_adequacy",
        "Fiber Adequacy",
        "computed",
        "%",
        lo=0,
        hi=200,
        kind="summary",
        rollup="mean",
        computed=True,
    ),
    _q(
        "vital.wrist_temperature_deviation",
        "wrist_temperature_deviation",
        "Wrist Temperature Deviation",
        "computed",
        "degC",
        lo=-5,
        hi=5,
        kind="summary",
        rollup="latest",
        computed=True,
    ),
]


def _menstrual_codes() -> list[CodeDefinition]:
    return [
        CodeDefinition(code="none", label="No flow"),
        CodeDefinition(code="light", label="Light"),
        CodeDefinition(code="medium", label="Medium"),
        CodeDefinition(code="heavy", label="Heavy"),
        CodeDefinition(code="unspecified", label="Unspecified"),
    ]


def _symptom(metric_id: str, wire: str, display: str) -> MetricDefinition:
    """A presence/severity symptom log entry (categorical)."""
    return MetricDefinition(
        id=metric_id,
        ontology_version=ONTOLOGY_VERSION,
        display_name=display,
        category="symptom",
        value_type="categorical",
        allowed_codes=[
            CodeDefinition(code="not_present", label="Not present"),
            CodeDefinition(code="mild", label="Mild"),
            CodeDefinition(code="moderate", label="Moderate"),
            CodeDefinition(code="severe", label="Severe"),
        ],
        aggregation=AggregationSpec(kind="event", default_rollup="none"),
        fusion=FusionPolicy(strategy="dedup", source_priority=["apple_healthkit", "manual"]),
        source_mappings=[SourceVocabularyMapping(source="apple_healthkit", source_metric=wire)],
    )


# --- Non-scalar + category metrics (explicit) --------------------------------
_SPECIAL: list[MetricDefinition] = [
    MetricDefinition(
        id="sleep.stage",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Sleep Stage",
        category="sleep",
        value_type="categorical",
        allowed_codes=SLEEP_STAGE_CODES,
        aggregation=AggregationSpec(kind="event", default_rollup="none"),
        fusion=FusionPolicy(
            strategy="dedup", source_priority=["apple_healthkit", "oura", "whoop", "fitbit"]
        ),
        source_mappings=[
            SourceVocabularyMapping(
                source="apple_healthkit",
                source_metric="sleep_analysis",
                value_map={
                    "HKCategoryValueSleepAnalysisAwake": "awake",
                    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
                    "HKCategoryValueSleepAnalysisAsleepCore": "core",
                    "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
                },
            )
        ],
    ),
    MetricDefinition(
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
    MetricDefinition(
        id="workout.session",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Workout Session",
        category="activity",
        value_type="event",
        aggregation=AggregationSpec(kind="event", default_rollup="count"),
        fusion=FusionPolicy(
            strategy="dedup", source_priority=["apple_healthkit", "garmin", "strava", "manual"]
        ),
        source_mappings=[
            SourceVocabularyMapping(source="apple_healthkit", source_metric="workouts")
        ],
    ),
    MetricDefinition(
        id="blood_pressure",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Blood Pressure",
        category="vital",
        value_type="components",
        components=[
            MetricComponent(
                metric_id="blood_pressure.systolic", label="Systolic", canonical_unit="mmHg"
            ),
            MetricComponent(
                metric_id="blood_pressure.diastolic", label="Diastolic", canonical_unit="mmHg"
            ),
        ],
        aggregation=AggregationSpec(kind="instant", default_rollup="latest"),
        fusion=DEFAULT_FUSION,
        standards_mappings=[
            ExternalCoding(system="loinc", code="85354-9", display="Blood pressure panel")
        ],
    ),
    MetricDefinition(
        id="recovery.score",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Recovery Score",
        category="recovery",
        value_type="quantity",
        canonical_unit="score",
        allowed_units=["score"],
        valid_range=NumericRange(min_value=0, max_value=100),
        aggregation=AggregationSpec(kind="summary", default_rollup="latest"),
        fusion=FusionPolicy(
            strategy="ranked_source", source_priority=["whoop", "oura", "computed"]
        ),
    ),
    MetricDefinition(
        id="readiness.score",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Readiness Score",
        category="recovery",
        value_type="quantity",
        canonical_unit="score",
        allowed_units=["score"],
        valid_range=NumericRange(min_value=0, max_value=100),
        aggregation=AggregationSpec(kind="summary", default_rollup="latest"),
        fusion=FusionPolicy(
            strategy="ranked_source", source_priority=["oura", "whoop", "computed"]
        ),
    ),
    MetricDefinition(
        id="mindfulness.session",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Mindful Session",
        category="mental",
        value_type="event",
        aggregation=AggregationSpec(kind="event", default_rollup="count"),
        fusion=FusionPolicy(strategy="dedup", source_priority=["apple_healthkit", "manual"]),
        source_mappings=[
            SourceVocabularyMapping(source="apple_healthkit", source_metric="mindful_session")
        ],
    ),
    MetricDefinition(
        id="reproductive.sexual_activity",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Sexual Activity",
        category="reproductive",
        value_type="event",
        aggregation=AggregationSpec(kind="event", default_rollup="count"),
        fusion=FusionPolicy(strategy="dedup", source_priority=["apple_healthkit", "manual"]),
        source_mappings=[
            SourceVocabularyMapping(source="apple_healthkit", source_metric="sexual_activity")
        ],
    ),
    MetricDefinition(
        id="reproductive.menstrual_flow",
        ontology_version=ONTOLOGY_VERSION,
        display_name="Menstrual Flow",
        category="reproductive",
        value_type="categorical",
        allowed_codes=_menstrual_codes(),
        aggregation=AggregationSpec(kind="event", default_rollup="none"),
        fusion=FusionPolicy(strategy="dedup", source_priority=["apple_healthkit", "manual"]),
        source_mappings=[
            SourceVocabularyMapping(source="apple_healthkit", source_metric="menstrual_flow")
        ],
    ),
    _symptom("symptom.headache", "headache", "Headache"),
    _symptom("symptom.fatigue", "fatigue", "Fatigue"),
    _symptom("symptom.nausea", "nausea", "Nausea"),
    _symptom("symptom.fever", "fever", "Fever"),
    _symptom("symptom.cough", "coughing", "Coughing"),
    _symptom("symptom.shortness_of_breath", "shortness_of_breath", "Shortness of Breath"),
    _symptom(
        "symptom.chest_tightness_or_pain", "chest_tightness_or_pain", "Chest Tightness or Pain"
    ),
    _symptom("symptom.dizziness", "dizziness", "Dizziness"),
    _symptom("symptom.mood_changes", "mood_changes", "Mood Changes"),
    _symptom("symptom.sleep_changes", "sleep_changes", "Sleep Changes"),
]


def _assemble() -> dict[MetricId, MetricDefinition]:
    registry: dict[MetricId, MetricDefinition] = {}
    for metric in (*_QUANTITY, *_SPECIAL):
        if metric.id in registry:
            msg = f"duplicate metric id in registry: {metric.id}"
            raise ValueError(msg)
        registry[metric.id] = metric
    return registry


REGISTRY: dict[MetricId, MetricDefinition] = _assemble()


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
