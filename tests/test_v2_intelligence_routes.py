"""/api/v2/intelligence route tests — ADR-0003 D1/D4/D5/D7.

Direct-call handler tests (the suite's route-test convention) over a stateful
in-memory fake repo, so the orchestration is exercised end-to-end without a DB:
PUT classifies each route's trust zone with the REAL classifier, seals the key
and never echoes it; consent is a separate step that flips the cloud opt-in;
test-connection is SSRF-guarded. ``_make_client`` is stubbed so no call leaves.
"""

from __future__ import annotations

import dataclasses
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from analysis.llm.client import HealthcheckResult  # noqa: E402
from analysis.netguard import SsrfError  # noqa: E402
from auth import last4  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from server.api import v2_intelligence as mod  # noqa: E402
from storage.timescale.intelligence import (  # noqa: E402
    Connection,
    CredentialRef,
    FallbackRoute,
    Settings,
)

NOW = datetime(2026, 6, 10, tzinfo=UTC)
OWNER = mod.repo_module.DEFAULT_OWNER_ID


class _FakeSession:
    async def commit(self):
        return None


class _FakeRepo:
    """In-memory stand-in for storage.timescale.intelligence (module + repo)."""

    def __init__(self):
        self.default_repository = self
        self.connections: list[Connection] = []
        self.credentials: dict[int, CredentialRef] = {}
        self.secrets: dict[int, str] = {}
        self.settings: Settings | None = None
        self.routes: list[FallbackRoute] = []
        self._cid = 0
        self._credid = 0
        self.audit: list[str] = []

    # credentials
    async def put_credential(self, session, *, provider, api_key, owner_id=OWNER):
        self._credid += 1
        ref = CredentialRef(
            id=self._credid,
            provider=provider,
            key_version="v0",
            key_last4=last4(api_key),
            created_at=NOW,
        )
        self.credentials[self._credid] = ref
        self.secrets[self._credid] = api_key
        self.audit.append("credential_set")
        return ref

    async def rotate_credential(self, session, *, credential_id, api_key, owner_id=OWNER):
        old = self.credentials[credential_id]
        self.credentials[credential_id] = dataclasses.replace(old, key_last4=last4(api_key))
        self.secrets[credential_id] = api_key
        self.audit.append("credential_rotated")

    async def get_credential(self, session, *, credential_id, owner_id=OWNER):
        return self.credentials.get(credential_id)

    async def get_connection_secret(self, session, *, connection_id, owner_id=OWNER):
        conn = next((c for c in self.connections if c.id == connection_id), None)
        if conn is None or conn.credential_id is None:
            return None
        return self.secrets.get(conn.credential_id)

    # connections
    async def upsert_connection(
        self,
        session,
        *,
        provider,
        destination,
        connection_id=None,
        display_name=None,
        base_url=None,
        credential_id=None,
        enabled=True,
        owner_id=OWNER,
    ):
        if connection_id is None:
            self._cid += 1
            conn = Connection(
                id=self._cid,
                provider=provider,
                display_name=display_name,
                base_url=base_url,
                destination=destination,
                credential_id=credential_id,
                enabled=enabled,
                last_test_status=None,
                last_test_at=None,
            )
            self.connections.append(conn)
            return conn
        idx = next(i for i, c in enumerate(self.connections) if c.id == connection_id)
        conn = dataclasses.replace(
            self.connections[idx],
            provider=provider,
            display_name=display_name,
            base_url=base_url,
            destination=destination,
            credential_id=credential_id,
            enabled=enabled,
        )
        self.connections[idx] = conn
        return conn

    async def get_connection(self, session, *, connection_id, owner_id=OWNER):
        return next((c for c in self.connections if c.id == connection_id), None)

    async def list_connections(self, session, *, owner_id=OWNER):
        return list(self.connections)

    async def record_test_result(self, session, *, connection_id, status, owner_id=OWNER):
        idx = next(i for i, c in enumerate(self.connections) if c.id == connection_id)
        self.connections[idx] = dataclasses.replace(
            self.connections[idx], last_test_status=status, last_test_at=NOW
        )
        self.audit.append("provider_healthcheck")

    # settings
    async def get_settings(self, session, *, owner_id=OWNER):
        return self.settings

    async def update_settings(self, session, *, owner_id=OWNER, actor=None, **fields):
        cur = self.settings or Settings(
            owner_id=OWNER,
            mode="off",
            primary_connection_id=None,
            primary_model=None,
            primary_temperature=None,
            primary_max_tokens=None,
            primary_timeout_ms=None,
            allow_cloud_egress=False,
            redact_cloud_prompts=True,
            revision=0,
            consent_version=None,
            consent_text_hash=None,
            consented_at=None,
            consented_by=None,
        )
        merged = dataclasses.replace(
            cur,
            revision=cur.revision + 1,
            **{k: v for k, v in fields.items() if v is not None},
        )
        self.settings = merged
        self.audit.append("settings_updated")
        return merged

    async def record_consent(
        self,
        session,
        *,
        owner_id=OWNER,
        granted,
        consent_version=None,
        consent_text_hash=None,
        consented_by=None,
        actor=None,
    ):
        assert self.settings is not None
        self.settings = dataclasses.replace(
            self.settings,
            allow_cloud_egress=granted,
            consent_version=consent_version if granted else None,
            consent_text_hash=consent_text_hash if granted else None,
            consented_at=NOW if granted else None,
            consented_by=consented_by if granted else None,
        )
        self.audit.append("consent_granted" if granted else "consent_revoked")

    # fallback
    async def get_fallback_routes(self, session, *, owner_id=OWNER):
        return list(self.routes)

    async def set_fallback_routes(self, session, *, routes, owner_id=OWNER):
        self.routes = [
            FallbackRoute(
                id=i + 1,
                priority=i,
                connection_id=r.connection_id,
                model=r.model,
                temperature=r.temperature,
                max_tokens=r.max_tokens,
                timeout_ms=r.timeout_ms,
            )
            for i, r in enumerate(routes)
        ]


@pytest.fixture
def repo(monkeypatch):
    fake = _FakeRepo()
    monkeypatch.setattr(mod, "_repo", fake)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    return fake


def _request(trusted=()):
    llm = SimpleNamespace(trusted_local_hosts=list(trusted))
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(analysis_config=SimpleNamespace(llm=llm)))
    )


def _no_secret_anywhere(view: dict, secret: str):
    import json

    assert secret not in json.dumps(view, default=str)


# ── GET ────────────────────────────────────────────────────────────────


async def test_get_empty_is_off_and_not_managed_by_env(repo):
    view = await mod.get_intelligence(session=_FakeSession())
    assert view["mode"] == "off"
    assert view["managed_by_env"] is False
    assert view["primary"] is None
    assert view["consent"]["granted"] is False
    assert view["allow_cloud_egress"] is False


async def test_get_managed_by_env_when_env_set_and_db_unconfigured(repo, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    view = await mod.get_intelligence(session=_FakeSession())
    assert view["managed_by_env"] is True
    assert view["env_provider"] == "deepseek"


# ── PUT ────────────────────────────────────────────────────────────────


async def test_put_cloud_primary_classifies_seals_and_hides_key(repo):
    body = mod.ApplyIntelligenceRequest(
        mode="cloud",
        primary=mod.PrimaryInput(
            provider="deepseek", model="deepseek/deepseek-chat", api_key="sk-SECRET"
        ),
    )
    view = await mod.put_intelligence(request=_request(), body=body, session=_FakeSession())

    # Server classified deepseek as cloud (client never said so).
    assert view["primary"]["provider"] == "deepseek"
    assert view["primary"]["destination"] == "cloud"
    assert view["primary"]["model"] == "deepseek/deepseek-chat"
    # The key was sealed → only last4 surfaces, raw key never echoed.
    assert view["primary"]["key_last4"] == last4("sk-SECRET")
    _no_secret_anywhere(view, "sk-SECRET")
    # mode=cloud configured but egress NOT yet allowed (consent is separate).
    assert view["mode"] == "cloud"
    assert view["allow_cloud_egress"] is False
    assert view["consent"]["granted"] is False
    assert "credential_set" in repo.audit


async def test_put_local_ollama_is_classified_local(repo):
    body = mod.ApplyIntelligenceRequest(
        mode="local",
        primary=mod.PrimaryInput(
            provider="ollama", model="llama3.1:8b", base_url="http://ollama:11434"
        ),
    )
    view = await mod.put_intelligence(request=_request(), body=body, session=_FakeSession())
    assert view["primary"]["destination"] == "local"


async def test_put_omitting_key_keeps_existing_credential(repo):
    first = mod.ApplyIntelligenceRequest(
        mode="cloud",
        primary=mod.PrimaryInput(provider="deepseek", model="m", api_key="sk-first"),
    )
    await mod.put_intelligence(request=_request(), body=first, session=_FakeSession())
    assert len(repo.credentials) == 1

    # Re-save without a key → no new credential, no rotation.
    again = mod.ApplyIntelligenceRequest(
        mode="cloud",
        primary=mod.PrimaryInput(provider="deepseek", model="m2"),
    )
    await mod.put_intelligence(request=_request(), body=again, session=_FakeSession())
    assert len(repo.credentials) == 1
    assert repo.audit.count("credential_rotated") == 0
    assert len(repo.connections) == 1  # reused, not duplicated


async def test_put_fallback_chain_creates_ordered_routes(repo):
    body = mod.ApplyIntelligenceRequest(
        mode="cloud",
        primary=mod.PrimaryInput(provider="deepseek", model="deepseek/deepseek-chat", api_key="k"),
        fallback=[
            mod.ConnectionInput(provider="openrouter", model="openrouter/a:free", api_key="or"),
            mod.ConnectionInput(provider="openrouter", model="openrouter/b:free"),
        ],
    )
    view = await mod.put_intelligence(request=_request(), body=body, session=_FakeSession())
    assert [f["priority"] for f in view["fallback"]] == [0, 1]
    assert [f["model"] for f in view["fallback"]] == ["openrouter/a:free", "openrouter/b:free"]
    # both fallback rows share the single openrouter connection
    assert len({f["connection_id"] for f in view["fallback"]}) == 1


# ── consent (separate step) ─────────────────────────────────────────────


async def test_consent_requires_cloud_mode(repo):
    with pytest.raises(HTTPException) as exc:
        await mod.post_consent(body=mod.ConsentRequest(granted=True), session=_FakeSession())
    assert exc.value.status_code == 409


async def test_put_then_consent_grants_then_revokes(repo):
    await mod.put_intelligence(
        request=_request(),
        body=mod.ApplyIntelligenceRequest(
            mode="cloud", primary=mod.PrimaryInput(provider="deepseek", model="m", api_key="k")
        ),
        session=_FakeSession(),
    )
    granted = await mod.post_consent(
        body=mod.ConsentRequest(granted=True, consent_version="2026-06"), session=_FakeSession()
    )
    assert granted["allow_cloud_egress"] is True
    assert granted["consent"]["granted"] is True
    assert granted["consent"]["version"] == "2026-06"

    revoked = await mod.post_consent(body=mod.ConsentRequest(granted=False), session=_FakeSession())
    assert revoked["allow_cloud_egress"] is False
    assert revoked["consent"]["granted"] is False


# ── test-connection (SSRF-guarded) ──────────────────────────────────────


async def test_test_connection_inline_ok(repo, monkeypatch):
    class _OkClient:
        async def healthcheck(self):
            return HealthcheckResult(
                ok=True, destination="cloud", model="deepseek/x", latency_ms=42
            )

    monkeypatch.setattr(mod, "_make_client", lambda config: _OkClient())
    out = await mod.test_connection(
        body=mod.TestConnectionRequest(provider="deepseek", model="deepseek/x", api_key="sk-x"),
        session=_FakeSession(),
    )
    assert out["ok"] is True
    assert out["latency_ms"] == 42
    _no_secret_anywhere(out, "sk-x")


async def test_test_connection_ssrf_returns_400(repo, monkeypatch):
    class _Ssrf:
        async def healthcheck(self):
            raise SsrfError("resolves to non-public address")

    monkeypatch.setattr(mod, "_make_client", lambda config: _Ssrf())
    with pytest.raises(HTTPException) as exc:
        await mod.test_connection(
            body=mod.TestConnectionRequest(
                provider="custom", model="m", base_url="https://sneaky.internal", api_key="k"
            ),
            session=_FakeSession(),
        )
    assert exc.value.status_code == 400


async def test_test_connection_requires_provider_or_id(repo):
    with pytest.raises(HTTPException) as exc:
        await mod.test_connection(body=mod.TestConnectionRequest(), session=_FakeSession())
    assert exc.value.status_code == 422


async def test_test_connection_stored_records_result(repo, monkeypatch):
    # Seed a stored connection via PUT, then test it by id.
    await mod.put_intelligence(
        request=_request(),
        body=mod.ApplyIntelligenceRequest(
            mode="cloud", primary=mod.PrimaryInput(provider="deepseek", model="m", api_key="k")
        ),
        session=_FakeSession(),
    )
    conn_id = repo.connections[0].id

    class _OkClient:
        async def healthcheck(self):
            return HealthcheckResult(ok=True, destination="cloud", model="m", latency_ms=10)

    monkeypatch.setattr(mod, "_make_client", lambda config: _OkClient())
    out = await mod.test_connection(
        body=mod.TestConnectionRequest(connection_id=conn_id), session=_FakeSession()
    )
    assert out["ok"] is True
    assert repo.connections[0].last_test_status == "ok"
    assert "provider_healthcheck" in repo.audit
