"""HealthSave client compatibility checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402


class FakeResult:
    def __init__(self, row=None, scalar_value=1):
        self.row = row
        self.scalar_value = scalar_value

    def fetchone(self):
        return self.row

    def first(self):
        return self.row

    def scalar(self):
        return self.scalar_value


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.committed = False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if sql.startswith("SELECT id FROM devices"):
            return FakeResult(row=(1,))
        if sql.startswith("SELECT count(*)"):
            return FakeResult(row=(0, None, None))
        return FakeResult()

    async def commit(self):
        self.committed = True

    def insert_params_for(self, table_name: str) -> dict | None:
        needle = f"INSERT INTO {table_name}"
        for sql, params in self.calls:
            if needle in sql:
                return params
        return None

    def all_insert_params_for(self, table_name: str) -> list[dict]:
        needle = f"INSERT INTO {table_name}"
        return [params for sql, params in self.calls if needle in sql]


class FailingStatusSession(FakeSession):
    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        if sql.startswith("SELECT count(*)"):
            raise RuntimeError("database is unavailable")
        return await super().execute(statement, params)


class FakeRequest:
    def __init__(self, payload: dict):
        self.payload = payload

    async def json(self):
        return self.payload


@pytest.mark.asyncio
async def test_status_endpoint_returns_flat_metric_objects():
    session = FakeSession()

    result = await server.apple_status(session)

    assert "status" not in result
    assert "counts" not in result
    assert result["heart_rate"] == {"count": 0, "oldest": None, "newest": None}
    assert result["sleep_sessions"] == {"count": 0, "oldest": None, "newest": None}


@pytest.mark.asyncio
async def test_oxygen_saturation_alias_populates_blood_oxygen_table():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "oxygen_saturation",
            "samples": [
                {
                    "date": "2026-04-10T12:00:00+00:00",
                    "qty": 0.97,
                    "source": "Apple Watch",
                }
            ],
        }
    )

    result = await server.apple_batch(request, session)

    insert_params = session.insert_params_for("blood_oxygen")
    assert result["records"] == 1
    assert insert_params is not None
    assert insert_params["spo2_pct"] == 97.0
    assert session.insert_params_for("quantity_samples") is None


@pytest.mark.asyncio
async def test_step_count_daily_totals_populate_daily_activity():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "step_count",
            "samples": [
                {
                    "date": "2026-04-10T00:00:00+00:00",
                    "qty": 1234,
                    "source": "HealthKit Statistics",
                }
            ],
        }
    )

    result = await server.apple_batch(request, session)

    insert_params = session.insert_params_for("daily_activity")
    assert result["records"] == 1
    assert insert_params is not None
    assert insert_params["steps"] == 1234
    assert session.insert_params_for("quantity_samples") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("metric", ["apple_stand_time", "distance_cycling", "distance_wheelchair"])
async def test_non_summary_daily_metrics_remain_quantity_samples(metric):
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": metric,
            "samples": [
                {
                    "date": "2026-04-10T00:00:00+00:00",
                    "qty": 42,
                    "source": "HealthKit Statistics",
                }
            ],
        }
    )

    result = await server.apple_batch(request, session)

    insert_params = session.insert_params_for("quantity_samples")
    assert result["records"] == 1
    assert insert_params is not None
    assert insert_params["metric"] == metric
    assert session.insert_params_for("daily_activity") is None


@pytest.mark.asyncio
async def test_blood_pressure_correlation_preserves_inner_metric_names():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "blood_pressure",
            "samples": [
                {
                    "metric": "blood_pressure_systolic",
                    "date": "2026-04-10T09:00:00+00:00",
                    "qty": 120,
                    "source": "Blood Pressure Monitor",
                },
                {
                    "metric": "blood_pressure_diastolic",
                    "date": "2026-04-10T09:00:00+00:00",
                    "qty": 80,
                    "source": "Blood Pressure Monitor",
                },
            ],
        }
    )

    result = await server.apple_batch(request, session)

    inserts = session.all_insert_params_for("quantity_samples")
    assert result["records"] == 2
    assert [row["metric"] for row in inserts] == [
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
    ]


@pytest.mark.asyncio
async def test_batch_uses_sample_source_for_device_identity_and_logs_raw_payload():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "heart_rate",
            "batch_index": 2,
            "total_batches": 3,
            "samples": [
                {
                    "date": "2026-04-10T12:00:00+00:00",
                    "qty": 72,
                    "source": "Apple Watch Ultra",
                }
            ],
        }
    )

    result = await server.apple_batch(request, session)

    device_lookups = [
        params for sql, params in session.calls if sql.startswith("SELECT id FROM devices")
    ]
    raw_log = session.insert_params_for("raw_ingestion_log")
    assert result["records"] == 1
    assert device_lookups[0]["dt"] == "Apple Watch Ultra"
    assert raw_log is not None
    assert raw_log["source_type"] == "healthsave"
    assert raw_log["endpoint"] == "/api/apple/batch"
    assert json.loads(raw_log["raw_payload"])["metric"] == "heart_rate"


@pytest.mark.asyncio
async def test_sleep_stage_batches_upsert_sessions_and_write_stage_rows():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "sleep_analysis",
            "samples": [
                {
                    "date": "2026-04-10T22:00:00+00:00",
                    "endDate": "2026-04-10T23:00:00+00:00",
                    "value": "core",
                    "source": "Apple Watch",
                },
                {
                    "date": "2026-04-10T23:00:00+00:00",
                    "endDate": "2026-04-11T00:00:00+00:00",
                    "value": "deep",
                    "source": "Apple Watch",
                },
            ],
        }
    )

    result = await server.apple_batch(request, session)

    sleep_session_sql = [sql for sql, _ in session.calls if "INSERT INTO sleep_sessions" in sql]
    sleep_stage_rows = session.all_insert_params_for("sleep_stages")
    assert result["records"] == 1
    assert any("ON CONFLICT" in sql for sql in sleep_session_sql)
    assert len(sleep_stage_rows) == 2
    assert {row["stage"] for row in sleep_stage_rows} == {"core", "deep"}


@pytest.mark.asyncio
async def test_workouts_are_upserted_by_device_and_start_time():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "workouts",
            "samples": [
                {
                    "name": "Running",
                    "start": "2026-04-10T07:00:00+00:00",
                    "end": "2026-04-10T07:45:00+00:00",
                    "duration": 2700,
                    "source": "Apple Watch",
                }
            ],
        }
    )

    result = await server.apple_batch(request, session)

    workout_sql = [sql for sql, _ in session.calls if "INSERT INTO workouts" in sql]
    assert result["records"] == 1
    assert any("ON CONFLICT" in sql for sql in workout_sql)


@pytest.mark.asyncio
async def test_invalid_quantity_values_are_skipped_without_failing_batch():
    session = FakeSession()
    request = FakeRequest(
        {
            "metric": "respiratory_rate",
            "samples": [
                {
                    "date": "2026-04-10T12:00:00+00:00",
                    "qty": "not-a-number",
                    "source": "Apple Watch",
                }
            ],
        }
    )

    result = await server.apple_batch(request, session)

    assert result["records"] == 0
    assert session.insert_params_for("quantity_samples") is None
    assert session.committed is True


@pytest.mark.asyncio
async def test_status_logs_database_query_failures(caplog):
    session = FailingStatusSession()

    with caplog.at_level("WARNING", logger="healthsave"):
        result = await server.apple_status(session)

    assert result["heart_rate"] == {"count": 0, "oldest": None, "newest": None}
    assert "Status query failed for heart_rate" in caplog.text


def test_api_spec_documents_full_healthsave_metric_catalog():
    api_doc = Path("API.md").read_text()
    expected_metrics = [
        "heart_rate",
        "resting_heart_rate",
        "walking_heart_rate_average",
        "heart_rate_variability",
        "heart_rate_recovery",
        "atrial_fibrillation_burden",
        "vo2_max",
        "oxygen_saturation",
        "respiratory_rate",
        "peripheral_perfusion_index",
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        "blood_glucose",
        "insulin_delivery",
        "blood_alcohol_content",
        "number_of_alcoholic_beverages",
        "step_count",
        "distance_walking_running",
        "distance_cycling",
        "distance_swimming",
        "distance_wheelchair",
        "distance_downhill_snow_sports",
        "distance_cross_country_skiing",
        "distance_paddle_sports",
        "distance_rowing",
        "distance_skating_sports",
        "flights_climbed",
        "swimming_stroke_count",
        "push_count",
        "nike_fuel",
        "apple_exercise_time",
        "apple_stand_time",
        "apple_move_time",
        "active_energy_burned",
        "basal_energy_burned",
        "number_of_times_fallen",
        "walking_speed",
        "walking_step_length",
        "walking_asymmetry",
        "walking_double_support",
        "stair_ascent_speed",
        "stair_descent_speed",
        "apple_walking_steadiness",
        "six_minute_walk_test_distance",
        "running_power",
        "running_speed",
        "running_stride_length",
        "running_vertical_oscillation",
        "running_ground_contact_time",
        "cycling_speed",
        "cycling_power",
        "cycling_cadence",
        "cycling_functional_threshold_power",
        "cross_country_skiing_speed",
        "paddle_sports_speed",
        "rowing_speed",
        "physical_effort",
        "workout_effort_score",
        "estimated_workout_effort_score",
        "body_temperature",
        "wrist_temperature",
        "basal_body_temperature",
        "body_mass",
        "body_fat_percentage",
        "bmi",
        "lean_body_mass",
        "height",
        "waist_circumference",
        "electrodermal_activity",
        "forced_expiratory_volume_1",
        "forced_vital_capacity",
        "peak_expiratory_flow_rate",
        "inhaler_usage",
        "sleeping_breathing_disturbances",
        "environmental_audio_exposure",
        "headphone_audio_exposure",
        "environmental_sound_reduction",
        "uv_exposure",
        "time_in_daylight",
        "underwater_depth",
        "water_temperature",
        "dietary_energy_consumed",
        "dietary_protein",
        "dietary_fat_total",
        "dietary_fat_saturated",
        "dietary_fat_monounsaturated",
        "dietary_fat_polyunsaturated",
        "dietary_carbohydrates",
        "dietary_sugar",
        "dietary_fiber",
        "dietary_cholesterol",
        "dietary_sodium",
        "dietary_potassium",
        "dietary_calcium",
        "dietary_iron",
        "dietary_magnesium",
        "dietary_phosphorus",
        "dietary_zinc",
        "dietary_manganese",
        "dietary_copper",
        "dietary_selenium",
        "dietary_chromium",
        "dietary_molybdenum",
        "dietary_chloride",
        "dietary_biotin",
        "dietary_vitamin_a",
        "dietary_vitamin_b6",
        "dietary_vitamin_b12",
        "dietary_vitamin_c",
        "dietary_vitamin_d",
        "dietary_vitamin_e",
        "dietary_vitamin_k",
        "dietary_folate",
        "dietary_niacin",
        "dietary_pantothenic_acid",
        "dietary_riboflavin",
        "dietary_thiamin",
        "dietary_iodine",
        "dietary_water",
        "dietary_caffeine",
        "sleep_analysis",
        "workouts",
        "activity_summaries",
        "ecg",
        "blood_pressure",
        "high_heart_rate_event",
        "low_heart_rate_event",
        "irregular_heart_rhythm_event",
        "low_cardio_fitness_event",
        "mindful_session",
        "handwashing_event",
        "toothbrushing_event",
        "environmental_audio_exposure_event",
        "headphone_audio_exposure_event",
        "apple_walking_steadiness_event",
        "menstrual_flow",
        "intermenstrual_bleeding",
        "ovulation_test_result",
        "cervical_mucus_quality",
        "sexual_activity",
        "contraceptive",
        "pregnancy",
        "pregnancy_test_result",
        "lactation",
        "progesterone_test_result",
        "infrequent_menstrual_cycles",
        "irregular_menstrual_cycles",
        "persistent_intermenstrual_bleeding",
        "prolonged_menstrual_periods",
        "bleeding_after_pregnancy",
        "bleeding_during_pregnancy",
        "abdominal_cramps",
        "acne",
        "appetite_changes",
        "generalized_body_ache",
        "bloating",
        "breast_pain",
        "chest_tightness_or_pain",
        "chills",
        "constipation",
        "coughing",
        "diarrhea",
        "dizziness",
        "fainting",
        "fatigue",
        "fever",
        "headache",
        "heartburn",
        "hot_flashes",
        "lower_back_pain",
        "loss_of_smell",
        "loss_of_taste",
        "mood_changes",
        "nausea",
        "pelvic_pain",
        "rapid_pounding_or_fluttering_heartbeat",
        "runny_nose",
        "shortness_of_breath",
        "sinus_congestion",
        "skipped_heartbeat",
        "sleep_changes",
        "sore_throat",
        "vomiting",
        "wheezing",
        "bladder_incontinence",
        "dry_skin",
        "hair_loss",
        "vaginal_dryness",
        "memory_lapse",
        "night_sweats",
        "sleep_apnea_event",
    ]

    missing = [metric for metric in expected_metrics if f"`{metric}`" not in api_doc]
    assert missing == []


def test_api_spec_documents_quantity_sample_exceptions_and_workout_nested_fields():
    api_doc = Path("API.md").read_text()

    assert "`apple_stand_time` stays in `quantity_samples`" in api_doc
    assert "`distance_cycling`" in api_doc
    assert "`distance_wheelchair`" in api_doc
    assert "`heartRateData`" in api_doc
    assert "`route`" in api_doc
    assert "not persisted by this small-footprint server" in api_doc


def test_api_spec_documents_category_sample_wire_fields():
    api_doc = Path("API.md").read_text()

    assert "`endDate`" in api_doc
    assert "`rawValue`" in api_doc
    assert "`end_date`" not in api_doc
    assert "duration in seconds" in api_doc
    assert "raw HealthKit category value" in api_doc


def test_api_spec_documents_ecg_as_accepted_but_not_persisted():
    api_doc = Path("API.md").read_text()
    compact_doc = " ".join(api_doc.split())

    assert "`ecg` batches are accepted for compatibility" in compact_doc
    assert "ECG records are not persisted by this small-footprint server" in compact_doc


def test_schema_declares_idempotency_constraints_for_retry_safe_sync():
    schema = Path("schema.sql").read_text()

    assert "uq_sleep_sessions_device_start" in schema
    assert "ON sleep_sessions (device_id, start_time)" in schema
    assert "uq_sleep_stages" in schema
    assert "ON sleep_stages (time, device_id, stage)" in schema
    assert "uq_workouts_device_start" in schema
    assert "ON workouts (device_id, start_time)" in schema
    assert "idx_raw_ingestion_log_ingested_at" in schema


def test_schema_declares_phase_1_5_analysis_tables_for_fresh_installs():
    schema = Path("schema.sql").read_text()

    assert "CREATE TABLE analysis_runs" in schema
    assert "CREATE TABLE analysis_findings" in schema
    assert "CREATE TABLE analysis_insights" in schema
    assert "idx_insights_type_created" in schema


def test_readme_documents_existing_install_migration_flow():
    readme = Path("README.md").read_text()

    assert "migrations/001_audit_hardening.sql" in readme
    assert "migrations/002_analysis_tables.sql" in readme
    assert "docker compose exec -T db psql" in readme
