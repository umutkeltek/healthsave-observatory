"""Apple Health (HealthSave bridge) plugin contract tests.

Phase 6 ships this as the first first-party Source plugin. Tests
verify the manifest is well-formed, the entrypoint resolves to a
``plugin_sdk.Source`` subclass, and the discovery walk finds it in
the live ``plugins/`` directory.

The wrapper's ``ingest`` method itself is implicitly covered by
``tests/test_api_contract.py``: the route → ingest pipeline path is
the same one the plugin delegates to, so any regression there
also fails the route tests. We do NOT duplicate that integration
coverage here.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_sdk import (  # noqa: E402
    PluginManifest,
    Source,
    discover,
    is_sdk_compatible,
    load_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "plugins" / "sources" / "apple_health_healthsave"


def test_apple_health_plugin_directory_exists():
    assert PLUGIN_DIR.is_dir(), f"Apple Health plugin directory missing: {PLUGIN_DIR}"
    assert (PLUGIN_DIR / "plugin.yaml").is_file()
    assert (PLUGIN_DIR / "__init__.py").is_file()
    assert (PLUGIN_DIR / "README.md").is_file()


def test_apple_health_manifest_parses_and_validates():
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    assert isinstance(manifest, PluginManifest)
    assert manifest.id == "apple-health-healthsave"
    assert manifest.kind == "source"
    assert manifest.language == "python"
    # SDK target accepts the running SDK.
    assert is_sdk_compatible(manifest)


def test_apple_health_manifest_emits_every_route_supported_metric():
    """If iOS POSTs a metric, the plugin manifest should declare it.

    The route's per-metric dispatch (storage.timescale.measurements._ingest_metric)
    handles a fixed set of dedicated tables + a quantity_samples
    catch-all. The manifest enumerates the headline metrics; the
    catch-all is named explicitly so operators know what's covered.
    """
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    declared = set(manifest.emits)
    must_include = {
        "measurement.heart_rate",
        "measurement.hrv",
        "measurement.sleep_analysis",
        "measurement.workouts",
        "measurement.activity_summaries",
        "measurement.quantity_samples",
    }
    missing = must_include - declared
    assert not missing, f"plugin manifest is missing declared emits: {missing}"


def test_apple_health_entrypoint_resolves_to_source_subclass():
    """``entrypoint: module:Class`` must resolve to a Source subclass."""
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    module_path, _, class_name = manifest.entrypoint.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    assert issubclass(cls, Source), f"{cls!r} is not a Source subclass"


def test_apple_health_class_instantiates_with_manifest():
    """Loader will call ``cls(manifest)``; that must succeed."""
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    module_path, _, class_name = manifest.entrypoint.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    instance = cls(manifest)
    assert isinstance(instance, Source)
    assert instance.manifest is manifest


def test_apple_health_plugin_discovered_under_real_plugins_dir():
    """``discover()`` walks the actual ``plugins/`` and finds it."""
    found = discover()
    matches = [p for p in found if p.plugin_id == "apple-health-healthsave"]
    assert len(matches) == 1, (
        f"expected exactly one apple-health-healthsave plugin; found {len(matches)}"
    )
    only = matches[0]
    assert only.kind == "source"
    assert only.plugin_dir == PLUGIN_DIR.resolve()


def test_apple_health_plugin_permissions_are_minimal():
    """No network, no secrets — the plugin operates entirely inside the API process."""
    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    assert manifest.permissions.network is False
    assert manifest.permissions.secrets == []
    # The two declared capabilities are storage writes, not arbitrary side effects.
    capability_names = {c.name for c in manifest.permissions.capabilities}
    assert capability_names == {"write:raw_ingestion_log", "write:measurements"}


@pytest.mark.asyncio
async def test_apple_health_ingest_is_a_thin_wrapper_returns_zero_on_empty_payload():
    """Empty payload → no rows committed, no rejected.

    Phase 6.1: the plugin requires a ``storage`` Protocol instance in
    the payload. The empty branch short-circuits before touching storage,
    so we pass a sentinel that would explode if invoked — this proves
    the empty path is dispatch-free.
    """
    from plugins.sources.apple_health_healthsave import AppleHealthSource

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = AppleHealthSource(manifest)
    result = await plugin.ingest(
        {
            "storage": object(),  # not invoked when samples is empty
            "session": object(),  # not invoked when samples is empty
            "device_id": 1,
            "metric": "heart_rate",
            "samples": [],
        }
    )
    assert result == {"accepted": 0, "rejected": 0}


@pytest.mark.asyncio
async def test_apple_health_ingest_projects_from_canonical_observations_when_supplied():
    """Canonical observations are the source for the per-metric projection path."""
    from datetime import UTC, datetime

    from contracts._base import DEFAULT_OWNER_ID, Provenance
    from contracts.observation import Observation, build_dedup_key
    from contracts.values import QuantityValue
    from storage.results import IngestWriteResult

    from plugins.sources.apple_health_healthsave import AppleHealthSource

    observed_at = datetime(2026, 5, 11, 8, 0, tzinfo=UTC)
    obs = Observation(
        metric_id="vital.heart_rate",
        value=QuantityValue(
            type="quantity", value=72, unit="bpm", canonical_value=72, canonical_unit="bpm"
        ),
        interval_start=observed_at,
        interval_end=observed_at,
        source_id="a9b1e7e0-0000-4000-8000-000000000001",
        provenance=Provenance(
            source_plugin_id="apple-health-healthsave",
            sdk_version="test",
            captured_at=observed_at,
        ),
        normalizer_id="apple_health",
        normalizer_version="test",
        dedup_key=build_dedup_key(
            owner_id=DEFAULT_OWNER_ID,
            workspace_id=DEFAULT_OWNER_ID,
            source_id="a9b1e7e0-0000-4000-8000-000000000001",
            metric_id="vital.heart_rate",
            interval_start=observed_at,
            interval_end=observed_at,
            value_repr="72",
        ),
    )

    class ExplodingStorage:
        async def get_or_create_device(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("raw storage path should not be used")

        async def ingest_metric(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("raw storage path should not be used")

    class RecordingProjection:
        def __init__(self):
            self.calls = []

        async def project_observations(self, session, device_id, metric, observations, owner_id):
            self.calls.append((session, device_id, metric, observations, owner_id))
            return IngestWriteResult(accepted=len(observations))

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = AppleHealthSource(manifest)
    projection = RecordingProjection()
    session = object()

    result = await plugin.ingest(
        {
            "storage": ExplodingStorage(),
            "projection": projection,
            "session": session,
            "device_id": 1,
            "metric": "heart_rate",
            "samples": [{"date": observed_at.isoformat(), "qty": 72, "source": "Apple Watch"}],
            "canonical_observations": [obs],
            "owner_id": DEFAULT_OWNER_ID,
        }
    )

    assert result["accepted"] == 1
    assert len(projection.calls) == 1
    call_session, device_id, metric, observations, owner_id = projection.calls[0]
    assert call_session is session
    assert device_id == 1
    assert metric == "heart_rate"
    assert observations == [obs]
    assert owner_id == DEFAULT_OWNER_ID


@pytest.mark.asyncio
async def test_apple_health_ingest_projects_mixed_sources_under_their_own_devices():
    """Canonical projection must preserve per-sample device attribution."""
    from datetime import UTC, datetime

    from contracts._base import DEFAULT_OWNER_ID, Provenance
    from contracts.observation import Observation, build_dedup_key
    from contracts.values import QuantityValue
    from normalization.identity import resolve_apple_origin
    from storage.results import IngestWriteResult

    from plugins.sources.apple_health_healthsave import AppleHealthSource

    source_id = "a9b1e7e0-0000-4000-8000-000000000001"
    observed_at = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

    def observation(source: str, value: int, source_record_uid: str) -> Observation:
        stream_id = resolve_apple_origin(DEFAULT_OWNER_ID, source).stream_id
        return Observation(
            metric_id="vital.heart_rate",
            value=QuantityValue(
                type="quantity",
                value=value,
                unit="bpm",
                canonical_value=value,
                canonical_unit="bpm",
            ),
            interval_start=observed_at,
            interval_end=observed_at,
            source_id=source_id,
            stream_id=stream_id,
            source_record_uid=source_record_uid,
            provenance=Provenance(
                source_plugin_id="apple-health-healthsave",
                sdk_version="test",
                captured_at=observed_at,
            ),
            normalizer_id="apple_health",
            normalizer_version="test",
            dedup_key=build_dedup_key(
                owner_id=DEFAULT_OWNER_ID,
                workspace_id=DEFAULT_OWNER_ID,
                source_id=source_id,
                metric_id="vital.heart_rate",
                interval_start=observed_at,
                interval_end=observed_at,
                source_record_uid=source_record_uid,
            ),
        )

    peloton_obs = observation("Peloton", 120, "peloton-uuid")
    withings_obs = observation("Withings", 72, "withings-uuid")

    class RecordingStorage:
        def __init__(self):
            self.device_lookups = []

        async def get_or_create_device(self, session, device_name):
            self.device_lookups.append(device_name)
            assert device_name == "Withings"
            return 15

        async def ingest_metric(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("raw storage path should not be used")

    class RecordingProjection:
        def __init__(self):
            self.calls = []

        async def project_observations(self, session, device_id, metric, observations, owner_id):
            observations = list(observations)
            self.calls.append((device_id, observations))
            return IngestWriteResult(accepted=len(observations))

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = AppleHealthSource(manifest)
    storage = RecordingStorage()
    projection = RecordingProjection()

    result = await plugin.ingest(
        {
            "storage": storage,
            "projection": projection,
            "session": object(),
            "device_id": 19,
            "first_device_name": "Peloton",
            "metric": "heart_rate",
            "samples": [
                {
                    "date": observed_at.isoformat(),
                    "qty": 120,
                    "source": "Peloton",
                    "uuid": "peloton-uuid",
                },
                {
                    "date": observed_at.isoformat(),
                    "qty": 72,
                    "source": "Withings",
                    "uuid": "withings-uuid",
                },
            ],
            "canonical_observations": [peloton_obs, withings_obs],
            "owner_id": DEFAULT_OWNER_ID,
        }
    )

    assert result["accepted"] == 2
    assert projection.calls == [
        (19, [peloton_obs]),
        (15, [withings_obs]),
    ]
    assert storage.device_lookups == ["Withings"]


@pytest.mark.asyncio
async def test_apple_health_ingest_falls_back_when_device_labels_share_a_stream():
    """Ambiguous normalized streams must keep the exact-label raw device path."""
    from contracts._base import DEFAULT_OWNER_ID
    from storage.results import IngestWriteResult

    from plugins.sources.apple_health_healthsave import AppleHealthSource

    class RecordingStorage:
        def __init__(self):
            self.device_lookups = []
            self.ingest_calls = []

        async def get_or_create_device(self, session, device_name):
            self.device_lookups.append(device_name)
            return {"withings": 15}[device_name]

        async def ingest_metric(self, session, device_id, metric, samples, owner_id):
            self.ingest_calls.append((device_id, samples))
            return IngestWriteResult(accepted=len(samples))

    class ExplodingProjection:
        async def project_observations(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("ambiguous stream mapping should not be projected")

    samples = [
        {"date": "2026-09-09T12:00:00Z", "qty": 72, "source": "Withings"},
        {"date": "2026-09-09T12:01:00Z", "qty": 73, "source": "withings"},
    ]

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = AppleHealthSource(manifest)
    storage = RecordingStorage()

    result = await plugin.ingest(
        {
            "storage": storage,
            "projection": ExplodingProjection(),
            "session": object(),
            "device_id": 14,
            "first_device_name": "Withings",
            "metric": "heart_rate",
            "samples": samples,
            "canonical_observations": [object()],
            "owner_id": DEFAULT_OWNER_ID,
        }
    )

    assert result["accepted"] == 2
    assert storage.device_lookups == ["withings"]
    assert storage.ingest_calls == [
        (14, [samples[0]]),
        (15, [samples[1]]),
    ]


@pytest.mark.asyncio
async def test_apple_health_ingest_falls_back_to_raw_writers_for_multi_device_workouts():
    """A workout batch from two devices must still reach the v1 writers.

    The projection only speaks quantity, so non-quantity metrics (workouts,
    sleep stages, ECG, category events) come back as an empty
    ``IngestWriteResult`` and the raw writers have to run. Combining those
    empty results turned the unset ``inserted_new`` into ``0``, which read as
    "already projected" and skipped the fallback: the v1 ``workouts`` and
    sleep tables froze on the day a self-hoster moved to v2 while the
    canonical store stayed current, and every receipt claimed 0 accepted.
    """
    from datetime import UTC, datetime

    from contracts._base import DEFAULT_OWNER_ID, Provenance
    from contracts.observation import Observation, build_dedup_key
    from contracts.values import EventValue
    from normalization.identity import resolve_apple_origin
    from storage.results import IngestWriteResult

    from plugins.sources.apple_health_healthsave import AppleHealthSource

    source_id = "a9b1e7e0-0000-4000-8000-000000000001"
    started_at = datetime(2026, 9, 10, 7, 0, tzinfo=UTC)
    ended_at = datetime(2026, 9, 10, 7, 45, tzinfo=UTC)

    def workout(source: str, source_record_uid: str) -> Observation:
        return Observation(
            metric_id="activity.workout",
            value=EventValue(type="event", label="Workout Session"),
            interval_start=started_at,
            interval_end=ended_at,
            source_id=source_id,
            stream_id=resolve_apple_origin(DEFAULT_OWNER_ID, source).stream_id,
            source_record_uid=source_record_uid,
            provenance=Provenance(
                source_plugin_id="apple-health-healthsave",
                sdk_version="test",
                captured_at=started_at,
            ),
            normalizer_id="apple_health",
            normalizer_version="test",
            dedup_key=build_dedup_key(
                owner_id=DEFAULT_OWNER_ID,
                workspace_id=DEFAULT_OWNER_ID,
                source_id=source_id,
                metric_id="activity.workout",
                interval_start=started_at,
                interval_end=ended_at,
                source_record_uid=source_record_uid,
            ),
        )

    class RecordingStorage:
        def __init__(self):
            self.ingest_calls = []

        async def get_or_create_device(self, session, device_name):
            assert device_name == "iPhone"
            return 21

        async def ingest_metric(self, session, device_id, metric, samples, owner_id):
            self.ingest_calls.append((device_id, metric, samples))
            return IngestWriteResult(accepted=len(samples))

    class EmptyProjection:
        """What the real projection returns for a non-quantity observation."""

        def __init__(self):
            self.calls = 0

        async def project_observations(self, session, device_id, metric, observations, owner_id):
            self.calls += 1
            return IngestWriteResult()

    samples = [
        {
            "uuid": "watch-workout",
            "start": started_at.isoformat(),
            "end": ended_at.isoformat(),
            "name": "Running",
            "source": "Apple Watch",
        },
        {
            "uuid": "phone-workout",
            "start": started_at.isoformat(),
            "end": ended_at.isoformat(),
            "name": "Walking",
            "source": "iPhone",
        },
    ]

    manifest = load_manifest(PLUGIN_DIR / "plugin.yaml")
    plugin = AppleHealthSource(manifest)
    storage = RecordingStorage()
    projection = EmptyProjection()

    result = await plugin.ingest(
        {
            "storage": storage,
            "projection": projection,
            "session": object(),
            "device_id": 20,
            "first_device_name": "Apple Watch",
            "metric": "workouts",
            "samples": samples,
            "canonical_observations": [
                workout("Apple Watch", "watch-workout"),
                workout("iPhone", "phone-workout"),
            ],
            "owner_id": DEFAULT_OWNER_ID,
        }
    )

    assert projection.calls == 2
    assert result["accepted"] == 2
    assert storage.ingest_calls == [
        (20, "workouts", [samples[0]]),
        (21, "workouts", [samples[1]]),
    ]


# ──────────────────────────────────────────────────────────────────────
# Registry-path integration test — addresses advisor concern that the
# Phase 6 SDK is "decorative" (registered but no test exercises the
# discover → instantiate → invoke path end-to-end). This test proves
# the load-bearing chain works: the SDK is Phase 7 ready, not just
# Phase 6 ready.
#
# Phase 6.1: the plugin is now Protocol-aware — writes go through an
# injected ``IngestStorage`` instance, not via direct
# ``storage.timescale.measurements`` calls. The test injects a recording
# storage on Path B and compares its SQL trace against Path A's direct
# ``_ingest_metric`` trace. Because the production ``PostgresIngestStorage``
# is a thin pass-through wrapper over ``measurements._ingest_metric`` /
# ``_get_or_create_device`` (Phase 5C contract), the two traces must
# stay byte-identical — that is the load-bearing claim Phase 7 needs.
# ──────────────────────────────────────────────────────────────────────


class _RegistryFakeSession:
    """Records every SQL call so the test can assert the plugin and
    the direct path produce the same INSERT shape."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.calls.append((sql, params or {}))
        # _ingest_metric → _ingest_generic → INSERT … RETURNING is not
        # used here; the catch-all path doesn't read back rows.
        from types import SimpleNamespace

        return SimpleNamespace(
            first=lambda: None,
            scalar=lambda: 1,
            fetchone=lambda: None,
            fetchall=lambda: [],
        )

    async def commit(self) -> None:
        pass


class _RegistryRecordingStorage:
    """``IngestStorage`` Protocol impl that delegates to the real
    ``storage.timescale.measurements`` helpers (the path the production
    ``PostgresIngestStorage`` takes). Lets the registry-path test prove
    that plugin → Protocol → measurements still issues byte-identical
    SQL vs the direct path.
    """

    async def get_or_create_device(self, session, device_type):
        from storage.timescale.measurements import _get_or_create_device

        return await _get_or_create_device(session, device_type)

    async def ingest_metric(self, session, device_id, metric, samples, owner_id):
        from storage.timescale.measurements import _ingest_metric

        return await _ingest_metric(session, device_id, metric, samples, owner_id)


@pytest.mark.asyncio
async def test_registry_load_path_produces_same_writes_as_direct_path():
    """End-to-end: discover → registry → instantiate → invoke produces
    byte-identical SQL writes vs calling the storage helper directly.

    This is the test that proves the Phase 6 SDK is load-bearing-ready
    and not a decorative abstraction. If the registry chain breaks
    (entrypoint resolves wrong, manifest-injection drifts the
    instance, the ABC method swaps an arg name), this test fails BEFORE
    Phase 7 tries to wire it.

    Phase 6.1: the plugin requires an ``IngestStorage`` in its payload.
    We inject ``_RegistryRecordingStorage`` which delegates to the same
    ``_ingest_metric`` helper Path A calls directly — proving the
    Protocol seam is the only difference and it is shape-preserving.
    """
    # Path A — direct: the route's pre-Phase-6.1 call shape.
    from storage.timescale.measurements import _ingest_metric

    direct_session = _RegistryFakeSession()
    samples = [
        {"date": "2026-05-11T08:00:00Z", "qty": 72, "source": "Apple Watch", "unit": "bpm"},
        {"date": "2026-05-11T08:01:00Z", "qty": 73, "source": "Apple Watch", "unit": "bpm"},
    ]
    direct_count = await _ingest_metric(direct_session, 1, "heart_rate", samples)

    # Path B — through the registry chain + Phase 6.1 Protocol seam:
    # discover → load entrypoint → instantiate via SDK → call .ingest()
    # with an IngestStorage instance that delegates to the same helper.
    found = discover()
    apple = next(p for p in found if p.plugin_id == "apple-health-healthsave")
    module_path, _, class_name = apple.manifest.entrypoint.partition(":")
    cls = getattr(importlib.import_module(module_path), class_name)
    plugin = cls(apple.manifest)

    plugin_session = _RegistryFakeSession()
    result = await plugin.ingest(
        {
            "storage": _RegistryRecordingStorage(),
            "session": plugin_session,
            "device_id": 1,
            "metric": "heart_rate",
            "samples": samples,
            "first_device_name": "Apple Watch",
        }
    )

    # Identity assertions: same row count, same SQL shapes.
    assert direct_count == result["accepted"]
    assert len(direct_session.calls) == len(plugin_session.calls)
    direct_sqls = [sql for sql, _ in direct_session.calls]
    plugin_sqls = [sql for sql, _ in plugin_session.calls]
    assert direct_sqls == plugin_sqls, (
        "registry path issued different SQL than the direct path — "
        "Phase 7 will inherit a Schrödinger SDK"
    )


@pytest.mark.asyncio
async def test_get_or_create_device_creates_atomically_when_absent():
    """A first-sighting device must be created with a single atomic upsert.

    Two concurrent batches can both miss the SELECT, so creation cannot be a
    bare INSERT — the loser would take a UniqueViolation and fail an otherwise
    valid batch (issue #28).
    """
    from types import SimpleNamespace

    from sqlalchemy.exc import IntegrityError
    from storage.timescale.measurements import _get_or_create_device

    class ConcurrentInsertSession:
        """Simulates a racing peer: the row is absent at SELECT, present at INSERT."""

        def __init__(self):
            self.calls = []

        async def execute(self, statement, params=None):
            sql = " ".join(str(statement).split())
            self.calls.append((sql, params or {}))

            if sql.startswith("SELECT id FROM devices"):
                return SimpleNamespace(first=lambda: None)

            if sql.startswith("INSERT INTO devices"):
                if "ON CONFLICT" not in sql:
                    raise IntegrityError(
                        sql,
                        params,
                        Exception(
                            "duplicate key value violates unique constraint "
                            '"devices_device_type_key"'
                        ),
                    )

                return SimpleNamespace(scalar=lambda: 42)

            raise AssertionError(f"unexpected SQL: {sql}")

    session = ConcurrentInsertSession()

    device_id = await _get_or_create_device(session, "Test Device")

    assert device_id == 42
    insert_sql, insert_params = session.calls[-1]
    assert "INSERT INTO devices" in insert_sql
    assert "ON CONFLICT (device_type)" in insert_sql
    assert "RETURNING id" in insert_sql
    assert insert_params == {"dt": "Test Device"}


@pytest.mark.asyncio
async def test_get_or_create_device_reads_without_writing_when_present():
    """The hot path must stay a lock-free read.

    ``INSERT ... ON CONFLICT DO UPDATE`` locks the devices row until COMMIT,
    and device resolution opens the ingest transaction that commits only after
    the whole batch lands. Upserting an already-known device would serialize
    every concurrent batch from that device behind the previous one.
    """
    from types import SimpleNamespace

    from storage.timescale.measurements import _get_or_create_device

    class ExistingDeviceSession:
        def __init__(self):
            self.calls = []

        async def execute(self, statement, params=None):
            sql = " ".join(str(statement).split())
            self.calls.append((sql, params or {}))

            if sql.startswith("SELECT id FROM devices"):
                return SimpleNamespace(first=lambda: (7,))

            raise AssertionError(f"known device must not issue writes, got: {sql}")

    session = ExistingDeviceSession()

    device_id = await _get_or_create_device(session, "Apple Watch Ultra")

    assert device_id == 7
    assert len(session.calls) == 1
    sql, params = session.calls[0]
    assert sql.startswith("SELECT id FROM devices")
    assert params == {"dt": "Apple Watch Ultra"}
