"""Per-provider, per-owner "last successful poll" cursor (``source_poll_cursors``).

The worker reads it before a source poll to backfill a gap longer than the
plugin's own lookback, and writes it in the same transaction that commits the
poll's data, so the cursor never claims a poll whose writes rolled back. The
caller owns the transaction boundary.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from auth import DEFAULT_OWNER_ID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_last_successful_poll(
    session: AsyncSession,
    *,
    provider: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> datetime | None:
    """When ``provider``'s poll last succeeded for ``owner_id``, or None if never."""
    row = (
        await session.execute(
            text(
                """
                SELECT last_success_at
                  FROM source_poll_cursors
                 WHERE owner_id = :owner_id AND provider = :provider
                """
            ),
            {"owner_id": str(owner_id), "provider": provider},
        )
    ).first()
    return row.last_success_at if row is not None else None


async def record_successful_poll(
    session: AsyncSession,
    *,
    provider: str,
    polled_at: datetime,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> None:
    """Move the cursor to ``polled_at`` (the poll's start). It never moves back."""
    await session.execute(
        text(
            """
            INSERT INTO source_poll_cursors (owner_id, provider, last_success_at)
            VALUES (:owner_id, :provider, :polled_at)
            ON CONFLICT (owner_id, provider) DO UPDATE
               SET last_success_at = GREATEST(
                       source_poll_cursors.last_success_at, EXCLUDED.last_success_at
                   ),
                   updated_at = NOW()
            """
        ),
        {"owner_id": str(owner_id), "provider": provider, "polled_at": polled_at},
    )
