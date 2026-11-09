from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import server
import server.api.v2_moments as route
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from server.api.deps import get_session
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


# ── a moment cannot end before it starts ──────────────────────────────

START = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("model", [CreateMomentRequest, UpdateMomentRequest])
def test_end_before_start_is_rejected(model) -> None:
    with pytest.raises(ValidationError, match="end_at must not be before start_at"):
        model(kind="travel", title="Trip", start_at=START, end_at=START - timedelta(minutes=1))


@pytest.mark.parametrize("model", [CreateMomentRequest, UpdateMomentRequest])
@pytest.mark.parametrize("end_at", [None, START, START + timedelta(days=2)])
def test_open_instant_and_forward_ranges_are_accepted(model, end_at) -> None:
    body = model(kind="travel", title="Trip", start_at=START, end_at=end_at)
    assert body.end_at == end_at


def test_naive_and_aware_bounds_are_compared_not_crashed() -> None:
    """A naive and an aware timestamp must compare (a TypeError would be a 500)."""
    naive_two_days_earlier = (START - timedelta(days=2)).replace(tzinfo=None)
    with pytest.raises(ValidationError, match="end_at must not be before start_at"):
        CreateMomentRequest(
            kind="travel", title="Trip", start_at=START, end_at=naive_two_days_earlier
        )
    accepted = CreateMomentRequest(
        kind="travel",
        title="Trip",
        start_at=naive_two_days_earlier,
        end_at=START,
    )
    assert accepted.end_at == START


@pytest.fixture
def client(monkeypatch):
    repo = _Repo()
    monkeypatch.setattr(route, "default_repository", repo)

    async def fake_session():
        yield _Session()

    server.app.dependency_overrides[get_session] = fake_session
    try:
        with TestClient(server.app, raise_server_exceptions=False) as c:
            yield c, repo
    finally:
        server.app.dependency_overrides.clear()


def test_end_before_start_is_422_on_create_and_update_and_never_written(client) -> None:
    c, repo = client
    body = {
        "kind": "illness",
        "title": "Cold",
        "start_at": "2026-07-20T12:00:00Z",
        "end_at": "2026-07-19T12:00:00Z",
    }

    created = c.post("/api/v2/moments", json=body)
    updated = c.put("/api/v2/moments/1", json=body)

    assert created.status_code == 422
    assert updated.status_code == 422
    assert "end_at must not be before start_at" in created.text
    assert repo.create_args is None
    assert repo.update_args is None


@pytest.mark.parametrize(
    "body",
    [
        # Year 1 at +05:00 is year 0 in UTC: datetime cannot hold it.
        {"start_at": "0001-01-01T00:30:00+05:00", "end_at": "2026-07-20T12:00:00Z"},
        {"start_at": "2026-07-20T12:00:00Z", "end_at": "9999-12-31T23:30:00-05:00"},
        {"start_at": "0001-01-01T00:30:00+05:00"},
    ],
)
def test_a_bound_outside_the_utc_range_is_422_not_500(client, body) -> None:
    c, repo = client
    payload = {"kind": "travel", "title": "Trip", **body}

    created = c.post("/api/v2/moments", json=payload)
    updated = c.put("/api/v2/moments/1", json=payload)

    assert created.status_code == 422, created.text
    assert updated.status_code == 422, updated.text
    assert repo.create_args is None
    assert repo.update_args is None
