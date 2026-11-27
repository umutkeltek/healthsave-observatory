"""Workout elevation gain on a real stack: wire -> workouts table -> export.

The unit suite pins the writer's SQL against a recording session; only real
Postgres proves the upsert's COALESCE keeps a stored value when an older app
(or another source) re-sends the workout without one, and that migration 037's
column reaches ``/api/v2/export`` as a number or null.

Each run posts under its own source name, so it gets its own device row and
never collides with an earlier run on a dirty volume.

Skipped unless ``E2E_BASE_URL`` and ``E2E_DATABASE_URL`` are set (``make e2e``).
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import httpx
import pytest

BASE_URL = os.getenv("E2E_BASE_URL")
DATABASE_URL = os.getenv("E2E_DATABASE_URL")
API_KEY = os.getenv("E2E_API_KEY", "")
OWNER = "00000000-0000-0000-0000-000000000001"  # no X-User-Id -> the sentinel owner

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not BASE_URL or not DATABASE_URL,
        reason="set E2E_BASE_URL + E2E_DATABASE_URL to run e2e (see `make e2e`)",
    ),
]


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _workout(name: str, start: datetime, minutes: int, source: str, **extra) -> dict:
    return {
        "name": name,
        "start": _iso(start),
        "end": _iso(start + timedelta(minutes=minutes)),
        "duration": minutes * 60,
        "activeEnergy": 400,
        "distance": 5000,
        "source": source,
        **extra,
    }


def _v2_workout(name: str, start: datetime, minutes: int, source: str, **extra) -> dict:
    sample = _workout(name, start, minutes, source, **extra)
    sample.update(
        uuid=str(uuid4()).upper(),
        startDate=sample["start"],
        endDate=sample["end"],
        tzOffsetMinutes=0,
    )
    return sample


def _post_v1(client: httpx.Client, samples: list[dict]) -> dict:
    body = {"metric": "workouts", "batch_index": 0, "total_batches": 1, "samples": samples}
    resp = client.post("/api/apple/batch", json=body, headers=_headers())
    assert resp.status_code in (200, 201, 202), f"{resp.status_code} {resp.text[:400]}"
    return resp.json()


def _post_v2(client: httpx.Client, samples: list[dict]) -> dict:
    body = {
        "schema_version": 2,
        "metric": "workouts",
        "batch_index": 0,
        "total_batches": 1,
        "samples": samples,
        "source_bundle_id": "com.healthsave.ios",
        "device": {"name": "iPhone", "model": "e2e-host"},
    }
    resp = client.post("/api/v2/apple/batch", json=body, headers=_headers())
    assert resp.status_code in (200, 201, 202), f"{resp.status_code} {resp.text[:400]}"
    receipt = resp.json()
    assert receipt["status"] == "processed", receipt
    assert receipt["records_rejected"] == 0, receipt
    return receipt


async def _stored(source: str) -> dict[str, tuple[float | None, float | None]]:
    """start (ISO, UTC) -> (elevation_gain_m, calories) for this run's workouts."""

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            "SELECT start_time, elevation_gain_m, calories FROM workouts "
            "WHERE owner_id = $1 AND source_id = $2",
            OWNER,
            source,
        )
    finally:
        await conn.close()
    return {_iso(r["start_time"]): (r["elevation_gain_m"], r["calories"]) for r in rows}


async def _canonical_summary(source_record_uid: str) -> dict:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        value = await conn.fetchval(
            "SELECT value_json::text FROM canonical_observations "
            "WHERE owner_id = $1 AND source_record_uid = $2 AND metric_id = 'workout.session'",
            OWNER,
            source_record_uid,
        )
    finally:
        await conn.close()
    assert value is not None, f"no canonical workout.session for {source_record_uid}"
    return json.loads(value)["summary"]


def test_elevation_gain_is_stored_kept_on_resend_and_exported() -> None:
    source = f"e2e Elevation Watch {uuid4().hex[:8]}"
    day = (datetime.now(UTC) - timedelta(days=3)).replace(hour=6, minute=0, second=0, microsecond=0)
    hike, walk, swim = day, day + timedelta(hours=4), day + timedelta(hours=8)
    run, rowing = day + timedelta(hours=10), day + timedelta(hours=12)

    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        assert client.get("/ready").json().get("database") == "ok"

        # Frozen v1 route: a recorded ascent, a recorded flat 0, and none at all.
        _post_v1(
            client,
            [
                _workout("Hiking", hike, 150, source, elevationGain=412.6),
                _workout("Walking", walk, 30, source, elevationGain=0),
                _workout("Swimming", swim, 40, source),
            ],
        )
        stored = asyncio.run(_stored(source))
        assert stored[_iso(hike)] == (412.6, 400.0)
        assert stored[_iso(walk)][0] == 0.0
        assert stored[_iso(swim)][0] is None

        # An older app re-sends the hike without the field: the rest updates,
        # the stored ascent stays. A bad value later never erases it either.
        _post_v1(client, [_workout("Hiking", hike, 150, source, activeEnergy=830)])
        assert asyncio.run(_stored(source))[_iso(hike)] == (412.6, 830.0)
        _post_v1(client, [_workout("Hiking", hike, 150, source, elevationGain=-5)])
        assert asyncio.run(_stored(source))[_iso(hike)] == (412.6, 400.0)

        # v2 route: stored, and the canonical workout.session keeps it beside distance.
        good = _v2_workout("Running", run, 45, source, elevationGain=86.5)
        bad = _v2_workout("Rowing", rowing, 30, source, elevationGain="uphill")
        _post_v2(client, [good, bad])
        stored = asyncio.run(_stored(source))
        assert stored[_iso(run)][0] == 86.5
        assert stored[_iso(rowing)][0] is None
        summary = asyncio.run(_canonical_summary(good["uuid"]))
        assert (summary["distance"], summary["elevationGain"]) == (5000, 86.5)

        # Read side: every workout row carries elevation_gain_m, number or null.
        window = {"from": (day - timedelta(days=1)).date(), "to": (day + timedelta(days=1)).date()}
        params = {"metric": "workouts", **{k: v.isoformat() for k, v in window.items()}}
        exported = client.get("/api/v2/export", params=params, headers=_headers()).json()
        assert exported and all("elevation_gain_m" in row for row in exported)
        ours = {
            datetime.fromisoformat(row["start_time"]): row["elevation_gain_m"]
            for row in exported
            if row["source_id"] == source
        }
        assert ours == {hike: 412.6, walk: 0.0, swim: None, run: 86.5, rowing: None}

        text = client.get(
            "/api/v2/export", params={**params, "format": "csv"}, headers=_headers()
        ).text
        header = next(csv.reader(io.StringIO(text)))
        assert header.index("elevation_gain_m") == header.index("distance_m") + 1
