"""E2E: the anomaly-watcher feed drains a backlog on real PostgreSQL (M18).

The analysis engine inserts every finding of one run in one transaction, so a
run's findings share one ``created_at`` (``DEFAULT now()``). The agents
supervisor keeps ``cursor = max(occurred_at)`` after each committed tick and
asks the feed for what came after it. This test seeds runs like that, pages
through the feed with exactly that cursor rule, and checks every watch/alert
finding comes out once, oldest first, with nothing skipped at a page boundary.

Everything runs in one transaction that is rolled back; the seeded rows sit in
a far-future window so rows already in the database never reach the feed.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]

WINDOW_START = datetime(2031, 1, 1, 6, 0, tzinfo=UTC)


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))


def _seed_rows() -> list[dict]:
    """Five runs of 50 anomalies plus one run of 130, each run on one
    timestamp. Every 5th anomaly is ``info`` (never surfaced), and each run
    also writes a ``summary`` finding the feed must ignore.
    """
    rows: list[dict] = []
    for run, size in enumerate([50, 50, 50, 50, 50, 130]):
        created_at = WINDOW_START + timedelta(hours=run)
        rows.append(
            {
                "finding_type": "summary",
                "severity": "alert",
                "tag": f"summary-{run}",
                "created_at": created_at,
            }
        )
        for index in range(size):
            rows.append(
                {
                    "finding_type": "anomaly",
                    "severity": "info" if index % 5 == 4 else ("alert" if index % 2 else "watch"),
                    "tag": f"run-{run}-{index}",
                    "created_at": created_at,
                }
            )
    return rows


@pytest.mark.asyncio
async def test_the_feed_pages_every_finding_once_oldest_first_across_shared_timestamps() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    from plugins.agents.anomaly_watcher.feed import AnalysisFindingsAnomalyFeed

    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            ids_by_tag: dict[str, int] = {}
            for row in _seed_rows():
                result = await session.execute(
                    text(
                        "INSERT INTO analysis_findings "
                        "(finding_type, metric, severity, structured_data, created_at) "
                        "VALUES (:finding_type, 'heart_rate', :severity, "
                        "CAST(:structured_data AS jsonb), :created_at) RETURNING id"
                    ),
                    {
                        "finding_type": row["finding_type"],
                        "severity": row["severity"],
                        "structured_data": json.dumps({"tag": row["tag"]}),
                        "created_at": row["created_at"],
                    },
                )
                ids_by_tag[row["tag"]] = result.scalar_one()

            expected = [
                str(ids_by_tag[row["tag"]])
                for row in sorted(
                    _seed_rows(), key=lambda r: (r["created_at"], ids_by_tag[r["tag"]])
                )
                if row["finding_type"] == "anomaly" and row["severity"] != "info"
            ]
            assert len(expected) == 304

            @asynccontextmanager
            async def same_session():
                yield session

            feed = AnalysisFindingsAnomalyFeed(session_factory=same_session, limit=100)

            # The supervisor's rule: after a committed tick,
            # cursor = max(occurred_at) of what that tick observed.
            cursor = WINDOW_START - timedelta(seconds=1)
            seen: list[str] = []
            for _tick in range(20):
                observations = await feed.fetch_since(owner_id=uuid4(), cursor=cursor)
                if not observations:
                    break
                occurred = [obs.occurred_at for obs in observations]
                assert occurred == sorted(occurred)
                seen.extend(obs.subject_id for obs in observations)
                cursor = max(cursor, *occurred)
                feed.acknowledge(observations)  # what the supervisor does after commit

            assert len(seen) == len(set(seen)), "a finding was fed twice"
            assert seen == expected, f"{len(set(expected) - set(seen))} findings never surfaced"

            # A briefing transaction that began before the last run commits
            # now: its finding is stamped behind the cursor.
            late_id = (
                await session.execute(
                    text(
                        "INSERT INTO analysis_findings "
                        "(finding_type, metric, severity, structured_data, created_at) "
                        "VALUES ('anomaly', 'hrv', 'alert', '{}'::jsonb, :created_at) "
                        "RETURNING id"
                    ),
                    {"created_at": cursor - timedelta(minutes=5)},
                )
            ).scalar_one()
            late = await feed.fetch_since(owner_id=uuid4(), cursor=cursor)
            assert [obs.subject_id for obs in late] == [str(late_id)]
            feed.acknowledge(late)
            assert await feed.fetch_since(owner_id=uuid4(), cursor=cursor) == []
            await session.rollback()
    finally:
        await engine.dispose()
