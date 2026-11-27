"""E2E: narrator-failover audit writes on real PostgreSQL.

A brief served by a fallback narrator records a ``narrator_failover`` audit
event. Two things must hold against a real database, where a failed statement
aborts the whole transaction (a mocked session cannot show that):

* the database accepts the event type the Python allowlist accepts;
* a failed audit write never poisons the briefing's transaction.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

DATABASE_URL = os.getenv("E2E_DATABASE_URL")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not DATABASE_URL, reason="set E2E_DATABASE_URL to run e2e"),
]


def _engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1))


@pytest.mark.asyncio
async def test_database_accepts_every_audit_event_type_the_repository_allows() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.intelligence import _AUDIT_EVENT_TYPES, default_repository

    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            owner = uuid4()
            for event_type in sorted(_AUDIT_EVENT_TYPES):
                await default_repository.record_audit(
                    session, owner_id=owner, event_type=event_type, actor="e2e"
                )
            events = await default_repository.list_audit_events(session, owner_id=owner)
            assert {event.event_type for event in events} == set(_AUDIT_EVENT_TYPES)
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_failover_audit_write_leaves_the_briefing_transaction_usable(
    monkeypatch,
) -> None:
    """The briefing keeps writing after a failed audit insert in the same session."""
    from analysis.config import AnalysisConfig
    from analysis.engine import AnalysisEngine
    from analysis.llm.client import FailoverAttempt, InsightResult
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale import intelligence as intelligence_module

    async def failing_record_audit(session, **_kwargs):
        # Any statement error aborts a PostgreSQL transaction, as the old
        # CHECK violation did.
        await session.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(
        intelligence_module.default_repository, "record_audit", failing_record_audit
    )

    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            analysis_engine = AnalysisEngine(lambda: session, None, AnalysisConfig())
            result = InsightResult(
                narrative="Fallback narrative.",
                tokens_in=1,
                tokens_out=1,
                model="ollama/llama3.2:3b",
                insight_type="daily_briefing",
                failovers=[FailoverAttempt(candidate="cloud/model", error="timeout")],
            )
            await analysis_engine._record_failover_audit(session, result)

            # The briefing's next write runs in the same transaction.
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
            await session.rollback()
    finally:
        await engine.dispose()
