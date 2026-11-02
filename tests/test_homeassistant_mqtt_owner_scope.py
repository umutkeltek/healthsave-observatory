"""The Home Assistant bridge reads and publishes exactly ONE person.

On an Observatory that also holds participants (migration 029) every row has
an ``owner_id``. The bridge must never publish another person's rows to the
operator's Home Assistant, so every query it runs carries the owner predicate.

Three layers, none needs a database:

* SQL shape: every statement the repository emits filters every data table by
  the bound ``:owner_id`` (checked on the real statements, all of them).
* Behaviour: a two-owner fake session answers by that predicate; an unscoped
  query would hand back the second owner's rows first, so a missing filter
  shows up as a leak in the published MQTT payloads.
* Config: ``HEALTHSAVE_BRIDGE_OWNER`` parsing and its default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from contracts._base import DEFAULT_OWNER_ID
from homeassistant_mqtt.bridge import HomeAssistantMQTTConfig
from homeassistant_mqtt.config import load_config_from_env
from homeassistant_mqtt.main import publish_once
from storage.timescale import sync_receipts
from storage.timescale.homeassistant import TimescaleHealthSnapshotRepository

OWNER_A = DEFAULT_OWNER_ID
OWNER_B = UUID("11111111-2222-3333-4444-555555555555")

_DATA_TABLES = (
    "heart_rate|hrv|blood_oxygen|body_temperature|sleep_sessions|workouts|quantity_samples|"
    "medication_dose_events|daily_activity|recovery|healthsave_sync_receipts"
)
_FROM_DATA_TABLE = re.compile(rf"\bFROM\s+({_DATA_TABLES})\b")
_OWNER_PREDICATE = "owner_id = CAST(:owner_id AS UUID)"


# ─── fake two-owner database ──────────────────────────────────────────


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows

    def mappings(self) -> _Result:
        return self

    def scalar_one_or_none(self) -> Any:
        return self._rows[0][0] if self._rows and self._rows[0] else None


# (table, shape) -> [(owner, row)]. Owner B's rows come FIRST so an unscoped
# query (which takes the first row) returns B's data and the leak is visible.
_SECRET = "SECRET_B"
_ROWS: dict[tuple[str, str], list[tuple[UUID, tuple[Any, ...]]]] = {
    ("heart_rate", "scalar"): [(OWNER_B, (199,)), (OWNER_A, (61,))],
    ("heart_rate", "by_source"): [
        (OWNER_B, (f"{_SECRET} Watch", 198)),
        (OWNER_A, ("Apple Watch", 62)),
    ],
    ("hrv", "scalar"): [(OWNER_B, (91.1,)), (OWNER_A, (44.4,))],
    ("hrv", "by_source"): [
        (OWNER_B, (f"{_SECRET} Strap", 92.2)),
        (OWNER_A, ("Apple Watch", 45.5)),
    ],
    ("daily_activity", "scalar"): [(OWNER_B, (99999,)), (OWNER_A, (4321,))],
    ("daily_activity", "by_source"): [
        (OWNER_B, (f"{_SECRET} Phone", 88888)),
        (OWNER_A, ("Apple Watch", 4322)),
    ],
    ("sleep_sessions", "scalar"): [(OWNER_B, (12.0,)), (OWNER_A, (7.25,))],
    ("sleep_sessions", "by_source"): [
        (OWNER_B, (f"{_SECRET} Ring", 13 * 3_600_000)),
        (OWNER_A, ("Apple Watch", 26_100_000)),
    ],
    ("blood_oxygen", "scalar"): [(OWNER_B, (77.7,)), (OWNER_A, (97.5,))],
    ("recovery", "scalar"): [(OWNER_B, (88,)), (OWNER_A, (66,))],
    ("healthsave_sync_receipts", "scalar"): [
        (OWNER_B, (datetime(2026, 11, 3, 1, tzinfo=UTC),)),
        (OWNER_A, (datetime(2026, 11, 3, 9, tzinfo=UTC),)),
    ],
    ("medication_dose_events", "scalar"): [(OWNER_B, (_SECRET.lower(),)), (OWNER_A, ("taken",))],
}
_QUANTITY: dict[tuple[UUID, str], Any] = {
    (OWNER_B, "strain"): 21.0,
    (OWNER_A, "strain"): 9.5,
}


class _TwoOwnerSession:
    """Answers each query from the rows of the owner the SQL is scoped to."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = str(statement)
        bound = {**statement.compile().params, **(params or {})}
        self.statements.append((sql, bound))
        scoped = _OWNER_PREDICATE in sql
        owner = UUID(bound["owner_id"]) if scoped else None

        if "to_regclass" in sql:
            return _Result([(True,)])
        if "WITH receipt_coverage" in sql:
            return _Result([])  # coverage rows carry no payload of their own here
        if "WITH recent_sources" in sql:
            return _Result([(f"{_SECRET} Device" if owner != OWNER_A else "Apple Watch",)])
        if "FROM quantity_samples" in sql:
            metric = bound["metric_name"]
            options = [
                value
                for (row_owner, name), value in _QUANTITY.items()
                if name == metric and (owner is None or row_owner == owner)
            ]
            return _Result([(options[0],)] if options else [])

        table = _FROM_DATA_TABLE.search(sql).group(1)
        shape = "by_source" if ("DISTINCT ON" in sql or "SELECT source_id" in sql) else "scalar"
        rows = [row for row_owner, row in _ROWS[(table, shape)] if owner in (None, row_owner)]
        return _Result(rows if shape == "by_source" else rows[:1])


@dataclass
class _RecordingPublisher:
    config: HomeAssistantMQTTConfig = field(default_factory=HomeAssistantMQTTConfig)
    published: list[Any] = field(default_factory=list)

    def publish_many(self, messages) -> bool:
        self.published.extend(messages)
        return True


class _SessionFactory:
    def __init__(self, session: _TwoOwnerSession) -> None:
        self._session = session

    def __call__(self) -> _SessionFactory:
        return self

    async def __aenter__(self) -> _TwoOwnerSession:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


async def _publish_for(owner: UUID | None) -> tuple[list[Any], _TwoOwnerSession]:
    session = _TwoOwnerSession()
    repository = (
        TimescaleHealthSnapshotRepository()
        if owner is None
        else TimescaleHealthSnapshotRepository(owner_id=owner)
    )
    publisher = _RecordingPublisher()
    with patch("homeassistant_mqtt.main.async_session", _SessionFactory(session)):
        await publish_once(repository, publisher, readiness_entities=True)
    return publisher.published, session


def _rendered(messages: list[Any], *, drop_clock: bool = False) -> str:
    text = "\n".join(repr(message) for message in messages)
    if drop_clock:  # the payload carries wall-clock timestamps
        text = re.sub(r"\d{4}-\d\d-\d\dT[\d:.]+\+00:00", "<ts>", text)
    return text


# ─── SQL shape: every query, every table ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [OWNER_A, OWNER_B])
async def test_every_bridge_query_filters_every_data_table_by_the_bound_owner(owner) -> None:
    _, session = await _publish_for(owner)

    data_queries = [(sql, bound) for sql, bound in session.statements if "to_regclass" not in sql]
    # 12 + source_model + medication status + 4 per-source + coverage (readiness): 19 distinct reads
    assert len({sql for sql, _ in data_queries}) == 19
    for sql, bound in data_queries:
        tables = _FROM_DATA_TABLE.findall(sql)
        assert tables, sql
        assert sql.count(_OWNER_PREDICATE) >= len(tables), f"unscoped read in: {sql}"
        assert bound["owner_id"] == str(owner), sql


@pytest.mark.asyncio
async def test_default_owner_receipts_include_pre_migration_null_owner_rows() -> None:
    _, session = await _publish_for(OWNER_A)
    receipts = [sql for sql, _ in session.statements if "FROM healthsave_sync_receipts" in sql]
    assert receipts
    assert all("OR owner_id IS NULL" in sql for sql in receipts)

    _, other = await _publish_for(OWNER_B)
    other_receipts = [sql for sql, _ in other.statements if "FROM healthsave_sync_receipts" in sql]
    assert other_receipts
    assert not any("IS NULL" in sql for sql in other_receipts)


@pytest.mark.parametrize("owner", [OWNER_A, OWNER_B])
def test_scoped_coverage_query_filters_receipts_and_every_destination(owner) -> None:
    sql = sync_receipts._sync_coverage_query(owner)
    tables = _FROM_DATA_TABLE.findall(sql)
    assert len(tables) > 10  # receipts + every destination fragment
    assert sql.count(_OWNER_PREDICATE) == len(tables)


def test_unscoped_coverage_query_is_unchanged_for_the_phone_facing_routes() -> None:
    sql = sync_receipts._sync_coverage_query()
    assert ":owner_id" not in sql
    assert sql == sync_receipts._sync_coverage_query(None)


# ─── behaviour: a second owner's rows never reach a payload ───────────


@pytest.mark.asyncio
async def test_owner_b_rows_never_appear_in_owner_a_published_payloads() -> None:
    messages, _ = await _publish_for(OWNER_A)
    text = _rendered(messages)

    for leaked in ("199", "198", "91.1", "92.2", "99999", "88888", "77.7", _SECRET, "21.0"):
        assert leaked not in text, leaked
    for expected in ("61", "62", "44.4", "4321", "97.5", "apple_watch"):
        assert expected in text, expected


@pytest.mark.asyncio
async def test_default_bridge_owner_is_the_default_owner() -> None:
    default_messages, _ = await _publish_for(None)
    explicit_messages, _ = await _publish_for(OWNER_A)
    assert _rendered(default_messages, drop_clock=True) == _rendered(
        explicit_messages, drop_clock=True
    )
    assert TimescaleHealthSnapshotRepository().owner_id == DEFAULT_OWNER_ID


@pytest.mark.asyncio
async def test_bridge_pointed_at_another_owner_publishes_only_that_owner() -> None:
    messages, _ = await _publish_for(OWNER_B)
    text = _rendered(messages)
    assert "199" in text
    assert "99999" in text
    assert "4321" not in text
    assert "Apple Watch" not in text


@pytest.mark.asyncio
async def test_topics_and_entity_ids_are_unchanged_by_owner_scoping() -> None:
    """Scoping filters rows only; the topic layout the HA pack derives ids from stays put."""
    messages, _ = await _publish_for(OWNER_A)
    assert [message[0] for message in messages] == [
        "observatory/sensor/state",
        "homeassistant/sensor/observatory_apple_watch/heart_rate/config",
        "homeassistant/sensor/observatory_apple_watch/hrv_latest_ms/config",
        "homeassistant/sensor/observatory_apple_watch/steps_today/config",
        "homeassistant/sensor/observatory_apple_watch/last_sleep_hours/config",
        "observatory/source/apple_watch/state",
    ]


# ─── config ───────────────────────────────────────────────────────────


def test_bridge_owner_defaults_to_the_default_owner(monkeypatch) -> None:
    monkeypatch.delenv("HEALTHSAVE_BRIDGE_OWNER", raising=False)
    assert load_config_from_env().owner_id == DEFAULT_OWNER_ID


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_bridge_owner_means_the_default_owner(monkeypatch, blank) -> None:
    monkeypatch.setenv("HEALTHSAVE_BRIDGE_OWNER", blank)
    assert load_config_from_env().owner_id == DEFAULT_OWNER_ID


def test_bridge_owner_reads_a_uuid(monkeypatch) -> None:
    monkeypatch.setenv("HEALTHSAVE_BRIDGE_OWNER", f"  {OWNER_B}  ")
    assert load_config_from_env().owner_id == OWNER_B


def test_malformed_bridge_owner_fails_loudly_instead_of_falling_back(monkeypatch) -> None:
    monkeypatch.setenv("HEALTHSAVE_BRIDGE_OWNER", "not-a-uuid")
    with pytest.raises(ValueError, match="HEALTHSAVE_BRIDGE_OWNER"):
        load_config_from_env()


def test_compose_maps_bridge_owner_into_the_bridge_service() -> None:
    """Failure mode 15: an unmapped `.env` var is a silent no-op."""
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text()
    block = compose[compose.index("  homeassistant-mqtt:") :]
    assert "HEALTHSAVE_BRIDGE_OWNER: ${HEALTHSAVE_BRIDGE_OWNER:-}" in block
