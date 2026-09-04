"""TimescaleDB-backed measurement writers.

Phase 5E lifted the per-metric SQL out of ``server.ingestion.handlers``
and ``server.ingestion.sleep`` into this module. The original modules
are now thin re-export shims so existing callers (registry, route,
tests, the catch-all server package re-exports) keep working.

ARCH-001: the pure helpers (parsers, mappers, owner sentinel) now live BELOW
this layer — ``normalization.parsers`` / ``normalization.mappers`` and
``contracts._base.DEFAULT_OWNER_ID`` — so storage no longer imports the API
package (``server.*``). ``server.ingestion.{parsers,mappers}`` are thin
re-export shims for the API layer + plugins. This also retires the old
``server.__init__`` import-cycle workaround entirely.
"""

from __future__ import annotations

from datetime import timedelta
from json import dumps
from typing import TYPE_CHECKING
from uuid import UUID

from contracts._base import DEFAULT_OWNER_ID
from normalization.mappers import (
    ACTIVITY_FIELDS,
    DAILY_ACTIVITY_QUANTITY_FIELDS,
    DEDICATED_TABLES,
)
from normalization.parsers import (
    duration_ms_between,
    first_present,
    parse_date,
    parse_ts,
    to_float,
    to_int,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from storage.results import IngestWriteResult

if TYPE_CHECKING:
    from collections.abc import Iterable

    from contracts.observation import Observation


def _sample_source(sample: dict) -> str | None:
    """Extract the source label from a HealthKit-shaped sample.

    HealthSave iOS / Health Sync / Garmin / Whoop normalizers all use
    one of ``source`` / ``sourceName`` / ``source_id`` / ``device`` /
    ``deviceName`` to carry the device-or-app label. Stored as
    ``source_id`` in the metric tables.
    """
    value = first_present(
        sample, "source", "sourceName", "source_id", "device", "deviceName", "device_id"
    )
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _bump_rejected(metric: str, reason: str) -> None:
    """Phase 5G: surface silent sample rejections.

    Pre-5G the ``if t is None or v is None: continue`` pattern in
    every ingest helper threw away malformed samples without any
    counter or warning log. iOS shipping a date-format change would
    look like ``records: 0`` to operators — "nothing to insert"
    when the truth was "every sample failed to parse." Lazy import
    of the counter so this module stays usable from CLI scripts that
    don't load the FastAPI app.
    """
    try:
        from observability.metrics import INGEST_REJECTED

        INGEST_REJECTED.labels(metric=metric, reason=reason).inc()
    except Exception:  # pragma: no cover - metrics import optional
        # Failing to bump a counter is never a reason to fail ingest.
        pass


def _inserted_new_flag(result: object) -> bool | None:
    """Read ``RETURNING (xmax = 0) AS inserted_new`` when the session exposes it."""

    mappings = getattr(result, "mappings", None)
    if mappings is None:
        return None
    row = mappings().first()
    if row is None:
        return None
    value = row.get("inserted_new") if hasattr(row, "get") else None
    if value is None:
        return None
    return bool(value)


async def _execute_insert_with_result(
    session: AsyncSession,
    sql: str,
    params: dict,
) -> bool | None:
    result = await session.execute(text(sql), params)
    return _inserted_new_flag(result)


def _dedupe_rows_for_upsert(
    rows: list[dict],
    key_cols: list[str],
    metric: str,
    *,
    merge_non_null: bool = False,
) -> tuple[list[dict], int]:
    """Collapse same-conflict-key rows so one multi-row upsert stays valid.

    Postgres rejects a single ``INSERT ... ON CONFLICT DO UPDATE`` whose VALUES
    touch the same conflict key twice (CardinalityViolationError), and real
    HealthKit exports do produce same-timestamp duplicates in one batch. The
    per-row upsert loop absorbed those as sequential updates; the batched path
    must collapse them first. Last row wins, matching sequential semantics;
    ``merge_non_null`` makes later non-None values override per column instead,
    matching COALESCE-style update sets. An in-batch collision is legitimate
    full-export overlap, NOT a rejection — callers count it as
    ``deduped_in_batch`` so the receipt never calls it "rejected".
    """
    seen: dict[tuple, dict] = {}
    dedup_count = 0
    for row in rows:
        key = tuple(row.get(c) for c in key_cols)
        if key in seen:
            dedup_count += 1
            _bump_rejected(metric, "in_batch_dedupe")
            if merge_non_null:
                merged = dict(seen[key])
                merged.update({k: v for k, v in row.items() if v is not None})
                seen[key] = merged
                continue
        seen[key] = row
    return list(seen.values()), dedup_count


async def _execute_batch_insert_with_flags(
    session: AsyncSession,
    table: str,
    sql_columns: list[str],
    bind_keys: list[str],
    rows: list[dict],
    *,
    conflict_clause: str | None = None,
    update_set: str = "",
    flag_column: str = "inserted_new",
) -> list[bool | None]:
    """PERFORMANCE-001: single-round-trip upsert of N rows; returns per-row flags.

    Builds the canonical upsert shape:

        INSERT INTO <table> (<sql_columns>) VALUES ...[, ...]
        [ON CONFLICT (<cols>) DO UPDATE SET ...]
        RETURNING (xmax = 0) AS inserted_new

    ``sql_columns`` is the column list inside INSERT INTO (...) — DB column
    names. ``bind_keys`` is the names of dict keys in each row, which become
    the bind-parameter names ``:bind_key``. The two lists are paired
    positionally: the i-th ``:bind_key_i`` placeholder gets the value of
    dict[i][bind_keys[i]], and Postgres resolves the SQL column list
    against the positional values. This handles legacy aliasing like
    ``metric`` (bind) vs ``metric_name`` (column) without breaking.

    Single-row batches keep the named-param contract (``{bind_key: value}``)
    so existing tests that inspect bound parameters continue to work;
    larger batches bind positionally as ``:bind_key_<index>``. RETURNING
    flags are returned in input order.

    PostgreSQL requires ``VALUES`` to come BEFORE ``ON CONFLICT``; the
    helper handles that automatically.
    """
    if not rows:
        return []
    if not sql_columns or not bind_keys or len(sql_columns) != len(bind_keys):
        return [None] * len(rows)

    insert_prefix = f"INSERT INTO {table} ({', '.join(sql_columns)})"
    if conflict_clause:
        update_clause = (
            f" ON CONFLICT {conflict_clause} DO UPDATE SET {update_set}"
            if update_set
            else f" ON CONFLICT {conflict_clause} DO NOTHING"
        )
    else:
        update_clause = ""
    returning_clause = f" RETURNING (xmax = 0) AS {flag_column}"

    if len(rows) == 1:
        placeholders = ", ".join(f":{key}" for key in bind_keys)
        sql = f"{insert_prefix} VALUES ({placeholders}){update_clause}{returning_clause}"
        params = {key: rows[0].get(key) for key in bind_keys}
        result = await session.execute(text(sql), params)
        mappings = getattr(result, "mappings", None)
        if mappings is None:
            return [None]
        row = mappings().first()
        if row is None:
            return [None]
        value = row.get(flag_column) if hasattr(row, "get") else None
        return [None if value is None else bool(value)]

    # Multi-row batched path: positional binds ``:bind_key_<index>``.
    tuples = ", ".join(
        "(" + ", ".join(f":{key}_{i}" for key in bind_keys) + ")" for i in range(len(rows))
    )
    sql = f"{insert_prefix} VALUES {tuples}{update_clause}{returning_clause}"
    bound: dict[str, object] = {}
    for i, row in enumerate(rows):
        for key in bind_keys:
            bound[f"{key}_{i}"] = row.get(key)
    result = await session.execute(text(sql), bound)
    mappings = getattr(result, "mappings", None)
    flags: list[bool | None] = []
    if mappings is None:
        flags = [None] * len(rows)
    else:
        rows_obj = mappings()
        if hasattr(rows_obj, "all"):
            all_rows = rows_obj.all()
            for row in all_rows:
                value = row.get(flag_column) if hasattr(row, "get") else None
                flags.append(None if value is None else bool(value))
        else:
            for _ in range(len(rows)):
                row = rows_obj.first()
                if row is None:
                    flags.append(None)
                    continue
                value = row.get(flag_column) if hasattr(row, "get") else None
                flags.append(None if value is None else bool(value))
    while len(flags) < len(rows):
        flags.append(None)
    return flags[: len(rows)]


async def _get_or_create_device(session: AsyncSession, device_type: str) -> int:
    result = await session.execute(
        text("SELECT id FROM devices WHERE device_type = :dt"), {"dt": device_type}
    )
    row = result.first()
    if row:
        return row[0]
    result = await session.execute(
        text("INSERT INTO devices (device_type) VALUES (:dt) RETURNING id"),
        {"dt": device_type},
    )
    return result.scalar()


async def _log_raw_ingestion(
    session: AsyncSession, device_id: int | None, raw_payload: dict
) -> int | None:
    result = await session.execute(
        text("""
            INSERT INTO raw_ingestion_log
                (device_id, source_type, endpoint, raw_payload, processed)
            VALUES
                (:device_id, :source_type, :endpoint, CAST(:raw_payload AS jsonb), false)
            RETURNING id
        """),
        {
            "device_id": device_id,
            "source_type": "healthsave",
            "endpoint": "/api/apple/batch",
            "raw_payload": dumps(raw_payload),
        },
    )
    return result.scalar()


async def _mark_raw_ingestion_processed(session: AsyncSession, raw_log_id: int | None) -> None:
    if raw_log_id is None:
        return
    await session.execute(
        text("UPDATE raw_ingestion_log SET processed = true WHERE id = :id"),
        {"id": raw_log_id},
    )


# ──────────────────────────────────────────────────────────────────
#  Per-metric ingest dispatch
# ──────────────────────────────────────────────────────────────────


async def _ingest_metric(
    session: AsyncSession,
    device_id: int,
    metric: str,
    samples: list[dict],
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> IngestWriteResult:
    """Route a parsed batch to the correct writer.

    Falls back to ``quantity_samples`` (catch-all) when no dedicated
    path exists for the metric.
    """
    if metric == "activity_summaries":
        return await _ingest_activity(session, device_id, samples, owner_id=owner_id)
    if metric in DAILY_ACTIVITY_QUANTITY_FIELDS:
        return await _ingest_daily_quantity(session, device_id, metric, samples, owner_id=owner_id)
    if metric == "sleep_analysis":
        return await _ingest_sleep(session, device_id, samples, owner_id=owner_id)
    if metric == "medication_dose_event":
        return await _ingest_medication_dose_events(session, device_id, samples, owner_id=owner_id)
    if metric == "workouts":
        return await _ingest_workouts(session, device_id, samples, owner_id=owner_id)
    if metric == "ecg":
        return await _ingest_ecg(session, device_id, samples, owner_id=owner_id)
    if metric in DEDICATED_TABLES:
        return await _ingest_dedicated(session, device_id, metric, samples, owner_id=owner_id)
    return await _ingest_generic(session, device_id, metric, samples, owner_id=owner_id)


async def _ingest_dedicated(
    session: AsyncSession,
    device_id: int,
    metric: str,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> IngestWriteResult:
    spec = DEDICATED_TABLES[metric]
    rows = []
    rejected_count = 0
    value_col = list(spec["columns"].values())[1]
    for s in samples:
        row = {"device_id": device_id, "owner_id": str(owner_id)}
        for src_key, dst_col in spec["columns"].items():
            val = s.get(src_key)
            if dst_col == "time":
                val = parse_ts(val)
            if dst_col in spec.get("transforms", {}):
                val = spec["transforms"][dst_col](val)
            row[dst_col] = val
        if "defaults" in spec:
            row.update(spec["defaults"])
        # Identity-aware revision key: HKSample.uuid survives delete-and-reinsert
        # revisions, so a stable source_uuid lets the v1 path detect revisions
        # instead of silently landing two values for the day (Plan 2026-09-03).
        # Optional and additive: legacy rows without uuid keep the existing
        # (time, device_id, owner_id) conflict path; uuid-bearing rows take
        # the new (owner_id, source_uuid) partial unique index.
        sample_uuid = s.get("uuid")
        if sample_uuid is not None:
            row["source_uuid"] = str(sample_uuid)
        if row.get("time") and row.get(value_col) is not None:
            rows.append(row)
        else:
            rejected_count += 1
            _bump_rejected(metric, "missing_time_or_value")

    if not rows:
        return IngestWriteResult(rejected=rejected_count)

    # Identity-aware conflict routing: rows carrying a source_uuid upsert on
    # the partial unique index uq_<table>_source_uuid (covers revision/duplicate
    # detection for Apple HealthKit delete-and-reinsert patterns); rows without
    # uuid keep the original (time, device_id, owner_id) conflict path so
    # legacy shipped clients continue to behave exactly as before.
    identity_rows = [r for r in rows if r.get("source_uuid")]
    legacy_rows = [r for r in rows if not r.get("source_uuid")]

    result = IngestWriteResult()
    dedup_count = 0

    if identity_rows:
        # TimescaleDB hypertables require the partitioning column (``time``)
        # in every unique index, so the identity arbiter is
        # (owner_id, source_uuid, time); the partial predicate must be
        # repeated for Postgres to infer the partial unique index. Same
        # uuid always implies same time (HKSample.startDate is immutable),
        # so including time costs no idempotency. sleep_sessions is a
        # plain table and keeps (owner_id, source_uuid) — see
        # _upsert_sleep_session. Migration 025 carries the matching
        # indexes.
        rows_id, dedup_id = _dedupe_rows_for_upsert(
            identity_rows, ["owner_id", "source_uuid", "time"], metric
        )
        dedup_count += dedup_id
        columns = list(rows_id[0].keys())
        update_set = ", ".join(
            f"{c} = EXCLUDED.{c}"
            for c in rows_id[0]
            if c not in ("owner_id", "source_uuid", "time")
        )
        flags_id = await _execute_batch_insert_with_flags(
            session,
            spec["table"],
            columns,
            columns,
            rows_id,
            conflict_clause="(owner_id, source_uuid, time) WHERE source_uuid IS NOT NULL",
            update_set=update_set,
        )
        for inserted_new in flags_id:
            result = result.with_insert_flag(inserted_new)

    if legacy_rows:
        # Dedup within batch on the legacy (time, device_id, owner_id) tuple.
        legacy_conflict_cols = list(spec["conflict"]) + ["owner_id"]
        rows_leg, dedup_leg = _dedupe_rows_for_upsert(
            legacy_rows, legacy_conflict_cols, metric
        )
        dedup_count += dedup_leg
        conflict_sql = ", ".join(legacy_conflict_cols)
        columns = list(rows_leg[0].keys())
        update_set = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in rows_leg[0] if c not in legacy_conflict_cols
        )
        # Migration 025 rebuilt the legacy unique indexes PARTIAL on
        # status='active' (delete-and-reinsert replacements must not hit a
        # superseded row's slot). Postgres needs the predicate repeated to
        # infer the partial arbiter. Rows without a status pre-date the
        # column and default to 'active', so v1 upserts behave unchanged.
        flags_leg = await _execute_batch_insert_with_flags(
            session,
            spec["table"],
            columns,
            columns,
            rows_leg,
            conflict_clause=f"({conflict_sql}) WHERE status = 'active'",
            update_set=update_set,
        )
        for inserted_new in flags_leg:
            result = result.with_insert_flag(inserted_new)

    return result.with_counts(rejected=rejected_count, deduped_in_batch=dedup_count)


async def _ingest_generic(
    session: AsyncSession,
    device_id: int,
    metric: str,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> IngestWriteResult:
    """Insert into the catch-all quantity_samples table."""
    result = IngestWriteResult()
    rejected_count = 0
    rows: list[dict] = []
    for s in samples:
        t = parse_ts(s.get("date"))
        v = to_float(s.get("qty"))
        if t is None or v is None:
            rejected_count += 1
            _bump_rejected(metric, "missing_or_unparseable_date_or_qty")
            continue
        sample_metric = s.get("metric") if isinstance(s.get("metric"), str) else metric
        rows.append(
            {
                "time": t,
                "device_id": device_id,
                "metric_name": sample_metric,
                "value": v,
                "unit": s.get("unit", ""),
                "source_id": s.get("source", ""),
                "owner_id": str(owner_id),
            }
        )

    dedup_count = 0
    if rows:
        rows, dedup_count = _dedupe_rows_for_upsert(
            rows, ["time", "device_id", "metric_name", "owner_id"], metric
        )
        # PERFORMANCE-001: single multi-row VALUES for the whole batch.
        flags = await _execute_batch_insert_with_flags(
            session,
            "quantity_samples",
            ["time", "device_id", "metric_name", "value", "unit", "source_id", "owner_id"],
            ["time", "device_id", "metric_name", "value", "unit", "source_id", "owner_id"],
            rows,
            conflict_clause="(time, device_id, metric_name, owner_id)",
            update_set="value = EXCLUDED.value, unit = EXCLUDED.unit",
        )
        for inserted_new in flags:
            result = result.with_insert_flag(inserted_new)

    return result.with_counts(rejected=rejected_count, deduped_in_batch=dedup_count)


async def _ingest_ecg(
    session: AsyncSession,
    device_id: int,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> IngestWriteResult:
    """Persist ECG batches as average-HR quantity samples for now.

    Scope decision: capture only ``averageHeartRate`` + timestamp here;
    classification, samplingFrequency, and voltage-trace fields belong in
    a future dedicated ECG table.
    """
    # TODO(ISC-3): persist avgHR-less ECG events (AFib / inconclusive / poor
    # reading). Today an ECG with no averageHeartRate is dropped — those are
    # often the most clinically important readings. For now we at least count
    # them honestly as rejected instead of inflating an aggregate skip number.
    result = IngestWriteResult()
    rejected_count = 0
    rows: list[dict] = []
    for sample in samples:
        start = parse_ts(sample.get("start"))
        average_heart_rate = to_float(sample.get("averageHeartRate"))
        if start is None or average_heart_rate is None:
            rejected_count += 1
            _bump_rejected("ecg", "missing_start_or_average_hr")
            continue
        rows.append(
            {
                "time": start,
                "device_id": device_id,
                "metric_name": "ecg_average_heart_rate",
                "value": average_heart_rate,
                "unit": "bpm",
                "source_id": _sample_source(sample),
                "owner_id": str(owner_id),
            }
        )

    dedup_count = 0
    if rows:
        rows, dedup_count = _dedupe_rows_for_upsert(
            rows, ["time", "device_id", "metric_name", "owner_id"], "ecg"
        )
        # PERFORMANCE-001: single multi-row VALUES for the whole batch.
        flags = await _execute_batch_insert_with_flags(
            session,
            "quantity_samples",
            ["time", "device_id", "metric_name", "value", "unit", "source_id", "owner_id"],
            ["time", "device_id", "metric_name", "value", "unit", "source_id", "owner_id"],
            rows,
            conflict_clause="(time, device_id, metric_name, owner_id)",
            update_set="value = EXCLUDED.value, unit = EXCLUDED.unit",
        )
        for inserted_new in flags:
            result = result.with_insert_flag(inserted_new)

    return result.with_counts(rejected=rejected_count, deduped_in_batch=dedup_count)


async def _ingest_medication_dose_events(
    session: AsyncSession,
    device_id: int,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> IngestWriteResult:
    result = IngestWriteResult()
    rejected_count = 0
    allowed_statuses = {
        "taken",
        "skipped",
        "not_interacted",
        "snoozed",
        "notification_not_sent",
        "not_logged",
        "unknown",
    }
    rows: list[dict] = []
    for s in samples:
        t = parse_ts(s.get("date"))
        status = s.get("status") or s.get("medication_status")
        medication_metric = s.get("medication_metric") or s.get("metric")
        if (
            t is None
            or not isinstance(status, str)
            or status not in allowed_statuses
            or not isinstance(medication_metric, str)
            or not medication_metric
        ):
            rejected_count += 1
            _bump_rejected("medication_dose_event", "missing_or_invalid_time_status_or_metric")
            continue
        rows.append(
            {
                "time": t,
                "scheduled_time": parse_ts(s.get("scheduled_date")),
                "device_id": device_id,
                "medication_metric": medication_metric,
                "medication_name": s.get("medication_name", ""),
                "status": status,
                "scheduled_dose_quantity": to_float(s.get("scheduled_dose_quantity")),
                "dose_quantity": to_float(s.get("dose_quantity")),
                "unit": s.get("medication_unit") or s.get("unit", ""),
                "source_id": s.get("source", ""),
                "medication_concept_id": s.get("medication_concept_id", ""),
                "owner_id": str(owner_id),
            }
        )

    dedup_count = 0
    if rows:
        rows, dedup_count = _dedupe_rows_for_upsert(
            rows,
            ["time", "device_id", "medication_metric", "owner_id"],
            "medication_dose_event",
        )
        # PERFORMANCE-001: single multi-row VALUES for the whole batch.
        flags = await _execute_batch_insert_with_flags(
            session,
            "medication_dose_events",
            [
                "time",
                "scheduled_time",
                "device_id",
                "medication_metric",
                "medication_name",
                "status",
                "scheduled_dose_quantity",
                "dose_quantity",
                "unit",
                "source_id",
                "medication_concept_id",
                "owner_id",
            ],
            [
                "time",
                "scheduled_time",
                "device_id",
                "medication_metric",
                "medication_name",
                "status",
                "scheduled_dose_quantity",
                "dose_quantity",
                "unit",
                "source_id",
                "medication_concept_id",
                "owner_id",
            ],
            rows,
            conflict_clause="(time, device_id, medication_metric, owner_id)",
            update_set=(
                "scheduled_time = EXCLUDED.scheduled_time, "
                "medication_name = EXCLUDED.medication_name, "
                "status = EXCLUDED.status, "
                "scheduled_dose_quantity = EXCLUDED.scheduled_dose_quantity, "
                "dose_quantity = EXCLUDED.dose_quantity, "
                "unit = EXCLUDED.unit, "
                "source_id = EXCLUDED.source_id, "
                "medication_concept_id = EXCLUDED.medication_concept_id"
            ),
        )
        for inserted_new in flags:
            result = result.with_insert_flag(inserted_new)

    return result.with_counts(rejected=rejected_count, deduped_in_batch=dedup_count)


async def _ingest_activity(
    session: AsyncSession,
    device_id: int,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> IngestWriteResult:
    result = IngestWriteResult()
    rejected_count = 0
    rows: list[dict] = []
    all_metric_cols: set[str] = set()
    for s in samples:
        d = parse_date(s.get("date"))
        if not d:
            rejected_count += 1
            _bump_rejected("activity_summaries", "missing_or_unparseable_date")
            continue

        row: dict = {"date": d, "device_id": device_id, "owner_id": str(owner_id)}
        for src_key, dst_col in ACTIVITY_FIELDS.items():
            if src_key in s:
                row[dst_col] = s[src_key]
                all_metric_cols.add(dst_col)
        source_id = _sample_source(s)
        if source_id is not None:
            row["source_id"] = source_id
        rows.append(row)

    dedup_count = 0
    if rows:
        # Merge same-day rows column-wise: the update set is COALESCE-style, so
        # sequential upserts let later non-None values win per column.
        rows, dedup_count = _dedupe_rows_for_upsert(
            rows, ["date", "device_id", "owner_id"], "activity_summaries", merge_non_null=True
        )
        # PERFORMANCE-001: single multi-row VALUES for the whole batch.
        # Union of all metric columns across rows; pad missing with NULL so
        # every tuple has the same shape (required by the batch helper).
        fixed_cols = ["date", "device_id", "owner_id", "source_id"]
        metric_cols = sorted(all_metric_cols)
        cols = fixed_cols + metric_cols
        for row in rows:
            for col in metric_cols:
                row.setdefault(col, None)
        updates = ", ".join(
            f"{k} = COALESCE(EXCLUDED.{k}, daily_activity.{k})" for k in metric_cols + ["source_id"]
        )
        # Reorder dicts so columns are in the agreed order.
        ordered_rows = [{c: r.get(c) for c in cols} for r in rows]
        flags = await _execute_batch_insert_with_flags(
            session,
            "daily_activity",
            cols,  # sql_columns
            cols,  # bind_keys — keys already match column names
            ordered_rows,
            conflict_clause="(date, device_id, owner_id)",
            update_set=updates,
        )
        for inserted_new in flags:
            result = result.with_insert_flag(inserted_new)

    return result.with_counts(rejected=rejected_count, deduped_in_batch=dedup_count)


async def _ingest_daily_quantity(
    session: AsyncSession,
    device_id: int,
    metric: str,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> IngestWriteResult:
    column, converter = DAILY_ACTIVITY_QUANTITY_FIELDS[metric]
    result = IngestWriteResult()
    rejected_count = 0
    rows: list[dict] = []
    for sample in samples:
        d = parse_date(sample.get("date"))
        value = converter(sample.get("qty"))
        if not d or value is None:
            rejected_count += 1
            _bump_rejected(metric, "missing_or_unparseable_date_or_qty")
            continue
        rows.append(
            {
                "date": d,
                "device_id": device_id,
                "owner_id": str(owner_id),
                "source_id": _sample_source(sample),
                column: value,
            }
        )

    dedup_count = 0
    if rows:
        # Merge same-day rows: value column always present (last wins), source_id
        # COALESCE-style (last non-None wins) — merge_non_null matches both.
        rows, dedup_count = _dedupe_rows_for_upsert(
            rows, ["date", "device_id", "owner_id"], metric, merge_non_null=True
        )
        # PERFORMANCE-001: single multi-row VALUES for the whole batch.
        flags = await _execute_batch_insert_with_flags(
            session,
            "daily_activity",
            ["date", "device_id", "owner_id", "source_id", column],  # sql_columns
            ["date", "device_id", "owner_id", "source_id", column],  # bind_keys
            rows,
            conflict_clause="(date, device_id, owner_id)",
            update_set=(
                f"{column} = EXCLUDED.{column}, "
                "source_id = COALESCE(EXCLUDED.source_id, daily_activity.source_id)"
            ),
        )
        for inserted_new in flags:
            result = result.with_insert_flag(inserted_new)

    return result.with_counts(rejected=rejected_count, deduped_in_batch=dedup_count)


async def _ingest_workouts(
    session: AsyncSession,
    device_id: int,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> IngestWriteResult:
    result = IngestWriteResult()
    rejected_count = 0
    rows: list[dict] = []
    for s in samples:
        start = parse_ts(first_present(s, "start_date", "startDate", "start", "date"))
        end = parse_ts(first_present(s, "end_date", "endDate", "end"))
        if not start or not end:
            rejected_count += 1
            _bump_rejected("workouts", "missing_or_unparseable_start_or_end")
            continue
        duration_ms = first_present(s, "duration_ms")
        if duration_ms is None:
            duration_seconds = to_float(first_present(s, "duration"))
            duration_ms = int(duration_seconds * 1000) if duration_seconds is not None else None
        else:
            duration_ms = to_int(duration_ms)
        rows.append(
            {
                "device_id": device_id,
                "sport_type": first_present(s, "sport_type", "sportType", "name") or "unknown",
                "start_time": start,
                "end_time": end,
                "duration_ms": duration_ms,
                "avg_hr": to_float(first_present(s, "avg_hr", "avgHeartRate")),
                "max_hr": to_float(first_present(s, "max_hr", "maxHeartRate")),
                "calories": to_float(first_present(s, "calories", "activeEnergy")),
                "distance_m": to_float(first_present(s, "distance_m", "distance")),
                "source_id": _sample_source(s),
                "owner_id": str(owner_id),
            }
        )

    dedup_count = 0
    if rows:
        rows, dedup_count = _dedupe_rows_for_upsert(
            rows, ["device_id", "start_time", "owner_id"], "workouts"
        )
        # PERFORMANCE-001: single multi-row VALUES for the whole batch.
        flags = await _execute_batch_insert_with_flags(
            session,
            "workouts",
            [
                "device_id",
                "sport_type",
                "start_time",
                "end_time",
                "duration_ms",
                "avg_hr",
                "max_hr",
                "calories",
                "distance_m",
                "source_id",
                "owner_id",
            ],
            [
                "device_id",
                "sport_type",
                "start_time",
                "end_time",
                "duration_ms",
                "avg_hr",
                "max_hr",
                "calories",
                "distance_m",
                "source_id",
                "owner_id",
            ],
            rows,
            conflict_clause="(device_id, start_time, owner_id)",
            update_set=(
                "sport_type = EXCLUDED.sport_type, "
                "end_time = EXCLUDED.end_time, "
                "duration_ms = EXCLUDED.duration_ms, "
                "avg_hr = EXCLUDED.avg_hr, "
                "max_hr = EXCLUDED.max_hr, "
                "calories = EXCLUDED.calories, "
                "distance_m = EXCLUDED.distance_m, "
                "source_id = COALESCE(EXCLUDED.source_id, workouts.source_id)"
            ),
        )
        for inserted_new in flags:
            result = result.with_insert_flag(inserted_new)

    return result.with_counts(rejected=rejected_count, deduped_in_batch=dedup_count)


# ──────────────────────────────────────────────────────────────────
#  Sleep — segment grouping + session/stage upserts
# ──────────────────────────────────────────────────────────────────


def sleep_stage_segments(samples: list[dict]) -> list[dict]:
    segments = []
    for sample in samples:
        start = parse_ts(first_present(sample, "start_date", "startDate", "start", "date"))
        end = parse_ts(first_present(sample, "end_date", "endDate", "end"))
        if not start or not end or end <= start:
            continue
        segments.append(
            {
                "start": start,
                "end": end,
                "stage": str(first_present(sample, "value", "stage") or "").strip().lower(),
                "source": _sample_source(sample),
            }
        )

    segments.sort(key=lambda segment: segment["start"])
    return segments


def sleep_session_rows(device_id: int, samples: list[dict]) -> list[dict]:
    """Aggregate HealthKit sleep stage samples into session rows."""
    segments = sleep_stage_segments(samples)
    if not segments:
        return []

    sessions = []
    gap_threshold = timedelta(hours=4)
    current = None

    for segment in segments:
        start = segment["start"]
        end = segment["end"]

        if current is None or start - current["last_end"] > gap_threshold:
            if current is not None:
                sessions.append(current)
            current = {
                "start": start,
                "end": end,
                "last_end": end,
                "deep_ms": 0,
                "rem_ms": 0,
                "light_ms": 0,
                "awake_ms": 0,
                "segments": [],
            }
        else:
            current["end"] = max(current["end"], end)
            current["last_end"] = max(current["last_end"], end)

        current["segments"].append(segment)

        bucket = None
        if segment["stage"] == "deep":
            bucket = "deep_ms"
        elif segment["stage"] == "rem":
            bucket = "rem_ms"
        elif segment["stage"] == "awake":
            bucket = "awake_ms"
        elif segment["stage"] in {"core", "light", "asleep", "asleep unspecified"}:
            bucket = "light_ms"

        if bucket:
            current[bucket] += duration_ms_between(start, end)

    if current is not None:
        sessions.append(current)

    rows = []
    for session in sessions:
        total_duration_ms = session["deep_ms"] + session["rem_ms"] + session["light_ms"]
        if total_duration_ms == 0 and session["awake_ms"] == 0:
            continue
        # Pick the first non-null source from the session's segments.
        # In practice all segments share a source (single watch logging
        # one night of sleep); this guards against mixed-source noise.
        source_id = next(
            (seg.get("source") for seg in session["segments"] if seg.get("source")),
            None,
        )
        # Identity-aware pass-through: Apple HealthKit sleep stages each
        # carry a HKSample.uuid. We propagate the first non-null stage uuid
        # to the session row so the new partial unique index on
        # sleep_sessions.source_uuid catches delete-and-reinsert revisions
        # for the whole session. Legacy / v1 clients leave this empty
        # and continue to use (device_id, start_time, owner_id) upserts.
        session_source_uuid = next(
            (seg.get("uuid") for seg in session["segments"] if seg.get("uuid")),
            None,
        )
        rows.append(
            {
                "device_id": device_id,
                "start": session["start"],
                "end": session["end"],
                "total": total_duration_ms,
                "deep": session["deep_ms"],
                "rem": session["rem_ms"],
                "light": session["light_ms"],
                "awake": session["awake_ms"],
                "rr": None,
                "source_id": source_id,
                "source_uuid": session_source_uuid,
                "segments": session["segments"],
            }
        )
    return rows
async def _upsert_sleep_session(session: AsyncSession, row: dict) -> int:
    row.setdefault("owner_id", str(DEFAULT_OWNER_ID))
    row.setdefault("source_id", None)
    # Identity-aware two-arm upsert: when a session_source_uuid was lifted
    # from the underlying stages we conflict on (owner_id, source_uuid) so
    # delete-and-reinsert revisions hit the partial unique index instead of
    # landing two session rows for one night; when no uuid is present we
    # keep the legacy (device_id, start_time, owner_id) conflict path so
    # shipped clients behave exactly as before (Plan 2026-09-03).
    if row.get("source_uuid"):
        result = await session.execute(
            text("""
                INSERT INTO sleep_sessions (device_id, start_time, end_time, total_duration_ms,
                    deep_ms, rem_ms, light_ms, awake_ms, respiratory_rate, owner_id, source_id,
                    source_uuid)
                VALUES (:device_id, :start, :end, :total, :deep, :rem, :light, :awake, :rr,
                    :owner_id, :source_id, :source_uuid)
                ON CONFLICT (owner_id, source_uuid) WHERE source_uuid IS NOT NULL DO UPDATE SET
                    end_time = EXCLUDED.end_time,
                    total_duration_ms = EXCLUDED.total_duration_ms,
                    deep_ms = EXCLUDED.deep_ms,
                    rem_ms = EXCLUDED.rem_ms,
                    light_ms = EXCLUDED.light_ms,
                    awake_ms = EXCLUDED.awake_ms,
                    respiratory_rate = EXCLUDED.respiratory_rate,
                    source_id = COALESCE(EXCLUDED.source_id, sleep_sessions.source_id)
                RETURNING id
            """),
            row,
        )
        return result.scalar()
    result = await session.execute(
        text("""
            INSERT INTO sleep_sessions (device_id, start_time, end_time, total_duration_ms,
                deep_ms, rem_ms, light_ms, awake_ms, respiratory_rate, owner_id, source_id)
            VALUES (:device_id, :start, :end, :total, :deep, :rem, :light, :awake, :rr,
                :owner_id, :source_id)
            ON CONFLICT (device_id, start_time, owner_id) WHERE status = 'active' DO UPDATE SET
                end_time = EXCLUDED.end_time,
                total_duration_ms = EXCLUDED.total_duration_ms,
                deep_ms = EXCLUDED.deep_ms,
                rem_ms = EXCLUDED.rem_ms,
                light_ms = EXCLUDED.light_ms,
                awake_ms = EXCLUDED.awake_ms,
                respiratory_rate = EXCLUDED.respiratory_rate,
                source_id = COALESCE(EXCLUDED.source_id, sleep_sessions.source_id)
            RETURNING id
        """),
        row,
    )
    return result.scalar()


async def _upsert_sleep_stages(
    session: AsyncSession,
    device_id: int,
    session_id: int | None,
    segments: list[dict],
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> None:
    # PERFORMANCE-001: gather rows, then one multi-row INSERT.
    rows: list[dict] = []
    for segment in segments:
        duration_ms = duration_ms_between(segment["start"], segment["end"])
        if duration_ms <= 0:
            continue
        rows.append(
            {
                "time": segment["start"],
                "device_id": device_id,
                "session_id": session_id,
                "stage": segment["stage"],
                "duration_ms": duration_ms,
                "owner_id": str(owner_id),
            }
        )
    if not rows:
        return
    rows, _ = _dedupe_rows_for_upsert(
        rows, ["time", "device_id", "stage", "owner_id"], "sleep_stages"
    )
    # PERFORMANCE-001: one multi-row INSERT for the whole sleep session's stages
    # instead of one execute() per stage row. No RETURNING needed here — we
    # only care that the writes happened; the caller counts via rowcount.
    await _execute_batch_insert_with_flags(
        session,
        "sleep_stages",
        ["time", "device_id", "session_id", "stage", "duration_ms", "owner_id"],
        ["time", "device_id", "session_id", "stage", "duration_ms", "owner_id"],
        rows,
        conflict_clause="(time, device_id, stage, owner_id)",
        update_set="session_id = EXCLUDED.session_id, duration_ms = EXCLUDED.duration_ms",
    )


async def ingest_sleep(
    session: AsyncSession,
    device_id: int,
    samples: list,
    *,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> IngestWriteResult:
    # Aggregating path: many raw stage samples roll up into M sessions. Every
    # stage row is preserved in sleep_stages, so the N-stages -> M-sessions
    # difference is AGGREGATION, not rejection. accepted = sessions, rejected = 0.
    # (Deriving rejected as received-accepted here is what reported ~95% of a
    # healthy sleep sync as "rejected".)
    if any("startDate" in sample or "value" in sample for sample in samples):
        rows = sleep_session_rows(device_id, samples)
        count = 0
        for row in rows:
            segments = row.pop("segments", [])
            row["owner_id"] = str(owner_id)
            session_id = await _upsert_sleep_session(session, row)
            await _upsert_sleep_stages(session, device_id, session_id, segments, owner_id=owner_id)
            count += 1
        return IngestWriteResult(accepted=count)

    count = 0
    rejected_count = 0
    for s in samples:
        start = parse_ts(first_present(s, "start_date", "startDate", "date"))
        end = parse_ts(first_present(s, "end_date", "endDate"))
        if not start or not end:
            rejected_count += 1
            _bump_rejected("sleep_analysis", "missing_or_unparseable_start_or_end")
            continue
        await _upsert_sleep_session(
            session,
            {
                "device_id": device_id,
                "start": start,
                "end": end,
                "total": to_int(s.get("total_duration_ms")),
                "deep": to_int(s.get("deep_ms")),
                "rem": to_int(s.get("rem_ms")),
                "light": to_int(s.get("light_ms") or s.get("core_ms")),
                "awake": to_int(s.get("awake_ms")),
                "rr": to_float(s.get("respiratory_rate")),
                "owner_id": str(owner_id),
            },
        )
        count += 1
    return IngestWriteResult(accepted=count, rejected=rejected_count)


# ──────────────────────────────────────────────────────────────────
#  Identity-aware deletions (Slice 2 of 2026-09-03 plan)
# ──────────────────────────────────────────────────────────────────
#
# Apple HealthKit revises RHR and reshuffles sleep via
# delete-and-reinsert. The v1 ingest path's (time, device_id, owner_id)
# conflict clause silently landed two values for the day when that
# happened; migration 025 added a partial unique index on
# source_uuid plus a status='active'|'superseded' column to catch the
# revision properly. These helpers are the storage-zone surface for
# "mark rows superseded by HKSample.uuid". They are intentionally narrow
# (UUIDs only, no fuzzy matching) so the v2 route can call them safely
# with operator-vetted uuid lists.


# Tables that carry source_uuid after migration 025. Kept narrow: each
# entry must (a) have a source_uuid column and (b) accept status
# 'active'|'superseded'. Adding a table here requires a matching
# migration; do not append without one.
SOURCE_UUID_TABLES: tuple[str, ...] = (
    "heart_rate",
    "hrv",
    "blood_oxygen",
    "body_temperature",
    "sleep_sessions",
)


async def mark_canonical_observations_superseded(
    session: AsyncSession,
    *,
    owner_id: UUID,
    uuids: list[str],
) -> int:
    """Mark canonical rows ``superseded`` for the given HKSample UUIDs.

    Uses ``source_record_uid`` — the canonical layer's per-sample identity
    populated from ``sample['uuid']`` by the v2 normalizer (see
    ``packages/py/normalization/apple.py`` line 273). Idempotent: re-applying
    a deletion once ``status='superseded'`` is a no-op.
    """
    if not uuids:
        return 0
    result = await session.execute(
        text(
            """
            UPDATE canonical_observations
               SET status = 'superseded'
             WHERE owner_id = :owner_id
               AND status = 'active'
               AND source_record_uid = ANY(:uuids)
            """
        ),
        {"owner_id": str(owner_id), "uuids": uuids},
    )
    return result.rowcount or 0


async def mark_v1_dedicated_superseded(
    session: AsyncSession,
    *,
    owner_id: UUID,
    uuids: list[str],
    tables: tuple[str, ...] = SOURCE_UUID_TABLES,
) -> dict[str, int]:
    """Mark v1 dedicated table rows ``superseded`` for the given UUIDs.

    Returns a per-table count of rows updated. Each table has the
    partial unique index ``uq_<table>_source_uuid`` from migration 025, so
    the UPDATE shape is identical across the five tables. Idempotent.
    The caller passes a ``tables`` tuple to keep this function testable
    against a subset of tables; production callers use ``SOURCE_UUID_TABLES``.
    """
    counts: dict[str, int] = {}
    if not uuids:
        return counts
    for table in tables:
        result = await session.execute(
            text(
                f"""
                UPDATE {table}
                   SET status = 'superseded'
                 WHERE owner_id = :owner_id
                   AND status = 'active'
                   AND source_uuid = ANY(:uuids)
                """
            ),
            {"owner_id": str(owner_id), "uuids": uuids},
        )
        counts[table] = result.rowcount or 0
    return counts


# Historical private alias preserved for the dispatch table in this
# module + any external callers that reach in via attribute access.
_ingest_sleep = ingest_sleep


def _quantity_sample_from_observation(obs: Observation) -> dict | None:
    """Convert a canonical quantity observation to the v1 writer shape.

    This is intentionally narrow. Non-quantity canonical records
    (sleep stages, workouts, events) are projection gaps today, so the
    plugin can fall back to the existing raw-sample writers that still
    own those shapes.
    """

    value = getattr(obs, "value", None)
    if getattr(value, "type", None) != "quantity":
        return None

    qty = getattr(value, "canonical_value", None)
    if qty is None:
        qty = getattr(value, "value", None)
    if qty is None:
        return None

    unit = getattr(value, "canonical_unit", None) or getattr(value, "unit", None) or ""
    provenance = getattr(obs, "provenance", None)
    source = getattr(provenance, "source_plugin_id", None)
    if not source:
        source_id = getattr(obs, "source_id", None)
        source = str(source_id) if source_id else None

    # Plan 2026-09-03 (Slice 4): carry the canonical observation's
    # source_record_uid onto the projected row as the v1 writer's ``uuid``
    # key. _ingest_dedicated's identity arm reads it and stamps
    # source_uuid, so canonical-derived rows are supersedeable by
    # mark_v1_dedicated_superseded exactly like rows written straight
    # from the wire. Without this the projection path silently dropped
    # the identity and deletions could only supersede canonical rows.
    row = {
        "date": obs.interval_start.isoformat(),
        "qty": qty,
        "unit": unit,
        "source": source,
    }
    source_record_uid = getattr(obs, "source_record_uid", None)
    if source_record_uid:
        row["uuid"] = source_record_uid
    return row


class TimescaleMeasurementProjectionRepository:
    """Project canonical observations into the v1 Timescale metric tables."""

    async def project_observations(
        self,
        session: AsyncSession,
        device_id: int | str,
        metric: str,
        observations: Iterable[Observation],
        owner_id: UUID = DEFAULT_OWNER_ID,
    ) -> IngestWriteResult:
        samples = []
        for obs in observations:
            sample = _quantity_sample_from_observation(obs)
            if sample is not None:
                samples.append(sample)

        if not samples:
            return IngestWriteResult()

        return await _ingest_metric(session, int(device_id), metric, samples, owner_id=owner_id)


# ──────────────────────────────────────────────────────────────────
#  Phase-5C MeasurementRepository class skeleton kept as a name —
#  Phase 5F may attach methods (insert_heart_rate, insert_workout,
#  fetch_series). Today the class is empty; the SQL above is the
#  shipped surface and module-level functions are how callers reach
#  it.
# ──────────────────────────────────────────────────────────────────


class TimescaleMeasurementRepository:
    """Skeleton for the eventual Protocol-style class. Today the
    public surface is the module-level functions above; future phases
    may bind them as methods if injection is wanted."""


default_repository = TimescaleMeasurementRepository()
default_projection_repository = TimescaleMeasurementProjectionRepository()
