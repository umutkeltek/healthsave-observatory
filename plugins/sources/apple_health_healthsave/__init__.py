"""Apple Health (HealthSave bridge) — first first-party Source plugin.

The HealthSave iOS app calls
``POST /api/apple/batch`` with HealthKit-shaped payloads. As of
Phase 6.1 the route handler in ``apps/api/server/api/ingest.py``
delegates the per-device write loop to this plugin via the SDK
loader (``plugin_sdk.discover()`` → entrypoint resolve →
``plugin.ingest(...)``). The route still owns: payload validation,
owner-id resolution, audit log_raw, the empty-batch branch, the
``RAW_LOG_ORPHANED`` error boundary, and the response shape.

Phase 6.1 made the plugin **Protocol-aware**: the caller injects an
``IngestStorage`` Protocol instance via ``payload["storage"]`` and the
plugin routes every device + ingest call through it. This preserves
the Phase 5C backend-swap seam (Timescale → InfluxDB) — the plugin
does NOT import ``storage.timescale.measurements`` for writes. Source
and backend are orthogonal axes that compose, not subsume.

Lifecycle (Phase 7-C will wire the rest):

  * ``setup(config)``   — no-op for this plugin.
  * ``ingest(payload)`` — one batch in, ``{accepted, rejected}`` out.
  * ``shutdown()``      — no-op.

Phase 7+ will move audit + counter responsibilities into the loader.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from normalization.identity import resolve_apple_origin
from plugin_sdk import PluginManifest, Source
from server.ingestion.owner import DEFAULT_OWNER_ID
from server.ingestion.parsers import group_samples_by_device
from storage.results import IngestWriteResult, coerce_ingest_result

if TYPE_CHECKING:
    from contracts.observation import Observation
    from storage.ports import IngestStorage, MeasurementProjectionRepository

log = logging.getLogger("healthsave.plugins.apple_health_healthsave")


def _projection_reported_work(result: IngestWriteResult) -> bool:
    """True when the projection layer actually handled this batch.

    The projection only knows quantity observations; events (workouts),
    categorical records (sleep stages) and the rest come back as a bare
    ``IngestWriteResult()`` so the caller falls through to the raw writers
    that still own those shapes. That question must be asked of each
    projection result on its own: ``IngestWriteResult.combine`` folds an
    unset ``inserted_new`` (``None``) into ``0``, which then reads as
    "projected, wrote zero rows" and skips the fallback — which froze the
    v1 workouts and sleep tables for any batch that spanned two source
    devices while the canonical store stayed correct.
    """

    return bool(
        result.accepted
        or result.rejected
        or result.deduped_in_batch
        or result.inserted_new is not None
        or result.deduped_existing is not None
    )


class AppleHealthSource(Source):
    """Source plugin that ingests HealthSave iOS batches.

    Inherits :class:`plugin_sdk.Source` and implements the single
    required method, :meth:`ingest`. Manifest is injected by the
    loader; this class does not need to know its own id.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int | str | None]:
        """Ingest one HealthSave batch through the injected storage Protocol.

        ``payload`` MUST be the parsed BatchPayload-shaped dict — the
        same shape ``apps/api/server/api/ingest.py`` validates from
        ``await request.json()``. Returns
        ``{"accepted": N, "rejected": N, "deduped_in_batch": N, ...}``.
        ``rejected`` is the TRUE validation-failure count (missing/unparseable
        fields) reported by the storage writers via ``IngestWriteResult``;
        ``deduped_in_batch`` counts legitimate in-batch duplicate collapse
        (NOT a rejection). The ``INGEST_REJECTED`` Prometheus counter still
        fires per skip for operator alerting.

        Required keys in ``payload``:

          * ``storage`` (:class:`storage.ports.IngestStorage`) — Phase
            6.1 contract. The plugin dispatches every write through
            this Protocol instance. Tests inject a recording double;
            production injects ``PostgresIngestStorage``.
          * ``session`` — the open ``AsyncSession`` that the storage
            implementation expects (Postgres-typed in production).
          * ``device_id`` (int | str) — first-device id pre-resolved by
            the caller so the audit ``log_raw`` row gets the right
            device. Saves one ``get_or_create_device`` query per batch.
          * ``first_device_name`` (str) — name of that pre-resolved
            device. The plugin reuses ``device_id`` for matching
            ``device_name`` entries in ``sample_groups``.
          * ``metric`` (str) — the HealthKit metric name.
          * ``samples`` (list[dict]) — the parsed sample list.

        Optional:

          * ``canonical_observations`` (list[Observation]) — observations the
            route already normalized and wrote before invoking the projection
            path. Present for HealthSave Apple batches.
          * ``projection`` (:class:`storage.ports.MeasurementProjectionRepository`)
            — optional per-metric projection adapter. When supplied with
            canonical observations, the plugin projects from canonical truth
            instead of replaying raw samples.
          * ``owner_id`` (UUID) — defaults to ``DEFAULT_OWNER_ID``
            (the single-user sentinel that v1 + v2 share). The route
            resolves this from the ``X-User-Id`` header before calling
            the plugin, so production traffic always passes an explicit
            owner_id.
        """
        storage: IngestStorage = payload["storage"]
        projection: MeasurementProjectionRepository | None = payload.get("projection")
        canonical_observations: list[Observation] = payload.get("canonical_observations") or []
        session = payload["session"]
        device_id = payload["device_id"]
        first_device_name = payload.get("first_device_name")
        metric = payload["metric"]
        samples = payload["samples"]
        owner_id = payload.get("owner_id", DEFAULT_OWNER_ID)

        if not samples:
            return {"accepted": 0, "rejected": 0}

        sample_groups = group_samples_by_device(samples)

        if projection is not None and canonical_observations:
            # Preserve the existing fast path for ordinary single-device batches.
            if len(sample_groups) == 1:
                written = await projection.project_observations(
                    session, device_id, metric, canonical_observations, owner_id
                )
                projected = coerce_ingest_result(written)
                if _projection_reported_work(projected):
                    return projected.to_plugin_result()
            else:
                # Canonical observations carry per-sample stream identity, while
                # the legacy projection accepts one device_id per call. Match
                # each raw device group to its canonical stream and project it
                # under that group's resolved legacy device id.
                groups_by_stream = {}
                for device_name, device_samples in sample_groups:
                    stream_id = resolve_apple_origin(owner_id, device_name).stream_id
                    if stream_id in groups_by_stream:
                        # Distinct legacy device labels can normalize to the same
                        # canonical stream. In that ambiguous case, preserve the
                        # existing raw per-device path instead of guessing.
                        break
                    groups_by_stream[stream_id] = (device_name, device_samples)
                else:
                    observations_by_stream = {stream_id: [] for stream_id in groups_by_stream}
                    for observation in canonical_observations:
                        stream_id = getattr(observation, "stream_id", None)
                        if stream_id not in observations_by_stream:
                            break
                        observations_by_stream[stream_id].append(observation)
                    else:
                        projected_summary = IngestWriteResult()
                        projected_any = False
                        for stream_id, (device_name, _) in groups_by_stream.items():
                            device_observations = observations_by_stream[stream_id]
                            if not device_observations:
                                continue
                            resolved_device_id = (
                                device_id
                                if device_name == first_device_name
                                else await storage.get_or_create_device(session, device_name)
                            )
                            written = await projection.project_observations(
                                session,
                                resolved_device_id,
                                metric,
                                device_observations,
                                owner_id,
                            )
                            projected = coerce_ingest_result(written)
                            projected_any = projected_any or _projection_reported_work(projected)
                            projected_summary = projected_summary.combine(projected)

                        if projected_any:
                            return projected_summary.to_plugin_result()

        summary = IngestWriteResult()
        for device_name, device_samples in sample_groups:
            resolved_device_id = (
                device_id
                if device_name == first_device_name
                else await storage.get_or_create_device(session, device_name)
            )
            written = await storage.ingest_metric(
                session, resolved_device_id, metric, device_samples, owner_id
            )
            summary = summary.combine(coerce_ingest_result(written))

        return summary.to_plugin_result()
