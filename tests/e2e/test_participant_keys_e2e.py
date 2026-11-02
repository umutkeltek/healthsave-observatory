"""Participant keys on a real stack (migration 029).

Mints a participant ingest key straight into ``api_keys`` (only its SHA-256,
as ``healthsave participants add`` does), then posts the exact bytes every
shipped client sends -- iOS v1, iOS v2, Android -- with that key, and checks
on real Postgres that the rows carry the participant's owner, that
``/api/apple/status`` and ``/api/v2/sync/runs/latest`` answer for that owner,
that the key cannot read, that the admin can read it with ``?owner=``, and
that a revoked key is refused.

Idempotent on a dirty volume: every run mints a fresh label and owner.
Skipped unless ``E2E_BASE_URL`` + ``E2E_DATABASE_URL`` are set (``make e2e``).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
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
    ("apple_healthsave", "/api/apple/batch"),
    ("android_healthsave", "/api/apple/batch"),
    ("apple_healthsave_v2", "/api/v2/apple/batch"),
]


def _admin() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


@pytest.fixture(scope="module")
def participant():
    """A fresh participant: (key, owner_id, label, run_id)."""

    import asyncio

    key = secrets.token_hex(24)
    owner = uuid.uuid4()
    label = f"e2e-participant-{owner.hex[:8]}"

    async def _mint() -> None:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            await conn.execute(
                "INSERT INTO api_keys (key_hash, label, scope, owner_id) "
                "VALUES ($1, $2, 'ingest', $3)",
                hashlib.sha256(key.encode()).hexdigest(),
                label,
                owner,
            )
        finally:
            await conn.close()

    asyncio.run(_mint())
    return key, owner, label, f"participant-e2e-run-{owner.hex[:8]}"


async def _count(sql: str, *args) -> int:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        return int(await conn.fetchval(sql, *args))
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_participant_key_end_to_end(participant) -> None:
    key, owner, label, run_id = participant
    as_participant = {"X-API-Key": key}

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        index = 0
        for corpus, route in CORPORA:
            for path in sorted((FIXTURES / corpus).glob("*_batch.json")):
                metric = json.loads(path.read_text())["metric"]
                resp = await client.post(
                    route,
                    content=path.read_bytes(),
                    headers={
                        **as_participant,
                        "Content-Type": "application/json",
                        "X-HealthSave-Sync-Run-ID": run_id,
                        "X-HealthSave-Batch-ID": f"{run_id}-{index}",
                        "X-HealthSave-Metric": metric,
                    },
                )
                index += 1
                assert resp.status_code == 200, f"{path.name}: {resp.status_code} {resp.text[:300]}"
                assert resp.json()["status"] in ("processed", "empty"), resp.text[:300]

        # Rows landed under the participant's owner.
        assert (
            await _count("SELECT count(*) FROM canonical_observations WHERE owner_id = $1", owner)
            > 0
        )
        hr_rows = await _count("SELECT count(*) FROM heart_rate WHERE owner_id = $1", owner)
        assert hr_rows > 0
        assert (
            await _count(
                "SELECT count(*) FROM healthsave_sync_receipts "
                "WHERE sync_run_id = $1 AND owner_id <> $2",
                run_id,
                owner,
            )
            == 0
        )

        # /api/apple/status: same shape as the admin's, counts for the participant.
        mine = (await client.get("/api/apple/status", headers=as_participant)).json()
        admin = (await client.get("/api/apple/status", headers=_admin())).json()
        assert set(mine) == set(admin)
        assert set(mine["heart_rate"]) == {"count", "oldest", "newest"}
        active_hr = await _count(
            "SELECT count(*) FROM heart_rate WHERE owner_id = $1 AND status = 'active'", owner
        )
        assert mine["heart_rate"]["count"] == active_hr

        # The phone's own latest run, never someone else's.
        latest = (await client.get("/api/v2/sync/runs/latest", headers=as_participant)).json()
        assert latest["sync_run_id"] == run_id
        admin_latest = (await client.get("/api/v2/sync/runs/latest", headers=_admin())).json()
        assert admin_latest.get("sync_run_id") != run_id

        # An ingest key cannot read; the admin reads the participant with ?owner=.
        assert (await client.get("/api/v2/readiness", headers=as_participant)).status_code == 403
        assert (await client.get("/api/v2/owners", headers=as_participant)).status_code == 403
        readiness = await client.get(f"/api/v2/readiness?owner={owner}", headers=_admin())
        assert readiness.status_code == 200
        assert readiness.json()["metrics"], "admin ?owner= read returned no coverage"
        owners = (await client.get("/api/v2/owners", headers=_admin())).json()["owners"]
        assert owners[0]["is_default"] is True
        entry = next(o for o in owners if o["id"] == str(owner))
        assert entry["label"] == label and entry["active"] is True
        assert entry["last_ingest_at"] is not None

    # Revoked: refused in every auth mode, and it never falls back to the primary person.
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("UPDATE api_keys SET revoked_at = NOW() WHERE owner_id = $1", owner)
    finally:
        await conn.close()
    golden = FIXTURES / "apple_healthsave_v2" / "heart_rate_batch.json"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        resp = await client.post(
            "/api/v2/apple/batch",
            content=golden.read_bytes(),
            headers={**as_participant, "Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "api_key_revoked"
        owners = (await client.get("/api/v2/owners", headers=_admin())).json()["owners"]
        assert next(o for o in owners if o["id"] == str(owner))["active"] is False
