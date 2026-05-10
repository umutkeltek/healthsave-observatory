"""Apple Health (HealthSave bridge) — first first-party Source plugin.

The HealthSave iOS app (App Store ID 6759843047) calls
``POST /api/apple/batch`` with HealthKit-shaped payloads. The route
handler in ``apps/api/server/api/ingest.py`` already does the full
ingest work — payload validation, owner resolution, raw-payload
audit log, per-metric dispatch, observability counters.

The Phase 6 plugin model expresses the SAME work as a
:class:`plugin_sdk.Source` so that:

  * future Source plugins (Oura, Whoop, Garmin) ship in the same
    shape and the dashboard / runtime can list them uniformly
  * the route handler can eventually be migrated to invoke the
    plugin via the loader instead of calling the storage layer
    directly — removing the in-tree shortcut

This module is intentionally a THIN WRAPPER. It does NOT duplicate
ingest logic. ``ingest`` calls into ``server.ingestion.parsers`` and
``storage.timescale.measurements`` exactly as the route does, with
the same observability counters firing. Behavior is identical to
pre-Phase-6 — no wire-contract drift, no double-write risk, the
plugin is just an alternate front door to the existing pipeline.

The route handler still owns the HTTP surface (auth, response shape,
background tasks) and stays unchanged. Phase 7+ may move the route
to "delegate to the plugin loader" once a sandboxed loader exists.
"""

from __future__ import annotations

import logging
from typing import Any

from plugin_sdk import PluginManifest, Source
from server.ingestion.owner import DEFAULT_OWNER_ID
from server.ingestion.parsers import group_samples_by_device
from storage.timescale import measurements as measurements_sql

log = logging.getLogger("healthsave.plugins.apple_health_healthsave")


class AppleHealthSource(Source):
    """Source plugin that ingests HealthSave iOS batches.

    Inherits :class:`plugin_sdk.Source` and implements the single
    required method, :meth:`ingest`. Manifest is injected by the
    loader; this class does not need to know its own id.

    Concurrency note: ``ingest`` is async because it shares the same
    AsyncSession + asyncpg connection pool the route uses. Phase 7's
    loader injects the session per-call so the plugin stays
    transaction-aware without owning the pool.
    """

    def __init__(self, manifest: PluginManifest) -> None:
        super().__init__(manifest)

    async def ingest(self, payload: dict[str, Any]) -> dict[str, int]:
        """Ingest one HealthSave batch.

        ``payload`` MUST be the parsed BatchPayload-shaped dict — the
        same shape ``apps/api/server/api/ingest.py`` validates from
        ``await request.json()``. Returns
        ``{"accepted": N, "rejected": N}``; the route translates this
        into the {"records": N} field of its response (rejected is
        operator-side via the INGEST_REJECTED counter that
        storage.timescale.measurements bumps).

        Required keys in ``payload``:

          * ``session`` (the open AsyncSession)
          * ``device_id`` (int) — the resolved or freshly-created device
          * ``metric`` (str) — the HealthKit metric name
          * ``samples`` (list[dict])

        Optional:

          * ``owner_id`` (UUID) — defaults to DEFAULT_OWNER_ID
            (the single-user sentinel that v1 + v2 share)
        """
        session = payload["session"]
        device_id = payload["device_id"]
        metric = payload["metric"]
        samples = payload["samples"]
        owner_id = payload.get("owner_id", DEFAULT_OWNER_ID)

        if not samples:
            return {"accepted": 0, "rejected": 0}

        sample_groups = group_samples_by_device(samples)
        accepted = 0
        for device_name, device_samples in sample_groups:
            # The route already resolved the FIRST device in the batch.
            # For multi-device batches, defer to the same pattern.
            if device_name == payload.get("first_device_name"):
                resolved_device_id = device_id
            else:
                resolved_device_id = await measurements_sql._get_or_create_device(
                    session, device_name
                )
            accepted += await measurements_sql._ingest_metric(
                session, resolved_device_id, metric, device_samples, owner_id
            )

        # rejected counts are surfaced via the INGEST_REJECTED counter
        # inside measurements_sql; we cannot read those values back
        # without coupling to the registry. Returning 0 for rejected
        # here is correct — operators alert on the counter, not the
        # plugin return value.
        return {"accepted": accepted, "rejected": 0}
