from __future__ import annotations

from datetime import UTC, datetime

import pytest
import server.api.v2_moments as route
from fastapi import HTTPException
from server.api.v2_moments import (
    CreateMomentRequest,
    UpdateMomentRequest,
    delete_moment,
    list_moments,
    update_moment,
)


class _Repo:
    def __init__(self, moments=None):
        self.moments = list(moments or [])
        self.create_args = None
        self.update_args = None
        self.delete_calls: list[int] = []
        self.list_limit = None

    async def list(self, session, *, limit=50, before=None):
        self.list_limit = limit
        return self.moments

    async def create(self, session, **kwargs):
        self.create_args = kwargs
        moment = type("Moment", (), kwargs | {"created_at": None, "updated_at": None})()
        moment.id = 1
        return moment

    async def update(self, session, **kwargs):
        self.update_args = kwargs
        if kwargs["id"] == 99:
            return None
        moment = type("Moment", (), kwargs | {"created_at": None, "updated_at": None})()
        moment.id = kwargs["id"]
        return moment

    async def delete(self, session, **kwargs):
        self.delete_calls.append(kwargs["id"])
        return kwargs["id"] != 99


class _Session:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_list_delegates_to_repository(monkeypatch) -> None:
    repo = _Repo()
    monkeypatch.setattr(route, "default_repository", repo)
    result = await list_moments(_Session(), limit=10)
    assert result.count == 0
    assert repo.list_limit == 10


@pytest.mark.asyncio
async def test_create_validates_kind_and_commits(monkeypatch) -> None:
    repo = _Repo()
    monkeypatch.setattr(route, "default_repository", repo)
    session = _Session()
    view = await route.create_moment(
        CreateMomentRequest(
            kind="illness",
            title="Mild cold",
            start_at=datetime(2026, 7, 20, tzinfo=UTC),
            grade="moderate",
            note="Started Monday",
        ),
        session,
    )
    assert view.id == 1
    assert view.kind == "illness"
    assert repo.create_args["grade"] == "moderate"
    assert repo.create_args["title"] == "Mild cold"
    assert session.committed is True


@pytest.mark.asyncio
async def test_update_returns_404_for_unknown_moment(monkeypatch) -> None:
    monkeypatch.setattr(route, "default_repository", _Repo())
    with pytest.raises(HTTPException, match="moment not found"):
        await update_moment(
            99,
            UpdateMomentRequest(
                kind="travel",
                title="Trip",
                start_at=datetime(2026, 7, 20, tzinfo=UTC),
            ),
            _Session(),
        )


@pytest.mark.asyncio
async def test_delete_returns_404_for_unknown_moment(monkeypatch) -> None:
    monkeypatch.setattr(route, "default_repository", _Repo())
    with pytest.raises(HTTPException, match="moment not found"):
        await delete_moment(99, _Session())
