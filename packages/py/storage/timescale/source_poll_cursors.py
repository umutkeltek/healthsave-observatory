"""Per-provider, per-owner "last successful poll" cursor (``source_poll_cursors``).

The worker reads it before a source poll to backfill a gap longer than the
plugin's own lookback, and writes it in the same transaction that commits the
poll's data, so the cursor never claims a poll whose writes rolled back. A
widened poll that fails is counted so the worker can stop retrying a window
the vendor will not serve: a rejected range in ``backfill_failures`` (032), a
server error, timeout or rate limit while the vendor still answered the
default window in ``backfill_outage_failures`` (033). The gap it
gives up on is kept in ``unfilled_gap_start``/``unfilled_gap_end``. The caller
owns the transaction boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from auth import DEFAULT_OWNER_ID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class PollCursor:
    last_success_at: datetime
    backfill_failures: int = 0
    backfill_outage_failures: int = 0


async def get_poll_cursor(
    session: AsyncSession,
    *,
    provider: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
) -> PollCursor | None:
    """The cursor for ``provider`` and ``owner_id``, or None if no poll succeeded yet."""
    row = (
        await session.execute(
            text(
                """
                SELECT last_success_at, backfill_failures, backfill_outage_failures
                  FROM source_poll_cursors
                 WHERE owner_id = :owner_id AND provider = :provider
                """
            ),
            {"owner_id": str(owner_id), "provider": provider},
        )
    ).first()
    if row is None:
        return None
    return PollCursor(
        last_success_at=row.last_success_at,
        backfill_failures=row.backfill_failures,
        backfill_outage_failures=row.backfill_outage_failures,
    )


async def record_successful_poll(
    session: AsyncSession,
    *,
    provider: str,
    polled_at: datetime,
    owner_id: UUID = DEFAULT_OWNER_ID,
    unfilled_gap: tuple[datetime, datetime] | None = None,
) -> None:
    """Move the cursor to ``polled_at`` (the poll's start) and clear both failure counts.

    The cursor never moves back. ``unfilled_gap`` records the window a
    narrowed poll gave up on; without it the last recorded gap is kept.
    """
    gap_start, gap_end = unfilled_gap if unfilled_gap is not None else (None, None)
    await session.execute(
        text(
            """
            INSERT INTO source_poll_cursors
                (owner_id, provider, last_success_at, unfilled_gap_start, unfilled_gap_end)
            VALUES (:owner_id, :provider, :polled_at, :gap_start, :gap_end)
            ON CONFLICT (owner_id, provider) DO UPDATE
               SET last_success_at = GREATEST(
                       source_poll_cursors.last_success_at, EXCLUDED.last_success_at
                   ),
                   backfill_failures = 0,
                   backfill_outage_failures = 0,
                   unfilled_gap_start = COALESCE(
                       EXCLUDED.unfilled_gap_start, source_poll_cursors.unfilled_gap_start
                   ),
                   unfilled_gap_end = COALESCE(
                       EXCLUDED.unfilled_gap_end, source_poll_cursors.unfilled_gap_end
                   ),
                   updated_at = NOW()
            """
        ),
        {
            "owner_id": str(owner_id),
            "provider": provider,
            "polled_at": polled_at,
            "gap_start": gap_start,
            "gap_end": gap_end,
        },
    )


async def record_backfill_failure(
    session: AsyncSession,
    *,
    provider: str,
    owner_id: UUID = DEFAULT_OWNER_ID,
    outage: bool = False,
) -> None:
    """Count one failed widened poll. Only a cursor that exists can be widened.

    ``outage`` counts a server error, timeout or rate limit on the wide range
    while the default window worked; it has a higher limit than a rejected
    range.
    """
    column = "backfill_outage_failures" if outage else "backfill_failures"
    await session.execute(
        text(
            f"""
            UPDATE source_poll_cursors
               SET {column} = {column} + 1, updated_at = NOW()
             WHERE owner_id = :owner_id AND provider = :provider
            """
        ),
        {"owner_id": str(owner_id), "provider": provider},
    )
