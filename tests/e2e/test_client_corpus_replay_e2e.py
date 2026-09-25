"""Every committed client request golden, replayed against real Postgres.

The contract suite replays the goldens through the route handlers with a
``FakeSession``, which cannot see what only the database enforces: unique
indexes, types, the legacy (time, device_id, owner_id) partial index. A
mixed-source heart-rate batch passed that replay while real Postgres rejected
it with a 422 (#39/#40). This test posts the exact bytes each shipped client
sends -- iOS v1, iOS v2, Android -- to the running stack, and checks that the
mixed-source golden lands each sample under its own source's device.

Idempotent on a dirty volume: goldens carry stable identities, so a re-run
upserts the same rows. Skipped unless ``E2E_BASE_URL`` + ``E2E_DATABASE_URL``
are set (``make e2e``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import asyncpg
import httpx
import pytest

BASE_URL = os.getenv("E2E_BASE_URL")
DATABASE_URL = os.getenv("E2E_DATABASE_URL")
API_KEY = os.getenv("E2E_API_KEY", "")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not BASE_URL or not DATABASE_URL,
        reason="set E2E_BASE_URL + E2E_DATABASE_URL to run e2e (see `make e2e`)",
    ),
]

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CORPORA = [
    ("apple_healthsave", "/api/apple/batch"),  # iOS, v1 wire (App Store builds <= 1.7.1)
    ("android_healthsave", "/api/apple/batch"),  # Android reuses the v1 route by design
    ("apple_healthsave_v2", "/api/v2/apple/batch"),  # iOS 1.7.2+
]
GOLDENS = [
    pytest.param(path, route, id=f"{corpus}/{path.name}")
    for corpus, route in CORPORA
    for path in sorted((FIXTURES / corpus).glob("*_batch.json"))
]


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def test_every_client_corpus_is_present() -> None:
    for corpus, _ in CORPORA:
        assert list((FIXTURES / corpus).glob("*_batch.json")), f"{corpus} corpus is empty"


@pytest.mark.parametrize(("path", "route"), GOLDENS)
def test_client_golden_is_accepted_by_real_storage(path: Path, route: str) -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        resp = client.post(
            route,
            content=path.read_bytes(),
            headers={
                **_headers(),
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code in (200, 201, 202), f"{resp.status_code} {resp.text[:400]}"
    assert resp.json().get("status") in ("processed", "empty"), resp.text[:400]


@pytest.mark.asyncio
async def test_mixed_source_golden_lands_each_sample_under_its_own_device() -> None:
    golden = FIXTURES / "apple_healthsave_v2" / "heart_rate_batch.json"
    samples = json.loads(golden.read_text())["samples"]
    assert len({s["source"] for s in samples}) > 1, "heart_rate golden must stay mixed-source"

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        resp = await client.post(
            "/api/v2/apple/batch",
            content=golden.read_bytes(),
            headers={**_headers(), "Content-Type": "application/json"},
        )
    assert resp.status_code in (200, 201, 202), f"{resp.status_code} {resp.text[:400]}"

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            """
            SELECT h.source_uuid::text AS uuid, d.device_type
            FROM heart_rate h
            JOIN devices d ON d.id = h.device_id
            WHERE h.source_uuid = ANY($1::uuid[]) AND h.status = 'active'
            """,
            [s["uuid"] for s in samples],
        )
    finally:
        await conn.close()

    stored = {row["uuid"].upper(): row["device_type"] for row in rows}
    assert stored == {s["uuid"].upper(): s["source"] for s in samples}


@pytest.mark.asyncio
async def test_heartbeat_series_golden_keeps_every_beat_in_postgres() -> None:
    """The beats are the point of ``heartbeat_series``: they must reach Postgres whole.

    There is no v1 table for the metric, so the receipt must still count every series as
    accepted, and the canonical row's JSONB must hold the beat list and the HRV link as sent.
    """
    golden = FIXTURES / "apple_healthsave_v2" / "heartbeat_series_batch.json"
    samples = json.loads(golden.read_text())["samples"]

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        resp = await client.post(
            "/api/v2/apple/batch",
            content=golden.read_bytes(),
            headers={**_headers(), "Content-Type": "application/json"},
        )
    assert resp.status_code in (200, 201, 202), f"{resp.status_code} {resp.text[:400]}"
    receipt = resp.json()
    assert receipt["records_accepted"] == len(samples), receipt
    assert receipt["records_rejected"] == 0, receipt

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            """
            SELECT source_record_uid, value_json
            FROM canonical_observations
            WHERE metric_id = 'vital.heartbeat_series'
              AND source_record_uid = ANY($1::text[])
              AND status = 'active'
            """,
            [s["uuid"] for s in samples],
        )
    finally:
        await conn.close()

    stored = {row["source_record_uid"]: json.loads(row["value_json"])["summary"] for row in rows}
    assert set(stored) == {s["uuid"] for s in samples}
    for sample in samples:
        summary = stored[sample["uuid"]]
        assert summary["heartbeats"] == sample["heartbeats"]
        assert summary.get("hrvUUID") == sample.get("hrvUUID")
