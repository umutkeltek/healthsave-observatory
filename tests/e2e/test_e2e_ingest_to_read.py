"""End-to-end: golden iOS batch -> live stack -> v1 + v2 read surfaces.

Black-box over HTTP against a *running* stack (compose or any deployment),
not mocks. Replays the frozen ``apple_healthsave`` golden corpus through
``POST /api/apple/batch`` exactly as the HealthSave iOS app would, then asserts
the data is visible on both the v1 status surface and the v2 canonical read
surface (readiness + metric series). This is the test that proves the whole
ingest -> dual-write -> canonical -> read path actually works together — the
gap unit tests (which mock the DB) cannot cover.

Skipped unless ``E2E_BASE_URL`` is set, so the default ``pytest`` run is
unaffected. Drive it with ``make e2e`` (boots the compose stack), or point
``E2E_BASE_URL`` at any reachable api.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

BASE_URL = os.getenv("E2E_BASE_URL")
API_KEY = os.getenv("E2E_API_KEY", "")
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "apple_healthsave"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not BASE_URL, reason="set E2E_BASE_URL to run e2e (see `make e2e`)"),
]

# Golden fixture -> the canonical v2 metric_id it must surface after ingest.
CASES = {
    "heart_rate_batch.json": "vital.heart_rate",
    "quantity_step_count_batch.json": "activity.steps",
    "sleep_analysis_batch.json": "sleep.stage",
}


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _post_fixture(client: httpx.Client, name: str) -> None:
    payload = json.loads((FIXTURES_DIR / name).read_text())
    resp = client.post("/api/apple/batch", json=payload, headers=_headers())
    assert resp.status_code in (200, 201, 202), f"{name}: {resp.status_code} {resp.text[:300]}"


def test_golden_batches_flow_v1_to_v2() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        # 0) stack is alive
        assert client.get("/ready").json().get("database") == "ok"

        # 1) ingest every golden batch the way the iOS app does
        for name in CASES:
            _post_fixture(client, name)

        # 2) v1 surface (frozen, iOS-facing): heart_rate landed
        status = client.get("/api/apple/status", headers=_headers()).json()
        assert "heart_rate" in status, (
            f"heart_rate absent from /api/apple/status: {list(status)[:10]}"
        )

        # 3) v2 canonical surface: dual-write reached the read API the dashboard uses
        readiness = client.get("/api/v2/readiness", headers=_headers()).json()
        assert readiness["summary"]["metrics_with_data"] >= 1
        metric_ids = {m["metric_id"] for m in readiness["metrics"]}
        assert "vital.heart_rate" in metric_ids, (
            f"canonical missing heart_rate: {sorted(metric_ids)}"
        )

        # 4) the metric series the dashboard charts actually returns points
        series = client.get(
            "/api/v2/metrics/vital.heart_rate/series",
            params={"range": "90d"},
            headers=_headers(),
        ).json()
        assert series["points"], "v2 heart_rate series came back empty after ingest"


def test_sync_coverage_closes_resend_loop_for_dedicated_and_rollup_metrics() -> None:
    """GH#14 end-to-end: metrics that land in dedicated tables or daily_activity
    columns (not the quantity_samples catch-all keyed by their own name) must show
    a destination row and report ``fresh`` on /api/v2/sync/coverage — otherwise the
    frozen client reads them as receipt_only/stale_payload and resends forever.

    Exercises the real Postgres path (destination_union + the day-grain GREATEST
    adjustment) that the mocked-DB unit tests cannot cover.
    """
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        assert client.get("/ready").json().get("database") == "ok"

        # Dedicated-table metrics that used to show zero destination rows.
        for name in ("body_temperature_batch.json", "medication_dose_event_batch.json"):
            _post_fixture(client, name)

        # A daily_activity rollup with a WITHIN-DAY sample: the destination is
        # stored at midnight, so before the fix this reported stale_payload
        # (midnight < within-day) and looped. The day-grain GREATEST adjustment
        # must surface the within-day sample instead.
        within_day_step = {
            "metric": "step_count",
            "batch_index": 0,
            "total_batches": 1,
            "samples": [{"date": "2026-04-11T17:38:00.000Z", "qty": 1234, "source": "Apple Watch"}],
        }
        resp = client.post("/api/apple/batch", json=within_day_step, headers=_headers())
        assert resp.status_code in (200, 201, 202), (
            f"step_count: {resp.status_code} {resp.text[:300]}"
        )

        coverage = client.get("/api/v2/sync/coverage", headers=_headers()).json()
        rows = {m["metric"]: m for m in coverage["metrics"]}

        for metric in ("step_count", "body_temperature", "medication_dose_event"):
            assert metric in rows, f"{metric} absent from coverage: {sorted(rows)}"
            row = rows[metric]
            # destination_row_count arrives as a string (Postgres sum() -> NUMERIC
            # -> JSON), so coerce before the numeric check.
            assert int(row["destination_row_count"]) >= 1, (
                f"{metric} shows 0 destination rows -> receipt_only resend loop"
            )
            assert row["latest_destination_sample_time"] is not None
            assert row["freshness_state"] == "fresh", (
                f"{metric} freshness={row['freshness_state']} (expected fresh; client would resend)"
            )

        # The day-grain adjustment must surface the within-day sample, not the
        # midnight rollup timestamp the client would otherwise read as "behind".
        step_dest = str(rows["step_count"]["latest_destination_sample_time"])
        assert step_dest >= "2026-04-11T17:38:00", (
            f"step_count destination still midnight-truncated: {step_dest}"
        )
