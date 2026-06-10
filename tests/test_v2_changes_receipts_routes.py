"""v2 change-signal + receipts routes: /api/v2/changes, /api/v2/receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Response
from server.api import v2_changes, v2_receipts

_T = datetime(2026, 6, 10, 8, 0, tzinfo=UTC)


class _FakeReadiness:
    async def fetch_canonical_sources(self, session, **kwargs):
        return [{"source_plugin_id": "apple_healthsave", "last_ingested_at": _T}]


class _FakeSync:
    async def latest_sync_run(self, session):
        return {"sync_run_id": "run-1", "last_seen_at": _T.isoformat()}


class _FakeBriefings:
    async def latest_narratives_by_type(self, session, **kwargs):
        return {"daily_briefing": SimpleNamespace(created_at=_T)}


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


@pytest.fixture(autouse=True)
def _patch_repos(monkeypatch):
    monkeypatch.setattr(v2_changes, "_READINESS", _FakeReadiness())
    monkeypatch.setattr(v2_changes, "_SYNC", _FakeSync())
    monkeypatch.setattr(v2_changes, "_BRIEFINGS", _FakeBriefings())
    monkeypatch.setattr(v2_receipts, "_READINESS", _FakeReadiness())
    monkeypatch.setattr(v2_receipts, "_SYNC", _FakeSync())


@pytest.mark.asyncio
async def test_changes_returns_fingerprint_with_etag() -> None:
    response = Response()
    body = await v2_changes.changes(_FakeRequest(), response, session=None)
    assert isinstance(body, dict)
    assert body["last_ingested_at"] == _T.isoformat()
    assert body["last_narrative_at"] == _T.isoformat()
    assert body["latest_sync_run"]["sync_run_id"] == "run-1"
    assert body["version_token"] == response.headers["ETag"]


@pytest.mark.asyncio
async def test_changes_304_on_matching_etag() -> None:
    first = Response()
    body = await v2_changes.changes(_FakeRequest(), first, session=None)
    token = body["version_token"]
    second = await v2_changes.changes(
        _FakeRequest({"if-none-match": token}), Response(), session=None
    )
    assert isinstance(second, Response)
    assert second.status_code == 304


@pytest.mark.asyncio
async def test_changes_token_stable_for_same_state() -> None:
    a = await v2_changes.changes(_FakeRequest(), Response(), session=None)
    b = await v2_changes.changes(_FakeRequest(), Response(), session=None)
    assert a["version_token"] == b["version_token"]


class _FakeAuditRepo:
    def __init__(self, events: list[Any] | None = None, error: bool = False):
        self._events = events or []
        self._error = error

    async def list_audit_events(self, session, *, owner_id=None, limit=100):
        if self._error:
            raise RuntimeError("relation does not exist")
        return self._events[:limit]


@pytest.mark.asyncio
async def test_receipts_composes_events_and_ingest(monkeypatch) -> None:
    event = SimpleNamespace(
        id=1,
        actor="user",
        event_type="consent_granted",
        before_revision=1,
        after_revision=2,
        metadata={"version": "2026-06"},
        created_at=_T,
    )
    monkeypatch.setattr(
        v2_receipts, "_INTELLIGENCE", SimpleNamespace(default_repository=_FakeAuditRepo([event]))
    )
    body = await v2_receipts.list_receipts(limit=50, session=None)
    assert body["events_unavailable"] is False
    assert body["count"] == 1
    assert body["events"][0]["event_type"] == "consent_granted"
    assert body["events"][0]["created_at"] == _T.isoformat()
    assert body["ingest"]["latest_sync_run"]["sync_run_id"] == "run-1"


@pytest.mark.asyncio
async def test_receipts_degrades_when_audit_table_missing(monkeypatch) -> None:
    """Pre-017 DB: events report unavailable (not silently empty); ingest still shows."""
    monkeypatch.setattr(
        v2_receipts,
        "_INTELLIGENCE",
        SimpleNamespace(default_repository=_FakeAuditRepo(error=True)),
    )
    body = await v2_receipts.list_receipts(limit=50, session=None)
    assert body["events_unavailable"] is True
    assert body["events"] == []
    assert body["ingest"]["sources"][0]["source_plugin_id"] == "apple_healthsave"


class _FakeBriefingRepo:
    def __init__(self, rows):
        self._rows = rows

    async def list_narratives(self, session, *, insight_type=None, limit=20):
        rows = [r for r in self._rows if insight_type is None or r.insight_type == insight_type]
        return rows[:limit]


@pytest.mark.asyncio
async def test_narratives_history_newest_first(monkeypatch) -> None:
    from server.api import v2_insights

    rows = [
        SimpleNamespace(insight_type="weekly_summary", narrative="week story", created_at=_T),
        SimpleNamespace(insight_type="daily_briefing", narrative="day story", created_at=_T),
    ]
    monkeypatch.setattr(v2_insights, "_BRIEFING_REPO", _FakeBriefingRepo(rows))
    body = await v2_insights.list_narratives(insight_type=None, limit=20, session=None)
    assert body["count"] == 2
    assert body["narratives"][0]["narrative"] == "week story"
    assert body["narratives"][0]["created_at"] == _T.isoformat()

    only_weekly = await v2_insights.list_narratives(
        insight_type="weekly_summary", limit=20, session=None
    )
    assert only_weekly["count"] == 1


@pytest.mark.asyncio
async def test_narratives_unknown_type_422(monkeypatch) -> None:
    from fastapi import HTTPException
    from server.api import v2_insights

    monkeypatch.setattr(v2_insights, "_BRIEFING_REPO", _FakeBriefingRepo([]))
    with pytest.raises(HTTPException) as exc:
        await v2_insights.list_narratives(insight_type="bogus", limit=20, session=None)
    assert exc.value.status_code == 422
