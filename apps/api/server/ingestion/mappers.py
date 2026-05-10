"""Metric → table mapping configuration.

Pure data: ``DEDICATED_TABLES`` declares which incoming metric names map to
first-class tables (with column renames + transforms), ``ACTIVITY_FIELDS``
maps activity-summary inputs to ``daily_activity`` columns, and
``DAILY_ACTIVITY_QUANTITY_FIELDS`` lists the quantity batches that should be
folded into ``daily_activity`` rather than the catch-all
``quantity_samples`` table.
"""

from .parsers import normalize_blood_oxygen, to_float, to_int

# Metrics that map to dedicated tables with specific column mappings
DEDICATED_TABLES = {
    "heart_rate": {
        "table": "heart_rate",
        "columns": {"date": "time", "qty": "bpm", "source": "source_id"},
        "transforms": {"bpm": to_int},
        "conflict": ["time", "device_id"],
    },
    "heart_rate_variability": {
        "table": "hrv",
        "columns": {"date": "time", "qty": "value_ms", "source": "source_id"},
        "transforms": {"value_ms": to_float},
        "defaults": {"algorithm": "sdnn"},
        "conflict": ["time", "device_id"],
    },
    "blood_oxygen": {
        "table": "blood_oxygen",
        "columns": {"date": "time", "qty": "spo2_pct"},
        "transforms": {"spo2_pct": normalize_blood_oxygen},
        "conflict": ["time", "device_id"],
    },
    "oxygen_saturation": {
        "table": "blood_oxygen",
        "columns": {"date": "time", "qty": "spo2_pct"},
        "transforms": {"spo2_pct": normalize_blood_oxygen},
        "conflict": ["time", "device_id"],
    },
    "body_temperature": {
        "table": "body_temperature",
        "columns": {"date": "time", "qty": "temp_celsius"},
        "transforms": {"temp_celsius": to_float},
        "conflict": ["time", "device_id"],
    },
    "wrist_temperature": {
        "table": "body_temperature",
        "columns": {"date": "time", "qty": "temp_celsius"},
        "transforms": {"temp_celsius": to_float},
        "conflict": ["time", "device_id"],
    },
}

# Activity summary fields → daily_activity columns
ACTIVITY_FIELDS = {
    "steps": "steps",
    "distance": "distance_m",
    "flights_climbed": "floors_climbed",
    "active_energy": "active_calories",
    "activeEnergyBurned": "active_calories",
    "basal_energy": "total_calories",
    "exercise_minutes": "active_minutes",
    "appleExerciseTime": "active_minutes",
    "stand_hours": "stand_hours",
    "appleStandHours": "stand_hours",
}

# HealthSave sends many activity totals as quantity batches rather than as
# `activity_summaries`; keep Grafana-facing daily totals populated.
DAILY_ACTIVITY_QUANTITY_FIELDS = {
    "step_count": ("steps", to_int),
    "distance_walking_running": ("distance_m", to_float),
    "flights_climbed": ("floors_climbed", to_int),
    "active_energy_burned": ("active_calories", to_float),
    "basal_energy_burned": ("total_calories", to_float),
    "apple_exercise_time": ("active_minutes", to_int),
}
