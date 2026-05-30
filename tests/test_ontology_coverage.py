"""Ontology coverage contract.

Guarantees every quantity metric HealthSave ingests has a canonical registry
mapping. INGESTED_WIRE_NAMES is the authoritative set of quantity wire names
the iOS app sends (mirrors the quantity tuples in
``ios_app/Sources/HealthSync/HealthTypes.swift``). If a metric is added there,
add it here AND to the registry — this test fails until both are done.
"""

from __future__ import annotations

import json

from contracts.ontology import REGISTRY, all_metrics, export_registry

# Authoritative quantity wire-names HealthSave ingests (HealthTypes.swift).
INGESTED_WIRE_NAMES: frozenset[str] = frozenset(
    {
        # Heart & cardiovascular
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
        # Blood pressure
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        # Blood & metabolic
        "blood_glucose",
        "blood_alcohol_content",
        "insulin_delivery",
        # Activity & movement
        "step_count",
        "active_energy_burned",
        "basal_energy_burned",
        "apple_exercise_time",
        "apple_stand_time",
        "apple_move_time",
        "flights_climbed",
        "distance_walking_running",
        "distance_cycling",
        "distance_swimming",
        "distance_wheelchair",
        "distance_downhill_snow_sports",
        "distance_cross_country_skiing",
        "distance_paddle_sports",
        "distance_rowing",
        "distance_skating_sports",
        "push_count",
        "swimming_stroke_count",
        "nike_fuel",
        "physical_effort",
        "workout_effort_score",
        "estimated_workout_effort_score",
        # Walking / running dynamics, mobility
        "walking_speed",
        "walking_step_length",
        "walking_asymmetry",
        "walking_double_support",
        "apple_walking_steadiness",
        "running_speed",
        "running_stride_length",
        "running_vertical_oscillation",
        "running_ground_contact_time",
        "running_power",
        "six_minute_walk_test_distance",
        "stair_ascent_speed",
        "stair_descent_speed",
        "number_of_times_fallen",
        # Cycling & sport speeds
        "cycling_speed",
        "cycling_cadence",
        "cycling_power",
        "cycling_functional_threshold_power",
        "cross_country_skiing_speed",
        "paddle_sports_speed",
        "rowing_speed",
        # Body & vitals
        "body_mass",
        "bmi",
        "body_fat_percentage",
        "lean_body_mass",
        "height",
        "waist_circumference",
        "body_temperature",
        "basal_body_temperature",
        "wrist_temperature",
        # Respiratory
        "forced_expiratory_volume_1",
        "forced_vital_capacity",
        "peak_expiratory_flow_rate",
        "inhaler_usage",
        "sleeping_breathing_disturbances",
        # Environment & audio, water
        "environmental_audio_exposure",
        "headphone_audio_exposure",
        "environmental_sound_reduction",
        "time_in_daylight",
        "uv_exposure",
        "electrodermal_activity",
        "underwater_depth",
        "water_temperature",
        # Nutrition
        "dietary_energy_consumed",
        "dietary_carbohydrates",
        "dietary_protein",
        "dietary_fat_total",
        "dietary_fat_saturated",
        "dietary_fat_monounsaturated",
        "dietary_fat_polyunsaturated",
        "dietary_cholesterol",
        "dietary_fiber",
        "dietary_sugar",
        "dietary_water",
        "dietary_caffeine",
        "dietary_calcium",
        "dietary_iron",
        "dietary_magnesium",
        "dietary_phosphorus",
        "dietary_potassium",
        "dietary_sodium",
        "dietary_chloride",
        "dietary_zinc",
        "dietary_copper",
        "dietary_manganese",
        "dietary_selenium",
        "dietary_iodine",
        "dietary_chromium",
        "dietary_molybdenum",
        "dietary_vitamin_a",
        "dietary_vitamin_c",
        "dietary_vitamin_d",
        "dietary_vitamin_e",
        "dietary_vitamin_k",
        "dietary_thiamin",
        "dietary_riboflavin",
        "dietary_niacin",
        "dietary_pantothenic_acid",
        "dietary_vitamin_b6",
        "dietary_biotin",
        "dietary_folate",
        "dietary_vitamin_b12",
        "number_of_alcoholic_beverages",
    }
)


def _mapped_wire_names() -> set[str]:
    names: set[str] = set()
    for metric in all_metrics():
        for mapping in metric.source_mappings:
            if mapping.source == "apple_healthkit":
                names.add(mapping.source_metric)
    return names


def test_every_ingested_metric_has_a_canonical_mapping() -> None:
    """No HealthSave-ingested quantity metric may be unmapped in the registry."""
    unmapped = INGESTED_WIRE_NAMES - _mapped_wire_names()
    assert not unmapped, (
        f"{len(unmapped)} ingested metrics lack a canonical mapping: {sorted(unmapped)}"
    )


def test_registry_is_full_catalog_sized() -> None:
    assert len(REGISTRY) >= 140, (
        f"registry shrank to {len(REGISTRY)} — expected full catalog (>=140)"
    )


def test_each_ingested_wire_name_maps_to_exactly_one_metric() -> None:
    """No ingested HealthKit wire-name may be claimed by two registry entries."""
    counts: dict[str, int] = {}
    for metric in all_metrics():
        for mapping in metric.source_mappings:
            if mapping.source == "apple_healthkit" and mapping.source_metric in INGESTED_WIRE_NAMES:
                counts[mapping.source_metric] = counts.get(mapping.source_metric, 0) + 1
    dupes = {wire: n for wire, n in counts.items() if n > 1}
    assert not dupes, f"wire-names mapped by multiple registry entries: {dupes}"


def test_full_registry_is_json_serializable() -> None:
    json.dumps(export_registry())
