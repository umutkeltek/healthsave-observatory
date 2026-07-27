from __future__ import annotations

from types import SimpleNamespace

import pytest
import server.api.v2_settings as route
from pydantic import ValidationError
from server.api.v2_settings import (
    UpdateAnalyticalTimeRequest,
    get_analytical_time,
    update_analytical_time,
)


class _Session:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


class _Repo:
    def __init__(self, current=None):
        self.current = current
        self.update_args = None

    async def get(self, session):
        return self.current

    async def update(self, session, **kwargs):
        self.update_args = kwargs
        self.current = SimpleNamespace(**kwargs, revision=4)
        return self.current


async def test_get_returns_safe_defaults_before_first_save(monkeypatch) -> None:
    monkeypatch.setattr(route, "default_repository", _Repo())
    view = await get_analytical_time(_Session())
    assert view.time_zone == "UTC"
    assert view.day_boundary_minutes == 240
    assert view.day_boundary == "04:00"
    assert view.sleep_day_assignment == "wake_time"
    assert view.revision == 0


async def test_update_validates_persists_and_commits(monkeypatch) -> None:
    repo = _Repo()
    monkeypatch.setattr(route, "default_repository", repo)
    session = _Session()
    view = await update_analytical_time(
        UpdateAnalyticalTimeRequest(time_zone="Europe/Istanbul", day_boundary_minutes=270),
        session,
    )
    assert repo.update_args == {"time_zone": "Europe/Istanbul", "day_boundary_minutes": 270}
    assert session.committed is True
    assert view.day_boundary == "04:30"
    assert view.revision == 4


def test_update_rejects_unknown_timezone_and_late_boundary() -> None:
    with pytest.raises(ValidationError, match="known IANA"):
        UpdateAnalyticalTimeRequest(time_zone="Mars/Olympus", day_boundary_minutes=240)
    with pytest.raises(ValidationError):
        UpdateAnalyticalTimeRequest(time_zone="UTC", day_boundary_minutes=721)
