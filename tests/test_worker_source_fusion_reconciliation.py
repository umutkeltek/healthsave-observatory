"""Worker source-poll fusion reconciliation hook."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "worker"))
sys.path.insert(0, str(ROOT / "packages" / "py"))

import httpx  # noqa: E402
import plugin_sdk  # noqa: E402
from normalization.fusion import DeviceLinkConfidence, VariantTier  # noqa: E402
from plugin_sdk import PluginManifest  # noqa: E402
from storage.timescale.fusion import (  # noqa: E402
    SessionCandidatePair,
    SessionObservationCandidate,
)
from worker import sources  # noqa: E402

from contracts import DEFAULT_OWNER_ID, DEFAULT_WORKSPACE_ID  # noqa: E402

DIRECT_OBS = uuid5(NAMESPACE_DNS, "healthsave.test.worker.direct-observation")
RELAYED_OBS = uuid5(NAMESPACE_DNS, "healthsave.test.worker.relayed-observation")
DIRECT_STREAM = uuid5(NAMESPACE_DNS, "healthsave.test.worker.direct-stream")
RELAYED_STREAM = uuid5(NAMESPACE_DNS, "healthsave.test.worker.relayed-stream")


def _manifest(*, session_capability: bool = True) -> PluginManifest:
    source_capabilities = []
    if session_capability:
        source_capabilities.append(
            {
                "plugin_id": "polar-accesslink",
                "metrics": ["measurement.workouts"],
                "delivery": "polling",
                "record_shape": "session",
                "aggregation_scope": "interval_component",
                "credential_ownership": "owner",
                "identity_priority": ["provider_object_id", "device_identity_link"],
            }
        )
    else:
        source_capabilities.append(
            {
                "plugin_id": "google-health-api",
                "metrics": ["measurement.step_count"],
                "delivery": "polling",
                "record_shape": "daily_total",
                "aggregation_scope": "provider_account_day_total",
                "credential_ownership": "owner",
                "identity_priority": ["provider_object_id"],
            }
        )
    return PluginManifest.model_validate(
        {
            "id": "polar-accesslink" if session_capability else "google-health-api",
            "name": "Test Source",
            "kind": "source",
            "version": "0.1.0",
            "sdk_version": ">=0.1,<0.2",
            "language": "python",
            "entrypoint": "tests.fake:FakeSource",
            "source_capabilities": source_capabilities,
        }
    )


def _pair() -> SessionCandidatePair:
    direct = SessionObservationCandidate(
        observation_id=DIRECT_OBS,
        stream_id=DIRECT_STREAM,
        vendor_family="polar",
        activity_type="RUNNING",
        start_epoch_s=1_779_970_000.0,
        end_epoch_s=1_779_971_800.0,
        provider_object_id="polar-exercise-1",
        variant_tier=VariantTier.DIRECT_WITH_PROVIDER_ID,
    )
    relayed = SessionObservationCandidate(
        observation_id=RELAYED_OBS,
        stream_id=RELAYED_STREAM,
        vendor_family="polar",
        activity_type="RUNNING",
        start_epoch_s=1_779_970_000.0,
        end_epoch_s=1_779_971_800.0,
        provider_object_id=None,
        variant_tier=VariantTier.HC_PACKAGE_AND_DEVICE,
    )
    return SessionCandidatePair(
        provider_subject_id="polar-user-10579",
        direct=direct,
        relayed=relayed,
        device_link=DeviceLinkConfidence.STRONG,
    )


class _FusionRepo:
    def __init__(self) -> None:
        self.find_calls: list[dict] = []
        self.reconcile_calls: list[dict] = []

    async def find_session_candidate_pairs(self, session, **kwargs):
        session.events.append("fusion_find")
        self.find_calls.append(kwargs)
        return [_pair()]

    async def reconcile_session_pair(self, session, **kwargs):
        session.events.append("fusion_reconcile")
        self.reconcile_calls.append(kwargs)
        return None


class _Session:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")


class _SessionFactory:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Session:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def __call__(self) -> _SessionFactory:
        return self


class _HttpClient:
    async def __aenter__(self) -> _HttpClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakePlugin:
    def __init__(self, manifest: PluginManifest) -> None:
        self.manifest = manifest

    async def ingest(self, payload):
        payload["session"].events.append("ingest")
        return {"accepted": 1, "rejected": 0}


@pytest.mark.asyncio
async def test_reconcile_source_poll_sessions_noops_without_session_capability():
    repo = _FusionRepo()
    session = _Session()

    count = await sources.reconcile_source_poll_sessions(
        session,
        manifest=_manifest(session_capability=False),
        fusion_repository=repo,
    )

    assert count == 0
    assert repo.find_calls == []
    assert repo.reconcile_calls == []


@pytest.mark.asyncio
async def test_make_source_poll_runs_fusion_after_successful_ingest_commit(monkeypatch):
    session = _Session()
    repo = _FusionRepo()

    monkeypatch.setattr(sources, "_plugin_yaml", lambda slug: Path("unused.yaml"))
    monkeypatch.setattr(sources, "_load_entrypoint", lambda entrypoint: _FakePlugin)
    monkeypatch.setattr(plugin_sdk, "load_manifest", lambda path: _manifest())
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: _HttpClient())

    poll = sources.make_source_poll(
        _SessionFactory(session),
        spec=sources.SourcePollSpec(
            slug="polar",
            entrypoint="plugins.sources.polar:PolarSource",
            log_label="polar",
        ),
        fusion_repository=repo,
    )

    await poll()

    assert session.events == ["ingest", "commit", "fusion_find", "fusion_reconcile", "commit"]
    assert repo.find_calls[0]["owner_id"] == DEFAULT_OWNER_ID
    assert repo.find_calls[0]["workspace_id"] == DEFAULT_WORKSPACE_ID
    assert repo.reconcile_calls[0]["provider_subject_id"] == "polar-user-10579"
    assert repo.reconcile_calls[0]["decided_by"] == "source-poll:polar-accesslink"
