"""Health Data Hub server package.

Minimal FastAPI server that receives health data from a compatible client
such as the HealthSave iOS app and stores it in TimescaleDB. HealthSave
expects a base server URL like ``http://your-server:8000`` and appends
the batch endpoint itself.

Env vars:
    DATABASE_URL  - PostgreSQL connection string (default: see below)
    API_KEY       - Optional API key for authentication (leave empty to disable)

The existing test suite (``tests/test_api_contract.py``) imports this
package as ``import server`` and calls ``server.apple_batch`` /
``server.apple_status`` directly, so we re-export those handlers plus
the handful of helpers and data tables that are reasonable to reach for
from the top-level namespace. Internal ingestion state is not re-exported
here - call it through ``server.ingestion.*`` in new code.
"""

from .api.deps import API_KEY, verify_api_key
from .api.ingest import apple_batch
from .api.status import apple_status
from .db.session import DATABASE_URL, async_session, engine, get_session
from .ingestion.handlers import (
    _get_or_create_device,
    _ingest_activity,
    _ingest_daily_quantity,
    _ingest_dedicated,
    _ingest_generic,
    _ingest_metric,
    _ingest_sleep,
    _ingest_workouts,
    _log_raw_ingestion,
    _mark_raw_ingestion_processed,
)
from .ingestion.mappers import (
    ACTIVITY_FIELDS,
    DAILY_ACTIVITY_QUANTITY_FIELDS,
    DEDICATED_TABLES,
)
from .ingestion.parsers import (
    duration_ms_between,
    first_present,
    group_samples_by_device,
    normalize_blood_oxygen,
    parse_date,
    parse_ts,
    sample_device_name,
    to_float,
    to_int,
)
from .ingestion.sleep import (
    _upsert_sleep_session,
    _upsert_sleep_stages,
    sleep_session_rows,
    sleep_stage_segments,
)
from .main import app, lifespan

__all__ = [
    "ACTIVITY_FIELDS",
    "API_KEY",
    "DAILY_ACTIVITY_QUANTITY_FIELDS",
    "DATABASE_URL",
    "DEDICATED_TABLES",
    "_get_or_create_device",
    "_ingest_activity",
    "_ingest_daily_quantity",
    "_ingest_dedicated",
    "_ingest_generic",
    "_ingest_metric",
    "_ingest_sleep",
    "_ingest_workouts",
    "_log_raw_ingestion",
    "_mark_raw_ingestion_processed",
    "_upsert_sleep_session",
    "_upsert_sleep_stages",
    "apple_batch",
    "apple_status",
    "app",
    "async_session",
    "duration_ms_between",
    "engine",
    "first_present",
    "get_session",
    "group_samples_by_device",
    "lifespan",
    "normalize_blood_oxygen",
    "parse_date",
    "parse_ts",
    "sample_device_name",
    "sleep_session_rows",
    "sleep_stage_segments",
    "to_float",
    "to_int",
    "verify_api_key",
]
