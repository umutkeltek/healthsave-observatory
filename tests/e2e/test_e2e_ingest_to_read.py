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
