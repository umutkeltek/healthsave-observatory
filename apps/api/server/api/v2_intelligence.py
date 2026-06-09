"""``/api/v2/intelligence/*`` — the narrator ("Intelligence") settings surface.

The write side of ADR-0003: a self-hoster configures the LLM narrator here
(off / local / cloud-BYOK), and the worker picks it up per job without a
redeploy (see ``analysis.intelligence.resolve_llm_config``). Four operations,
shaped by the Oracle-locked decisions:

* ``GET  /``                — the current posture, with NO secrets (only
  ``key_last4``) and an ``managed_by_env`` hint when env bootstrap config is
  currently the effective source.
* ``PUT  /``                — declarative apply: mode + primary provider/model
  (+ optional key) + the fallback chain. The server classifies each route's
  trust zone (D1) — the client never asserts ``destination``. Does NOT grant
  cloud egress (that is consent's job).
* ``POST /consent``         — the SEPARATE consent step (D5): grant flips the
  cloud-egress opt-in on + stamps consent; revoke clears it. mode=cloud alone
  never egresses until this is granted.
* ``POST /test-connection`` — verify a provider key works (D7) BEFORE consent,
  behind the SSRF guard; audited as ``provider_healthcheck``, no health data.

Secret discipline: an API key enters only via PUT / test-connection request
bodies and is sealed at the storage boundary; it is NEVER returned. Storage
access is the ``storage.timescale.intelligence`` repo; trust classification is
``analysis.egress`` — this module composes them (apps/api is top of the chain).
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import httpx
from analysis.config import LLMConfig
from analysis.egress import Destination, EgressRoute, classify_destination
from analysis.llm.client import HealthLLMClient
from analysis.netguard import SsrfError
from contracts._base import V2Model
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession
from storage.timescale import intelligence as repo_module
from storage.timescale.intelligence import FallbackRouteInput

from .deps import get_session, verify_api_key

_log = logging.getLogger("healthsave.api.v2_intelligence")

router = APIRouter(prefix="/api/v2/intelligence", dependencies=[Depends(verify_api_key)])

# Injectable seams (monkeypatched in tests so route tests stay DB-/network-free).
_repo = repo_module


def _make_client(config: LLMConfig) -> HealthLLMClient:
    """Build a narrator client for a one-off healthcheck (test seam)."""
    return HealthLLMClient(config)


# Known LOCAL Ollama endpoints to probe for the "easy local" path (ADR-0003 D8):
# the bundled sidecar (compose `local-ai` profile) and an Ollama running on the
# host machine. Both hostnames are inside the trust boundary (analysis.egress
# _LOCAL_HOSTS), so probing them is not an egress; the list is hardcoded, so the
# detect endpoint is not an SSRF surface.
_LOCAL_OLLAMA_URLS = ("http://ollama:11434", "http://host.docker.internal:11434")


async def _probe_ollama(url: str) -> dict:
    """GET ``<url>/api/tags`` (short timeout); return reachability + model names."""
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(f"{url}/api/tags")
            resp.raise_for_status()
            models = [m.get("name") for m in resp.json().get("models", []) if m.get("name")]
        return {"url": url, "reachable": True, "models": models}
    except Exception:  # noqa: BLE001 - unreachable is a normal answer here
        return {"url": url, "reachable": False, "models": []}


# ──────────────────────────────────────────────────────────────────────
# Wire models (V2Model: extra='forbid'; single-user → no owner/workspace,
# matching v2_agents / v2_experiments)
# ──────────────────────────────────────────────────────────────────────


class ConnectionInput(V2Model):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=2000)
    # Write-only. Omit on a re-save to keep the existing sealed key.
    api_key: str | None = Field(default=None, max_length=4000)
    display_name: str | None = Field(default=None, max_length=200)


class PrimaryInput(ConnectionInput):
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=8000)


class ApplyIntelligenceRequest(V2Model):
    mode: Literal["off", "local", "cloud"]
    primary: PrimaryInput | None = None
    fallback: list[ConnectionInput] | None = None
    redact_cloud_prompts: bool | None = None


class ConsentRequest(V2Model):
    granted: bool
    consent_version: str | None = Field(default=None, max_length=64)
    consent_text_hash: str | None = Field(default=None, max_length=128)


class TestConnectionRequest(V2Model):
    # Either test a stored connection by id, or an ad-hoc config inline.
    connection_id: int | None = None
    provider: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=2000)
    api_key: str | None = Field(default=None, max_length=4000)


# ──────────────────────────────────────────────────────────────────────
# Helpers (pure orchestration over the injected repo — unit-testable)
# ──────────────────────────────────────────────────────────────────────


def _trusted_local_hosts(request: Request) -> frozenset[str]:
    llm = request.app.state.analysis_config.llm
    return frozenset(getattr(llm, "trusted_local_hosts", ()) or ())


def _classify(provider: str, base_url: str | None, trusted: frozenset[str]) -> Destination:
    return classify_destination(
        EgressRoute(provider=provider, base_url=base_url), trusted_local_hosts=trusted
    )


async def _upsert_provider_connection(
    session: AsyncSession,
    conn: ConnectionInput,
    *,
    trusted: frozenset[str],
) -> int:
    """Find-or-create the connection for ``conn.provider`` and return its id.

    Single-user model: one connection per provider, reused across saves so test
    status / id stay stable. A supplied ``api_key`` creates or rotates the
    sealed credential; an omitted key keeps the existing one. ``destination`` is
    classified server-side from (provider, base_url) — never the client's claim.
    """
    existing = [c for c in await _repo.list_connections(session) if c.provider == conn.provider]
    connection_id = existing[0].id if existing else None
    credential_id = existing[0].credential_id if existing else None

    if conn.api_key:
        if credential_id is not None:
            await _repo.default_repository.rotate_credential(
                session, credential_id=credential_id, api_key=conn.api_key
            )
        else:
            ref = await _repo.default_repository.put_credential(
                session, provider=conn.provider, api_key=conn.api_key
            )
            credential_id = ref.id

    destination = _classify(conn.provider, conn.base_url, trusted)
    saved = await _repo.default_repository.upsert_connection(
        session,
        connection_id=connection_id,
        provider=conn.provider,
        base_url=conn.base_url,
        display_name=conn.display_name,
        credential_id=credential_id,
        destination=destination.value,
    )
    return saved.id


async def _build_view(session: AsyncSession, *, env_provider: str | None) -> dict:
    """Compose the current posture for the UI — secrets stripped to last4."""
    settings = await _repo.get_settings(session)
    connections = await _repo.list_connections(session)
    by_id = {c.id: c for c in connections}

    # key_last4 per connection via its credential (single-user → few rows).
    last4: dict[int, str | None] = {}
    for c in connections:
        if c.credential_id is not None:
            cred = await _repo.default_repository.get_credential(
                session, credential_id=c.credential_id
            )
            last4[c.id] = cred.key_last4 if cred else None

    def conn_view(c) -> dict:
        return {
            "id": c.id,
            "provider": c.provider,
            "display_name": c.display_name,
            "base_url": c.base_url,
            "destination": c.destination,
            "enabled": c.enabled,
            "key_last4": last4.get(c.id),
            "last_test_status": c.last_test_status,
            "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
        }

    db_active = settings is not None and settings.mode != "off"
    primary = None
    fallback: list[dict] = []
    if settings is not None:
        if settings.primary_connection_id and settings.primary_connection_id in by_id:
            primary = conn_view(by_id[settings.primary_connection_id])
            primary["model"] = settings.primary_model
        for route in await _repo.get_fallback_routes(session):
            fc = by_id.get(route.connection_id)
            fallback.append(
                {
                    "priority": route.priority,
                    "connection_id": route.connection_id,
                    "provider": fc.provider if fc else None,
                    "model": route.model,
                    "destination": fc.destination if fc else None,
                }
            )

    return {
        "mode": settings.mode if settings else "off",
        # Env bootstrap config is the effective source only until the owner
        # configures Intelligence in the UI; once mode!=off, the DB wins and the
        # UI controls are authoritative (no "the UI lies" problem — saving here
        # always takes over). The hint stays informational, not a lockout.
        "managed_by_env": env_provider is not None and not db_active,
        "env_provider": env_provider,
        "allow_cloud_egress": bool(settings.allow_cloud_egress) if settings else False,
        "redact_cloud_prompts": bool(settings.redact_cloud_prompts) if settings else True,
        "revision": settings.revision if settings else 0,
        "consent": {
            "granted": bool(settings and settings.consented_at is not None),
            "version": settings.consent_version if settings else None,
            "at": settings.consented_at.isoformat() if settings and settings.consented_at else None,
        },
        "primary": primary,
        "fallback": fallback,
    }


# ──────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────


@router.get("")
async def get_intelligence(session: AsyncSession = Depends(get_session)) -> dict:
    """Current narrator posture (no secrets)."""
    return await _build_view(session, env_provider=os.getenv("LLM_PROVIDER") or None)


@router.put("")
async def put_intelligence(
    request: Request,
    body: ApplyIntelligenceRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Apply mode + primary + fallback. Does NOT grant cloud egress (see consent)."""
    trusted = _trusted_local_hosts(request)

    fields: dict = {"mode": body.mode}
    if body.primary is not None:
        primary_id = await _upsert_provider_connection(session, body.primary, trusted=trusted)
        fields["primary_connection_id"] = primary_id
        fields["primary_model"] = body.primary.model
        if body.primary.temperature is not None:
            fields["primary_temperature"] = body.primary.temperature
        if body.primary.max_tokens is not None:
            fields["primary_max_tokens"] = body.primary.max_tokens
    if body.redact_cloud_prompts is not None:
        fields["redact_cloud_prompts"] = body.redact_cloud_prompts

    if body.fallback is not None:
        routes: list[FallbackRouteInput] = []
        for fb in body.fallback:
            cid = await _upsert_provider_connection(session, fb, trusted=trusted)
            routes.append(FallbackRouteInput(connection_id=cid, model=fb.model))
        await _repo.default_repository.set_fallback_routes(session, routes=routes)

    await _repo.default_repository.update_settings(session, actor="api", **fields)
    await session.commit()
    return await _build_view(session, env_provider=os.getenv("LLM_PROVIDER") or None)


@router.post("/consent")
async def post_consent(
    body: ConsentRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Grant / revoke the cloud-egress opt-in (the separate consent step, D5)."""
    settings = await _repo.get_settings(session)
    if body.granted and (settings is None or settings.mode != "cloud"):
        raise HTTPException(
            status_code=409,
            detail="configure a cloud provider (mode='cloud') before granting consent",
        )
    await _repo.default_repository.record_consent(
        session,
        granted=body.granted,
        consent_version=body.consent_version,
        consent_text_hash=body.consent_text_hash,
        consented_by="api",
        actor="api",
    )
    await session.commit()
    return await _build_view(session, env_provider=os.getenv("LLM_PROVIDER") or None)


@router.post("/test-connection")
async def test_connection(
    body: TestConnectionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Probe a provider (SSRF-guarded, one token, no health data); audit it."""
    if body.connection_id is not None:
        conn = await _repo.get_connection(session, connection_id=body.connection_id)
        if conn is None:
            raise HTTPException(status_code=404, detail="connection not found")
        provider, base_url = conn.provider, conn.base_url
        model = body.model or (await _stored_model(session, conn.id))
        api_key = await _repo.get_connection_secret(session, connection_id=conn.id) or ""
    else:
        if not body.provider or not body.model:
            raise HTTPException(
                status_code=422, detail="provide connection_id, or provider + model"
            )
        provider, base_url, model, api_key = (
            body.provider,
            body.base_url,
            body.model,
            body.api_key or "",
        )

    config = LLMConfig(provider=provider, model=model, base_url=base_url or "", api_key=api_key)
    client = _make_client(config)
    try:
        result = await client.healthcheck()
    except SsrfError as exc:
        raise HTTPException(status_code=400, detail=f"unsafe target: {exc}") from exc

    # Persist the outcome on the stored connection + audit it (no health data).
    if body.connection_id is not None:
        await _repo.default_repository.record_test_result(
            session, connection_id=body.connection_id, status="ok" if result.ok else "failed"
        )
        await session.commit()

    return {
        "ok": result.ok,
        "destination": result.destination,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "error": result.error,
    }


@router.get("/detect-local")
async def detect_local() -> dict:
    """Probe the known local Ollama endpoints so the UI can auto-fill "Local".

    Returns each candidate's reachability + installed models. No DB, no health
    data, no egress (the targets are inside the trust boundary). Lets a
    non-technical user click "Detect" instead of typing a base URL.
    """
    import asyncio

    candidates = await asyncio.gather(*[_probe_ollama(u) for u in _LOCAL_OLLAMA_URLS])
    return {"candidates": list(candidates)}


async def _stored_model(session: AsyncSession, connection_id: int) -> str:
    """Best-effort model for a stored connection: its primary/fallback route model."""
    settings = await _repo.get_settings(session)
    if settings and settings.primary_connection_id == connection_id and settings.primary_model:
        return settings.primary_model
    for route in await _repo.get_fallback_routes(session):
        if route.connection_id == connection_id:
            return route.model
    return ""
