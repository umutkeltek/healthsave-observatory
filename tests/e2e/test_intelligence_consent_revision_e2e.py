"""E2E: granting or revoking cloud-egress consent bumps the settings revision.

Consent flips ``allow_cloud_egress``, the switch the narrator resolver reads,
so it is a settings change like any other: the head row's ``revision`` moves
and the audit row carries ``before_revision``/``after_revision``, the same
chain ``update_settings`` writes. Checked on real PostgreSQL so the in-SQL
bump and its RETURNING are exercised, not just their text.
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
async def test_consent_grant_and_revoke_each_bump_revision_and_audit_it() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession
    from storage.timescale.intelligence import default_repository

    engine = _engine()
    owner = uuid4()
    try:
        async with AsyncSession(engine) as session:
            settings = await default_repository.update_settings(
                session, owner_id=owner, actor="e2e", mode="cloud"
            )
            assert settings.revision == 1

            await default_repository.record_consent(
                session, owner_id=owner, granted=True, consent_version="v1", actor="e2e"
            )
            granted = await default_repository.get_settings(session, owner_id=owner)
            assert granted.allow_cloud_egress is True
            assert granted.revision == 2

            await default_repository.record_consent(
                session, owner_id=owner, granted=False, actor="e2e", reason="e2e"
            )
            revoked = await default_repository.get_settings(session, owner_id=owner)
            assert revoked.allow_cloud_egress is False
            assert revoked.revision == 3

            events = await default_repository.list_audit_events(session, owner_id=owner)
            chain = sorted(
                (event.after_revision, event.before_revision, event.event_type) for event in events
            )
            assert chain == [
                (1, None, "settings_updated"),
                (2, 1, "consent_granted"),
                (3, 2, "consent_revoked"),
            ]
            await session.rollback()
    finally:
        await engine.dispose()
