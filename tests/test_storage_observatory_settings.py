from __future__ import annotations

from types import SimpleNamespace

from storage.timescale.observatory_settings import TimescaleObservatorySettingsRepository


class _Result:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row


class _Session:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        return _Result(next(self.rows))


def _row(**over):
    return SimpleNamespace(
        time_zone=over.get("time_zone", "Europe/Istanbul"),
        day_boundary_minutes=over.get("day_boundary_minutes", 240),
        revision=over.get("revision", 1),
        created_at=None,
        updated_at=None,
    )


async def test_get_returns_typed_settings() -> None:
    session = _Session([_row()])
    settings = await TimescaleObservatorySettingsRepository().get(session)
    assert settings.time_zone == "Europe/Istanbul"
    assert settings.day_boundary_minutes == 240
    assert "WHERE owner_id = :owner_id" in session.calls[0][0]


async def test_get_returns_none_before_first_save() -> None:
    assert await TimescaleObservatorySettingsRepository().get(_Session([None])) is None


async def test_update_is_additive_upsert_and_bumps_revision() -> None:
    session = _Session([_row(time_zone="America/New_York", day_boundary_minutes=270, revision=3)])
    settings = await TimescaleObservatorySettingsRepository().update(
        session,
        time_zone="America/New_York",
        day_boundary_minutes=270,
    )
    sql, params = session.calls[0]
    assert "ON CONFLICT (owner_id) DO UPDATE" in sql
    assert "revision = observatory_settings.revision + 1" in sql
    assert params["time_zone"] == "America/New_York"
    assert params["day_boundary_minutes"] == 270
    assert settings.revision == 3
