"""``GET /api/v2/year/{year}`` (no database; the three repositories are faked).

Contract: the response shape the web view reads, the owner rule (admin names
any owner, a participant read key only its own), the time basis it reports,
422 for a year that has not started, and that headline numbers stay one per
source.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from server.api import deps, v2_year
from server.api.access import route_class
from server.db.session import get_session
from server.ingestion.owner import DEFAULT_OWNER_ID
from server.main import app
from storage.timescale.api_keys import hash_api_key
from storage.timescale.observations import SeriesPoint
from storage.timescale.observatory_settings import ObservatorySettings
from storage.timescale.year import PresenceRow, StreamBoundsRow

ALICE = UUID("7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00")
BOB = UUID("2f4a9c1e-6d3b-4e8f-8a2c-5b7d9e0f1a2b")
WATCH = UUID("7c1f0c52-4c1b-5d0e-9a43-2a7f7d1b9e01")
RING = UUID("0b9d7e1e-34a4-5f39-8d3c-6f1f6a2f0a02")
PHONE = UUID("9e2d4f1a-77c0-5ad1-8f60-6c4f0b8b5d04")
LEGACY = "legacy-admin-key"


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


class _YearRepo:
    def __init__(self) -> None:
        self.presence_calls: list[dict] = []
        self.bounds_calls: list[UUID] = []

    async def day_presence(self, session, **kwargs):
        self.presence_calls.append(kwargs)
        rows = []
        for day in _days(date(2025, 1, 1), date(2025, 12, 31)):
            if date(2025, 8, 3) <= day <= date(2025, 8, 11):
                continue  # nine days in August with nothing
            rows.append(
                PresenceRow("vital.resting_heart_rate", WATCH, "interval_component", day, 2)
            )
            if day >= date(2025, 4, 10):
                rows.append(PresenceRow("sleep.stage", RING, "interval_component", day, 9))
            rows.append(PresenceRow("activity.steps", PHONE, "owner_all_source_day_total", day, 1))
        return rows

    async def stream_bounds(self, session, *, owner_id, **_kwargs):
        self.bounds_calls.append(owner_id)
        return [
            StreamBoundsRow(
                WATCH,
                "apple_health",
                "apple watch",
                "Apple Watch",
                datetime(2023, 5, 2, 6, tzinfo=UTC),
                datetime(2026, 11, 6, 6, tzinfo=UTC),
            ),
            StreamBoundsRow(
                RING,
                "apple_health",
                "oura ring",
                "Oura Ring",
                datetime(2025, 4, 10, 6, tzinfo=UTC),
                datetime(2026, 11, 6, 6, tzinfo=UTC),
            ),
            StreamBoundsRow(
                PHONE,
                "apple_health",
                "healthkit statistics",
                "HealthKit Statistics",
                datetime(2023, 5, 2, tzinfo=UTC),
                datetime(2026, 11, 6, tzinfo=UTC),
            ),
        ]


def _point(t: datetime, value: float, stream: UUID, scope: str) -> SeriesPoint:
    return SeriesPoint(
        t=t,
        interval_end=t,
        value=value,
        code=None,
        unit=None,
        source_id="apple_health",
        stream_id=str(stream),
        confidence=None,
        aggregation_scope=scope,
    )


class _Observations:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def query_series(self, session, *, metric_id, start, end, **kwargs):
        self.calls.append({"metric_id": metric_id, "start": start, "end": end, **kwargs})
        points = []
        for i, day in enumerate(_days(date(2025, 1, 1), date(2025, 12, 31))):
            at = datetime(day.year, day.month, day.day, 6, tzinfo=UTC)
            if metric_id == "vital.resting_heart_rate":
                points.append(_point(at, 56.0 + (i % 3 - 1), WATCH, "interval_component"))
                points.append(_point(at, 50.0 + (i % 3 - 1), RING, "interval_component"))
            elif metric_id == "activity.steps":
                points.append(_point(at, 8000.0 + i, PHONE, "owner_all_source_day_total"))
        return points


class _Settings:
    def __init__(self, by_owner: dict[UUID, ObservatorySettings] | None = None) -> None:
        self.by_owner = by_owner or {}
        self.asked: list[UUID] = []

    async def get(self, session, *, owner_id):
        self.asked.append(owner_id)
        return self.by_owner.get(owner_id)


@pytest.fixture
def fakes(monkeypatch):
    repo, observations, settings = _YearRepo(), _Observations(), _Settings()
    monkeypatch.setattr(v2_year, "year_repository", repo)
    monkeypatch.setattr(v2_year, "observation_repository", observations)
    monkeypatch.setattr(v2_year, "settings_repository", settings)
    stamp = SimpleNamespace(value="2025-12-31T23:00:00+00:00", asked=[])

    async def _stamp(session, owner_id):
        stamp.asked.append(owner_id)
        return stamp.value

    monkeypatch.setattr(v2_year, "_ingest_stamp", _stamp)
    monkeypatch.setattr(v2_year, "_YEAR_CACHE", {})
    return SimpleNamespace(repo=repo, observations=observations, settings=settings, stamp=stamp)


# ── auth session: answers the api_keys lookup for participant keys ───────


class _Result:
    def __init__(self, row=None):
        self.row = row

    def first(self):
        return self.row


class _KeySession:
    KEYS = {"alice-read": ("read", ALICE), "alice-ingest": ("ingest", ALICE)}

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        if "FROM api_keys WHERE key_hash" in sql:
            for key, (scope, owner) in self.KEYS.items():
                if (params or {}).get("key_hash") == hash_api_key(key):
                    return _Result(
                        SimpleNamespace(
                            _mapping={
                                "id": UUID(int=1),
                                "label": "Alice",
                                "scope": scope,
                                "owner_id": owner,
                                "created_at": None,
                                "revoked_at": None,
                            }
                        )
                    )
        return _Result()

    async def rollback(self):
        pass

    async def commit(self):
        pass


@pytest.fixture
def keyed(monkeypatch, fakes):
    monkeypatch.setattr(deps, "API_KEY", LEGACY)
    monkeypatch.setattr(deps, "ALLOW_NO_AUTH", False)
    fake = _KeySession()
    app.dependency_overrides[get_session] = lambda: fake
    try:
        yield fakes
    finally:
        app.dependency_overrides.pop(get_session, None)


def _client(key: str) -> TestClient:
    return TestClient(app, headers={"x-api-key": key})


# ── shape ────────────────────────────────────────────────────────────────


def test_year_answers_months_sources_changes_and_every_gap(keyed) -> None:
    response = _client(LEGACY).get("/api/v2/year/2025")
    assert response.status_code == 200
    body = response.json()

    assert body["year"] == 2025
    assert body["owner_id"] == str(DEFAULT_OWNER_ID)
    assert (body["window_start"], body["window_end"]) == ("2025-01-01", "2025-12-31")
    assert body["days_in_window"] == 365 == len(body["mask"]) == len(body["day_family_counts"])
    assert (body["time_zone"], body["day_boundary"]) == ("UTC", "04:00")
    assert [m["month"] for m in body["months"]] == list(range(1, 13))

    # The nine August days are in the overall gap list and in each family's.
    assert {"start": "2025-08-03", "end": "2025-08-11", "days": 9, "kind": "inside"} in body["gaps"]
    families = {f["id"]: f for f in body["families"]}
    assert set(families) == {"heart", "sleep", "activity"}
    for family in families.values():
        assert sum(g["days"] for g in family["gaps"]) == family["days_without_data"]
        assert family["mask"].count("0") == family["days_without_data"]
    assert families["sleep"]["gaps"][0] == {
        "start": "2025-01-01",
        "end": "2025-04-09",
        "days": 99,
        "kind": "before_first",
    }

    # The all-source step total is data, not a device.
    sources = {s["label"]: s for s in body["sources"]}
    assert set(sources) == {"Apple Watch", "Oura Ring"}
    assert sources["Oura Ring"]["new_this_year"] is True
    assert sources["Apple Watch"]["new_this_year"] is False
    assert body["device_changes"] == [
        {"day": "2025-04-10", "kind": "first_seen", "stream_id": str(RING), "label": "Oura Ring"}
    ]
    assert body["months"][3]["first_seen_ids"] == [str(RING)]
    assert {item["code"] for item in body["limitations"]} >= {"time_basis", "day_presence_only"}


def test_headlines_are_one_per_source(keyed) -> None:
    body = _client(LEGACY).get("/api/v2/year/2025").json()
    rhr = [h for h in body["headlines"] if h["id"] == "resting_heart_rate"]
    assert sorted((h["source_label"], h["value"]) for h in rhr) == [
        ("Apple Watch", 56.0),
        ("Oura Ring", 50.0),
    ]
    assert all(h["basis"] == "median_one_source" for h in rhr)
    steps = [h for h in body["headlines"] if h["id"] == "steps"]
    # The phone's all-source total is its own series, never labelled one source.
    assert [(h["stream_id"], h["source_label"], h["basis"]) for h in steps] == [
        (None, "All sources, daily total", "median_all_sources_total")
    ]
    # Headline reads ask for the single scope each metric rolls up over.
    assert all(call["rollup_scope_only"] for call in keyed.observations.calls)


def test_days_follow_the_persons_analytical_time(keyed) -> None:
    keyed.settings.by_owner[DEFAULT_OWNER_ID] = ObservatorySettings("Europe/Istanbul", 240, 3)
    body = _client(LEGACY).get("/api/v2/year/2025").json()
    assert (body["time_zone"], body["day_boundary"]) == ("Europe/Istanbul", "04:00")
    call = keyed.repo.presence_calls[0]
    assert call["time_zone"] == "Europe/Istanbul"
    assert call["day_boundary_minutes"] == 240
    # Jan 1 04:00 in Istanbul (UTC+3) is Jan 1 01:00 UTC.
    assert call["start"] == datetime(2025, 1, 1, 1, tzinfo=UTC)
    assert call["end"] == datetime(2026, 1, 1, 1, tzinfo=UTC)


def test_a_participant_without_its_own_setting_uses_the_primary_persons(keyed) -> None:
    keyed.settings.by_owner[DEFAULT_OWNER_ID] = ObservatorySettings("Europe/Berlin", 180, 1)
    body = _client(LEGACY).get(f"/api/v2/year/2025?owner={ALICE}").json()
    assert body["time_zone"] == "Europe/Berlin"
    assert keyed.settings.asked == [ALICE, DEFAULT_OWNER_ID]


# ── errors ───────────────────────────────────────────────────────────────


def test_a_year_that_has_not_started_is_422(keyed) -> None:
    next_year = datetime.now(UTC).year + 1
    response = _client(LEGACY).get(f"/api/v2/year/{next_year}")
    assert response.status_code == 422
    assert "has not started" in response.json()["detail"]
    assert keyed.repo.presence_calls == []


@pytest.mark.parametrize("year", ["1969", "2201", "twenty"])
def test_out_of_range_year_is_422(keyed, year) -> None:
    assert _client(LEGACY).get(f"/api/v2/year/{year}").status_code == 422
    assert keyed.repo.presence_calls == []


def test_year_requires_the_api_key(keyed) -> None:
    assert TestClient(app).get("/api/v2/year/2025").status_code == 401


# ── owner rule ───────────────────────────────────────────────────────────


def test_year_is_an_owner_scoped_read() -> None:
    assert route_class("GET", "/api/v2/year/{year}") == "owner_read"


def test_admin_names_any_owner(keyed) -> None:
    assert _client(LEGACY).get(f"/api/v2/year/2025?owner={ALICE}").status_code == 200
    assert keyed.repo.bounds_calls == [ALICE]
    assert keyed.repo.presence_calls[0]["owner_id"] == ALICE


def test_read_key_reads_only_its_own_year(keyed) -> None:
    client = _client("alice-read")
    own = client.get("/api/v2/year/2025")
    assert own.status_code == 200
    assert own.json()["owner_id"] == str(ALICE)
    forbidden = client.get(f"/api/v2/year/2025?owner={BOB}")
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"].startswith("owner_not_allowed")
    assert keyed.repo.bounds_calls == [ALICE]


def test_ingest_key_cannot_read_a_year(keyed) -> None:
    assert _client("alice-ingest").get("/api/v2/year/2025").status_code == 403
    assert keyed.repo.presence_calls == []


# ── current year ─────────────────────────────────────────────────────────


async def test_the_current_year_stops_at_today(fakes) -> None:
    view = await v2_year.build_year(
        object(), owner_id=DEFAULT_OWNER_ID, year=2025, now=datetime(2025, 9, 1, 12, tzinfo=UTC)
    )
    assert view.window_end == date(2025, 9, 1)
    assert view.days_in_window == 244
    assert view.months[11].confidence == "future"
    assert "partial_year" in {item.code for item in view.limitations}


# ── cache follows new data and new settings ──────────────────────────────


def test_a_new_sync_is_visible_on_the_next_read(keyed, monkeypatch) -> None:
    monkeypatch.setattr(v2_year, "YEAR_CACHE_TTL_SECONDS", 600.0)
    client = _client(LEGACY)
    assert client.get("/api/v2/year/2025").status_code == 200
    assert client.get("/api/v2/year/2025").status_code == 200
    assert len(keyed.repo.presence_calls) == 1  # second read served from cache

    keyed.stamp.value = "2026-01-02T08:00:00+00:00"  # the phone synced
    assert client.get("/api/v2/year/2025").status_code == 200
    assert len(keyed.repo.presence_calls) == 2
    # One entry per owner and year: replaced, never piled up per sync.
    assert list(v2_year._YEAR_CACHE) == [(DEFAULT_OWNER_ID, 2025)]
    assert keyed.stamp.asked[-1] == DEFAULT_OWNER_ID


def test_a_new_time_setting_is_visible_on_the_next_read(keyed, monkeypatch) -> None:
    monkeypatch.setattr(v2_year, "YEAR_CACHE_TTL_SECONDS", 600.0)
    client = _client(LEGACY)
    assert client.get("/api/v2/year/2025").json()["time_zone"] == "UTC"
    keyed.settings.by_owner[DEFAULT_OWNER_ID] = ObservatorySettings("Asia/Tokyo", 240, 2)
    assert client.get("/api/v2/year/2025").json()["time_zone"] == "Asia/Tokyo"
    assert len(keyed.repo.presence_calls) == 2


def test_each_owner_has_its_own_cached_year(keyed, monkeypatch) -> None:
    monkeypatch.setattr(v2_year, "YEAR_CACHE_TTL_SECONDS", 600.0)
    client = _client(LEGACY)
    client.get("/api/v2/year/2025")
    client.get(f"/api/v2/year/2025?owner={ALICE}")
    client.get("/api/v2/year/2025")
    assert [call["owner_id"] for call in keyed.repo.presence_calls] == [DEFAULT_OWNER_ID, ALICE]


# ── daily totals: whole calendar days, today's unfinished total left out ──


async def test_daily_total_headlines_read_whole_local_days(fakes) -> None:
    fakes.settings.by_owner[DEFAULT_OWNER_ID] = ObservatorySettings("Europe/Istanbul", 240, 1)
    await v2_year.build_year(
        object(), owner_id=DEFAULT_OWNER_ID, year=2025, now=datetime(2026, 3, 1, 9, tzinfo=UTC)
    )
    calls = {call["metric_id"]: call for call in fakes.observations.calls}
    # Istanbul is UTC+3: Jan 1 00:00 local is Dec 31 21:00 UTC; matched at + 12 h.
    assert calls["activity.steps"]["start"] == datetime(2024, 12, 31, 9, tzinfo=UTC)
    assert calls["activity.steps"]["end"] == datetime(2025, 12, 31, 9, tzinfo=UTC)
    # Readings that are not daily totals keep the analytical-day window (04:00).
    assert calls["vital.resting_heart_rate"]["start"] == datetime(2025, 1, 1, 1, tzinfo=UTC)

    fakes.observations.calls.clear()
    await v2_year.build_year(
        object(), owner_id=DEFAULT_OWNER_ID, year=2025, now=datetime(2025, 6, 10, 9, tzinfo=UTC)
    )
    steps = next(c for c in fakes.observations.calls if c["metric_id"] == "activity.steps")
    # June 10 is still running in Istanbul: its total stops at June 10 00:00 local.
    assert steps["end"] == datetime(2025, 6, 9, 9, tzinfo=UTC)
