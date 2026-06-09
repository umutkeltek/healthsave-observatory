"""TimescaleIntelligenceRepository tests — ADR-0003 D2/D3.

Same coverage strategy as the other v2 repos (``test_storage_agents.py``): a
``_FakeSession`` records every ``execute(sql, params)`` so we can pin the SQL
shape + params, and returns SQL-matched rows so dataclass mapping is exercised.
On top of the shape checks, these tests pin the two trust-critical behaviours
this repo owns:

  * credentials are SEALED at the boundary — ``put_credential`` never stores
    the plaintext key, and ``get_connection_secret`` round-trips it back;
  * ``update_settings`` bumps ``revision`` in-SQL and audits before/after.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from auth import seal  # noqa: E402
from auth.encryption import ENV_KEY  # noqa: E402
from auth.keyring import _keyring_from_env  # noqa: E402
from storage.timescale.intelligence import (  # noqa: E402
    Connection,
    CredentialRef,
    FallbackRouteInput,
    Settings,
    TimescaleIntelligenceRepository,
)

OWNER = UUID("00000000-0000-0000-0000-000000000001")
NOW = SimpleNamespace()  # opaque "timestamp" stand-in for mapping assertions


class _Result:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def first(self):
        return self._row

    def fetchall(self):
        return self._rows


class _FakeSession:
    """Records execute() calls; returns rows matched by an SQL substring.

    ``on(substr, row=..., rows=...)`` registers a response; ``execute`` returns
    the first matcher whose substring appears in the (whitespace-normalised)
    SQL, or an empty result. Substring matching keeps tests robust to extra
    intermediate executes (e.g. the audit insert between two reads).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._matchers: list[tuple[str, _Result]] = []

    def on(self, substr: str, *, row=None, rows=None) -> _FakeSession:
        self._matchers.append((substr, _Result(row=row, rows=rows)))
        return self

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        for substr, result in self._matchers:
            if " ".join(substr.split()) in sql:
                return result
        return _Result()

    def find(self, substr: str) -> tuple[str, dict]:
        """The (sql, params) of the first recorded call containing ``substr``."""
        norm = " ".join(substr.split())
        for sql, params in self.calls:
            if norm in sql:
                return sql, params
        raise AssertionError(f"no execute() matched {substr!r}; calls={[c[0] for c in self.calls]}")


@pytest.fixture
def repo() -> TimescaleIntelligenceRepository:
    return TimescaleIntelligenceRepository()


@pytest.fixture
def enc_key(monkeypatch) -> str:
    """A process keyring for sealing, via the legacy single-key path."""
    from auth import generate_key

    key = generate_key()
    monkeypatch.delenv("HDH_KEYRING", raising=False)
    monkeypatch.setenv(ENV_KEY, key)
    _keyring_from_env.cache_clear()
    yield key
    _keyring_from_env.cache_clear()


# ── credentials: the encryption boundary ──────────────────────────────


async def test_put_credential_seals_key_and_never_stores_plaintext(repo, enc_key):
    session = _FakeSession().on(
        "INSERT INTO llm_credentials", row=SimpleNamespace(id=7, created_at=NOW)
    )

    ref = await repo.put_credential(session, provider="deepseek", api_key="sk-secret-tail")

    assert isinstance(ref, CredentialRef)
    assert ref.id == 7
    assert ref.key_last4 == "••••tail"  # display hint only

    _, params = session.find("INSERT INTO llm_credentials")
    # The stored blob is Fernet ciphertext (bytes), NOT the plaintext key.
    assert isinstance(params["api_key_enc"], bytes)
    assert b"sk-secret-tail" not in params["api_key_enc"]
    assert params["key_last4"] == "••••tail"
    assert params["key_version"]  # tagged with the sealing key's version
    # And a credential_set audit event was appended.
    _, audit = session.find("INSERT INTO intelligence_audit_events")
    assert audit["event_type"] == "credential_set"


async def test_get_connection_secret_round_trips_the_sealed_key(repo, enc_key):
    sealed = seal("sk-roundtrip")  # sealed with the same process keyring
    session = _FakeSession().on(
        "FROM llm_connections AS conn",
        row=SimpleNamespace(api_key_enc=sealed.ciphertext, key_version=sealed.key_version),
    )

    secret = await repo.get_connection_secret(session, connection_id=3)

    assert secret == "sk-roundtrip"


async def test_get_connection_secret_none_when_no_credential(repo, enc_key):
    session = _FakeSession()  # no row → connection absent / no credential
    assert await repo.get_connection_secret(session, connection_id=99) is None


# ── settings head row: revision bump + audit ──────────────────────────


async def test_update_settings_bumps_revision_and_audits_before_after(repo):
    session = (
        _FakeSession()
        .on("RETURNING revision, (xmax", row=SimpleNamespace(revision=5, was_update=True))
        .on(
            "FROM intelligence_settings",
            row=SimpleNamespace(
                owner_id=str(OWNER),
                mode="cloud",
                primary_connection_id=2,
                primary_model="deepseek/deepseek-chat",
                primary_temperature=None,
                primary_max_tokens=None,
                primary_timeout_ms=None,
                allow_cloud_egress=True,
                redact_cloud_prompts=True,
                revision=5,
                consent_version=None,
                consent_text_hash=None,
                consented_at=None,
                consented_by=None,
            ),
        )
    )

    settings = await repo.update_settings(session, mode="cloud", allow_cloud_egress=True)

    assert isinstance(settings, Settings)
    assert settings.revision == 5
    # Revision bumped in-SQL, not read-modify-write.
    upsert_sql, _ = session.find("INTO intelligence_settings")
    assert "revision = intelligence_settings.revision + 1" in upsert_sql
    _, audit = session.find("INSERT INTO intelligence_audit_events")
    assert audit["event_type"] == "settings_updated"
    assert audit["before_revision"] == 4  # after(5) - 1, because was_update
    assert audit["after_revision"] == 5


async def test_update_settings_first_write_has_no_before_revision(repo):
    session = (
        _FakeSession()
        .on("RETURNING revision, (xmax", row=SimpleNamespace(revision=1, was_update=False))
        .on(
            "FROM intelligence_settings",
            row=SimpleNamespace(
                owner_id=str(OWNER),
                mode="off",
                primary_connection_id=None,
                primary_model=None,
                primary_temperature=None,
                primary_max_tokens=None,
                primary_timeout_ms=None,
                allow_cloud_egress=False,
                redact_cloud_prompts=True,
                revision=1,
                consent_version=None,
                consent_text_hash=None,
                consented_at=None,
                consented_by=None,
            ),
        )
    )

    await repo.update_settings(session, mode="off")

    _, audit = session.find("INSERT INTO intelligence_audit_events")
    assert audit["before_revision"] is None  # insert, not update
    assert audit["after_revision"] == 1


async def test_update_settings_rejects_unknown_field(repo):
    with pytest.raises(ValueError, match="unknown field"):
        await repo.update_settings(_FakeSession(), bogus_column=1)


async def test_update_settings_rejects_consent_columns(repo):
    # Consent is written via record_consent, not the posture path.
    with pytest.raises(ValueError, match="unknown field"):
        await repo.update_settings(_FakeSession(), consent_version="v1")


# ── fallback chain ────────────────────────────────────────────────────


async def test_set_fallback_routes_replaces_and_orders_by_position(repo):
    session = _FakeSession()
    routes = [
        FallbackRouteInput(connection_id=10, model="openrouter/a:free"),
        FallbackRouteInput(connection_id=11, model="openrouter/b:free", max_tokens=900),
    ]

    await repo.set_fallback_routes(session, routes=routes)

    # Delete first, then one insert per route with priority = list index.
    delete_sql = session.calls[0][0]
    assert "DELETE FROM llm_fallback_routes" in delete_sql
    inserts = [(s, p) for s, p in session.calls if "INSERT INTO llm_fallback_routes" in s]
    assert [p["priority"] for _, p in inserts] == [0, 1]
    assert [p["connection_id"] for _, p in inserts] == [10, 11]
    assert inserts[1][1]["max_tokens"] == 900


async def test_get_fallback_routes_maps_rows_in_priority_order(repo):
    session = _FakeSession().on(
        "FROM llm_fallback_routes",
        rows=[
            SimpleNamespace(
                id=1,
                priority=0,
                connection_id=10,
                model="m0",
                temperature=0.2,
                max_tokens=None,
                timeout_ms=None,
            ),
            SimpleNamespace(
                id=2,
                priority=1,
                connection_id=11,
                model="m1",
                temperature=None,
                max_tokens=500,
                timeout_ms=30000,
            ),
        ],
    )

    routes = await repo.get_fallback_routes(session)

    assert [r.priority for r in routes] == [0, 1]
    assert routes[0].model == "m0"
    assert routes[1].timeout_ms == 30000
    assert "ORDER BY priority" in session.find("FROM llm_fallback_routes")[0]


# ── connections ───────────────────────────────────────────────────────


async def test_upsert_connection_insert_path_carries_destination(repo):
    session = _FakeSession().on(
        "INTO llm_connections",
        row=SimpleNamespace(
            id=4,
            provider="deepseek",
            display_name="DeepSeek",
            base_url=None,
            destination="cloud",
            credential_id=7,
            enabled=True,
            last_test_status=None,
            last_test_at=None,
        ),
    )

    conn = await repo.upsert_connection(
        session,
        provider="deepseek",
        destination="cloud",
        display_name="DeepSeek",
        credential_id=7,
    )

    assert isinstance(conn, Connection)
    assert conn.destination == "cloud"
    insert_sql, params = session.find("INTO llm_connections")
    assert "INSERT INTO llm_connections" in insert_sql
    assert params["destination"] == "cloud"


async def test_upsert_connection_rejects_invalid_destination(repo):
    with pytest.raises(ValueError, match="destination"):
        await repo.upsert_connection(_FakeSession(), provider="x", destination="lan")


# ── audit ─────────────────────────────────────────────────────────────


async def test_record_audit_rejects_unknown_event_type(repo):
    with pytest.raises(ValueError, match="event_type"):
        await repo.record_audit(_FakeSession(), event_type="not_a_real_event")


async def test_record_audit_serializes_metadata_as_json(repo):
    session = _FakeSession()
    await repo.record_audit(
        session, event_type="provider_healthcheck", metadata={"connection_id": 3, "status": "ok"}
    )
    _, params = session.find("INSERT INTO intelligence_audit_events")
    assert '"connection_id": 3' in params["metadata"]  # JSON-encoded
    assert params["event_type"] == "provider_healthcheck"
