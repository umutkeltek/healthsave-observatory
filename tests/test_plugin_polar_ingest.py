"""Polar AccessLink plugin ingest path."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "py"))

from auth import DEFAULT_OWNER_ID, OAuthToken  # noqa: E402
from normalization import identity  # noqa: E402
from normalization.fusion import exact_ingest_key  # noqa: E402
from plugin_sdk import load_manifest  # noqa: E402

from plugins.sources.polar import POLAR_PROVIDER, PolarSource  # noqa: E402
from plugins.sources.polar.fetch import PATH_EXERCISES  # noqa: E402

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugins" / "sources" / "polar"


@dataclass
class _Response:
    status_code: int
    payload: dict[str, Any]
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self.payload


@dataclass
class _HttpClient:
    response: _Response
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def get(self, url: str, *, params=None, headers=None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self.response


@dataclass
class _IngestCall:
    metric: str
    samples: list[dict]
    device_id: int | str
    owner_id: Any


class _Storage:
    def __init__(self):
        self.ingest_calls: list[_IngestCall] = []

    async def get_or_create_device(self, session, device_type):
        return f"device:{device_type}"

    async def ingest_metric(self, session, device_id, metric, samples, owner_id):
        self.ingest_calls.append(
            _IngestCall(metric=metric, samples=samples, device_id=device_id, owner_id=owner_id)
        )
        return len(samples)


class _CanonicalRepo:
    def __init__(self):
        self.insert_calls: list[tuple[Any, list]] = []

    async def insert_many(self, session, observations):
        self.insert_calls.append((session, observations))
        return len(observations)


@dataclass
class _TokenStore:
    token: OAuthToken | None

    async def get_token(self, session, *, provider, owner_id):
        return self.token


def _plugin() -> PolarSource:
    return PolarSource(load_manifest(PLUGIN_DIR / "plugin.yaml"))


def _token() -> OAuthToken:
    return OAuthToken(
        owner_id=DEFAULT_OWNER_ID,
        provider=POLAR_PROVIDER,
        access_token="AT",
        refresh_token=None,
        expires_at=None,
        metadata={"x_user_id": 10579},
    )


@pytest.mark.asyncio
async def test_polar_ingest_returns_zero_when_no_token_stored():
    result = await _plugin().ingest(
        {
            "storage": _Storage(),
            "session": object(),
            "http_client": _HttpClient(_Response(200, {"exercises": []})),
            "token_store": _TokenStore(None),
        }
    )

    assert result == {"accepted": 0, "rejected": 0}


@pytest.mark.asyncio
async def test_polar_ingest_fetches_exercises_and_writes_existing_storage_port():
    storage = _Storage()
    canonical_repo = _CanonicalRepo()
    http = _HttpClient(
        _Response(
            200,
            {
                "exercises": [
                    {
                        "id": "2AC312F",
                        "device_id": "1111AAAA",
                        "start_time": "2008-10-13T10:40:02",
                        "duration": "PT30M",
                        "sport": "RUNNING",
                    }
                ]
            },
        )
    )

    result = await _plugin().ingest(
        {
            "storage": storage,
            "session": object(),
            "http_client": http,
            "token_store": _TokenStore(_token()),
            "canonical_repository": canonical_repo,
        }
    )

    assert result == {"accepted": 3, "rejected": 0}
    assert http.calls[0]["url"].endswith(PATH_EXERCISES)
    assert [call.metric for call in storage.ingest_calls] == [
        "workouts",
        "exercise_duration_seconds",
    ]
    assert storage.ingest_calls[0].device_id == "device:Polar"
    assert storage.ingest_calls[0].samples[0]["provider_object_id"] == "2AC312F"


@pytest.mark.asyncio
async def test_polar_ingest_writes_canonical_workout_session_for_fusion():
    storage = _Storage()
    canonical_repo = _CanonicalRepo()
    session = object()
    http = _HttpClient(
        _Response(
            200,
            {
                "exercises": [
                    {
                        "id": "2AC312F",
                        "device_id": "1111AAAA",
                        "start_time": "2008-10-13T10:40:02Z",
                        "duration": "PT30M",
                        "sport": "RUNNING",
                        "calories": 321,
                        "distance": 5123.4,
                    }
                ]
            },
        )
    )

    result = await _plugin().ingest(
        {
            "storage": storage,
            "session": session,
            "http_client": http,
            "token_store": _TokenStore(_token()),
            "canonical_repository": canonical_repo,
        }
    )

    assert result == {"accepted": 3, "rejected": 0}
    assert len(canonical_repo.insert_calls) == 1
    inserted_session, observations = canonical_repo.insert_calls[0]
    assert inserted_session is session
    assert len(observations) == 1

    obs = observations[0]
    expected_source_id = identity.source_uuid(DEFAULT_OWNER_ID, "polar-accesslink")
    expected_stream = identity.stream_id(DEFAULT_OWNER_ID, "polar-accesslink", "1111aaaa")
    assert obs.metric_id == "workout.session"
    assert obs.value.type == "event"
    assert obs.value.status == "completed"
    assert obs.value.label == "RUNNING"
    assert obs.value.summary["vendor_family"] == "polar"
    assert obs.value.summary["origin_provider"] == "polar-accesslink"
    assert obs.value.summary["provider_subject_id"] == "10579"
    assert obs.value.summary["provider_object_id"] == "2AC312F"
    assert obs.value.summary["provider_device_id"] == "1111AAAA"
    assert obs.value.summary["activity_type"] == "RUNNING"
    assert obs.value.summary["duration_seconds"] == 1800
    assert obs.value.summary["calories"] == 321.0
    assert obs.value.summary["distance_m"] == 5123.4
    assert obs.source_id == expected_source_id
    assert obs.stream_id == expected_stream
    assert obs.source_record_uid == "2AC312F"
    assert obs.exact_ingest_key == exact_ingest_key(
        DEFAULT_OWNER_ID,
        expected_source_id,
        "exercise",
        provider_object_id="2AC312F",
    )
    assert obs.aggregation_scope == "interval_component"
    assert obs.normalizer_id == "polar-accesslink"
