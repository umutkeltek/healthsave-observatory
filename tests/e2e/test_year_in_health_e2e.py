"""End-to-end: v1 batches for one past year -> live stack -> ``/api/v2/year/{year}``.

Proves the year view's real SQL (analytical-day bucketing, per-stream
observation bounds) against TimescaleDB, which the route tests fake. Uses
2019 and its own device names, so it cannot collide with the 2026 golden
fixtures other e2e tests replay into the same stack.

Skipped unless ``E2E_BASE_URL`` is set (``make e2e``).
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import httpx
import pytest

BASE_URL = os.getenv("E2E_BASE_URL")
API_KEY = os.getenv("E2E_API_KEY", "")
YEAR = 2019
WATCH = "Year E2E Watch"
RING = "Year E2E Ring"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not BASE_URL, reason="set E2E_BASE_URL to run e2e (see `make e2e`)"),
]


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _in_gap(day: date) -> bool:
    return date(YEAR, 8, 3) <= day <= date(YEAR, 8, 11)


def _sample(day: date, qty: float, source: str, hour: int = 6) -> dict:
    return {"date": f"{day.isoformat()}T{hour:02d}:00:00.000Z", "qty": qty, "source": source}


def _post(client: httpx.Client, metric: str, samples: list[dict]) -> None:
    chunks = [samples[i : i + 400] for i in range(0, len(samples), 400)]
    for index, chunk in enumerate(chunks):
        body = {
            "metric": metric,
            "batch_index": index,
            "total_batches": len(chunks),
            "samples": chunk,
        }
        response = client.post("/api/apple/batch", json=body, headers=_headers())
        assert response.status_code in (200, 201, 202), response.text[:300]


def test_year_reads_months_gaps_device_changes_and_per_source_numbers() -> None:
    # The watch records Jan 1 - Jun 30 and then stops; the ring arrives on
    # Apr 10. Nobody records Aug 3 - Aug 11.
    watch = [
        _sample(day, 56 + (i % 3 - 1), WATCH)
        for i, day in enumerate(_days(date(YEAR, 1, 1), date(YEAR, 6, 30)))
    ]
    ring = [
        _sample(day, 50 + (i % 3 - 1), RING, hour=7)
        for i, day in enumerate(_days(date(YEAR, 4, 10), date(YEAR, 12, 31)))
        if not _in_gap(day)
    ]
    # The phone's daily step totals (HealthKit statistics, stored as an
    # all-source day total at local midnight): each must land on its own day,
    # not on the day before the 04:00 boundary.
    steps = [
        {
            "date": f"{day.isoformat()}T00:00:00.000Z",
            "qty": 8000 + i,
            "source": "HealthKit Statistics",
        }
        for i, day in enumerate(_days(date(YEAR, 3, 1), date(YEAR, 3, 3)))
    ]
    with httpx.Client(base_url=BASE_URL, timeout=60) as client:
        assert client.get("/ready").json().get("database") == "ok"
        _post(client, "resting_heart_rate", watch + ring)
        _post(client, "step_count", steps)

        response = client.get(f"/api/v2/year/{YEAR}", headers=_headers())
        assert response.status_code == 200, response.text[:500]
        body = response.json()

    assert (body["window_start"], body["window_end"]) == (f"{YEAR}-01-01", f"{YEAR}-12-31")
    assert body["days_in_window"] == 365
    heart = next(f for f in body["families"] if f["id"] == "heart")
    assert {"start": f"{YEAR}-08-03", "end": f"{YEAR}-08-11", "days": 9, "kind": "inside"} in heart[
        "gaps"
    ]
    assert sum(g["days"] for g in heart["gaps"]) == heart["days_without_data"]
    assert heart["mask"].count("0") == heart["days_without_data"]

    activity = next(f for f in body["families"] if f["id"] == "activity")
    assert (activity["first_day"], activity["last_day"]) == (f"{YEAR}-03-01", f"{YEAR}-03-03")
    assert activity["days_with_data"] == 3

    sources = {s["label"]: s for s in body["sources"]}
    assert sources[WATCH]["first_day"] == f"{YEAR}-01-01"
    assert sources[WATCH]["last_day"] == f"{YEAR}-06-30"
    assert sources[WATCH]["stopped_this_year"] is True
    assert sources[RING]["first_day"] == f"{YEAR}-04-10"
    assert sources[RING]["new_this_year"] is True
    changes = {(c["label"], c["kind"], c["day"]) for c in body["device_changes"]}
    assert (RING, "first_seen", f"{YEAR}-04-10") in changes
    assert (WATCH, "last_seen", f"{YEAR}-06-30") in changes
    april = body["months"][3]
    assert sources[RING]["stream_id"] in april["first_seen_ids"]
    assert {sources[WATCH]["stream_id"], sources[RING]["stream_id"]} <= set(april["source_ids"])

    rhr = {
        h["source_label"]: h["value"] for h in body["headlines"] if h["id"] == "resting_heart_rate"
    }
    assert rhr[WATCH] == 56.0
    assert rhr[RING] == 50.0


def test_a_year_that_has_not_started_is_422() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        response = client.get("/api/v2/year/2199", headers=_headers())
    assert response.status_code == 422
