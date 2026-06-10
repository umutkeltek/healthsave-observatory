"""TimescaleDB registry for Source / Device / Stream identity (R2 Track A).

All SQL lives here (the storage zone). Callers pass an ``AsyncSession`` and own the
transaction (same contract as the other timescale repos). The pure, deterministic
UUID derivation lives in ``normalization.identity``; this module only persists and
reads the registry tables created in migration 015.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from normalization import identity
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SOURCE_UPSERT = text(
    """
    INSERT INTO sources (id, owner_id, plugin_id, display_name)
    VALUES (:id, :owner_id, :plugin_id, :display_name)
    ON CONFLICT (owner_id, plugin_id) DO UPDATE SET last_seen_at = now()
    """
)

_STREAM_UPSERT = text(
    """
    INSERT INTO source_device_streams
        (id, owner_id, source_plugin_id, origin_key, device_label)
    VALUES (:id, :owner_id, :plugin_id, :origin_key, :device_label)
    ON CONFLICT (owner_id, source_plugin_id, origin_key)
    DO UPDATE SET last_seen_at = now(), device_label = EXCLUDED.device_label
    """
)


async def record_origins(
    session: AsyncSession,
    *,
    owner_id: UUID,
    plugin_id: str,
    origins: Iterable[str | None],
) -> int:
    """Upsert the Source + one Stream per distinct origin seen in a batch.

    Idempotent (deterministic ids + ON CONFLICT). Returns the number of distinct
    streams touched. The caller owns the transaction; callers that want isolation
    from the main batch should wrap this in a savepoint.
    """
    await session.execute(
        _SOURCE_UPSERT,
        {
            "id": str(identity.source_uuid(owner_id, plugin_id)),
            "owner_id": str(owner_id),
            "plugin_id": plugin_id,
            "display_name": plugin_id,
        },
    )
    seen: set[str] = set()
    for raw in origins:
        origin_key = identity.normalize_origin(raw)
        if origin_key in seen:
            continue
        seen.add(origin_key)
        await session.execute(
            _STREAM_UPSERT,
            {
                "id": str(identity.stream_id(owner_id, plugin_id, origin_key)),
                "owner_id": str(owner_id),
                "plugin_id": plugin_id,
                "origin_key": origin_key,
                "device_label": (raw or "").strip() or "Unknown",
            },
        )
    return len(seen)


# Pagination is additive: limit=None preserves the original unbounded reads
# byte-for-byte. Ordering is part of the contract (documented in API.md) so
# offset pagination stays stable: sources by plugin_id, streams by
# last_seen_at DESC, devices by device_label.
def _page(sql: str, params: dict[str, Any], limit: int | None, offset: int) -> tuple[str, dict]:
    if limit is None:
        return sql, params
    return f"{sql} LIMIT :limit OFFSET :offset", {**params, "limit": limit, "offset": offset}


async def list_sources(
    session: AsyncSession, owner_id: UUID, *, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    sql, params = _page(
        "SELECT id, plugin_id, display_name, first_seen_at, last_seen_at "
        "FROM sources WHERE owner_id = :owner ORDER BY plugin_id",
        {"owner": str(owner_id)},
        limit,
        offset,
    )
    result = await session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


async def count_sources(session: AsyncSession, owner_id: UUID) -> int:
    result = await session.execute(
        text("SELECT count(*) FROM sources WHERE owner_id = :owner"),
        {"owner": str(owner_id)},
    )
    return int(result.scalar() or 0)


async def list_streams(
    session: AsyncSession, owner_id: UUID, *, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    sql, params = _page(
        "SELECT id, source_plugin_id, origin_key, device_label, "
        "first_seen_at, last_seen_at FROM source_device_streams "
        "WHERE owner_id = :owner ORDER BY last_seen_at DESC",
        {"owner": str(owner_id)},
        limit,
        offset,
    )
    result = await session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


async def count_streams(session: AsyncSession, owner_id: UUID) -> int:
    result = await session.execute(
        text("SELECT count(*) FROM source_device_streams WHERE owner_id = :owner"),
        {"owner": str(owner_id)},
    )
    return int(result.scalar() or 0)


async def list_devices(
    session: AsyncSession, owner_id: UUID, *, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    """Distinct emitters, derived from streams (no separate devices table yet)."""
    sql, params = _page(
        "SELECT device_label, count(*) AS stream_count, "
        "min(first_seen_at) AS first_seen_at, max(last_seen_at) AS last_seen_at "
        "FROM source_device_streams WHERE owner_id = :owner "
        "GROUP BY device_label ORDER BY device_label",
        {"owner": str(owner_id)},
        limit,
        offset,
    )
    result = await session.execute(text(sql), params)
    return [dict(row._mapping) for row in result]


async def count_devices(session: AsyncSession, owner_id: UUID) -> int:
    result = await session.execute(
        text(
            "SELECT count(DISTINCT device_label) FROM source_device_streams WHERE owner_id = :owner"
        ),
        {"owner": str(owner_id)},
    )
    return int(result.scalar() or 0)


async def get_stream(
    session: AsyncSession, owner_id: UUID, stream_id: UUID
) -> dict[str, Any] | None:
    result = await session.execute(
        text(
            "SELECT id, source_plugin_id, origin_key, device_label, "
            "first_seen_at, last_seen_at FROM source_device_streams "
            "WHERE owner_id = :owner AND id = :id"
        ),
        {"owner": str(owner_id), "id": str(stream_id)},
    )
    row = result.first()
    return dict(row._mapping) if row else None
