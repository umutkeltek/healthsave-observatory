"""End to end: synthetic year -> live stack -> MCP server over stdio -> real MCP client.

The question a person asks their AI, "how did I sleep this year", answered the
way an AI client answers it: start ``healthsave-mcp`` as a subprocess, speak
MCP to it over stdin/stdout, call ``sleep_summary(period="this_year")``.

The year is seeded under a fresh participant (ingest key), and read back with
that participant's read key, so it never mixes with the golden fixtures other
e2e tests replay as the default owner. A second key, the primary person's own
read key (``healthsave mcp key``), proves findings and lab results open to it
on the real app while the participant's read key is refused.

Skipped unless ``E2E_BASE_URL`` and ``E2E_DATABASE_URL`` are set (``make e2e``).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import secrets
import sys
import uuid
from pathlib import Path

import pytest

BASE_URL = os.getenv("E2E_BASE_URL")
DATABASE_URL = os.getenv("E2E_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OWNER = uuid.UUID("00000000-0000-0000-0000-000000000001")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not BASE_URL or not DATABASE_URL,
        reason="set E2E_BASE_URL + E2E_DATABASE_URL to run e2e (see `make e2e`)",
    ),
]


async def _mint(label: str, scope: str, owner: uuid.UUID) -> str:
    import asyncpg

    key = secrets.token_hex(24)
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "INSERT INTO api_keys (key_hash, label, scope, owner_id) VALUES ($1, $2, $3, $4)",
            hashlib.sha256(key.encode()).hexdigest(),
            label,
            scope,
            owner,
        )
    finally:
        await conn.close()
    return key


async def _ask(key: str, calls: list[tuple[str, dict]]) -> tuple[list[str], str, list[dict]]:
    """Start the server over stdio as an AI client does; list tools; call each."""

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT / "packages" / "mcp"),
        "HEALTHSAVE_URL": BASE_URL or "",
        "HEALTHSAVE_API_KEY": key,
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "healthsave_mcp"], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        listed = await session.list_tools()
        results = []
        for name, arguments in calls:
            result = await session.call_tool(name, arguments)
            text = "".join(getattr(c, "text", "") for c in result.content)
            assert not result.isError, f"{name}: {text}"
            results.append(json.loads(text))
    return sorted(t.name for t in listed.tools), init.instructions or "", results


@pytest.fixture(scope="module")
def synthetic_year():
    """A fresh participant with the synthetic year: (read key, seed summary)."""

    from scripts.seed_synthetic_year import post, seed

    owner = uuid.uuid4()
    label = f"e2e-mcp-{owner.hex[:8]}"
    ingest = asyncio.run(_mint(label, "ingest", owner))
    read = asyncio.run(_mint(label, "read", owner))
    summary = seed(BASE_URL, ingest)
    # Two workouts the way the phone sends them, for the workouts tool.
    post(BASE_URL, ingest, "workouts", _phone_workouts())
    return read, summary


def _phone_workouts() -> list[dict]:
    """Yesterday's run and hike, in the iOS app's batch shape."""

    day = dt.datetime.now(dt.UTC).replace(hour=7, minute=0, second=0, microsecond=0)
    day -= dt.timedelta(days=1)

    def sample(name: str, start: dt.datetime, minutes: int, **extra) -> dict:
        return {
            "name": name,
            "start": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "end": (start + dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "duration": minutes * 60,
            "source": "Apple Watch",
            **extra,
        }

    return [
        sample(
            "Running",
            day,
            45,
            activeEnergy=410,
            distance=7200,
            elevationGain=86.5,  # iPhone app 1.9.4+; an older server ignores it
            avgHeartRate=142,
            maxHeartRate=176,
        ),
        sample("Hiking", day + dt.timedelta(hours=9), 62, activeEnergy=388),
    ]


def _export_has_elevation(read_key: str) -> bool:
    """Whether this server's workouts export carries the elevation_gain_m column."""

    import httpx

    day = dt.datetime.now(dt.UTC).date()
    rows = httpx.get(
        f"{BASE_URL}/api/v2/export",
        params={"metric": "workouts", "from": (day - dt.timedelta(days=3)).isoformat()},
        headers={"X-API-Key": read_key},
        timeout=30,
    ).json()
    assert rows, "the seeded workouts are missing from the export"
    return "elevation_gain_m" in rows[0]


def test_how_did_i_sleep_this_year_through_a_real_mcp_client(synthetic_year) -> None:
    read_key, seeded = synthetic_year
    today = dt.datetime.now(dt.UTC).date()
    names, instructions, (sleep, year, overview, found, sessions) = asyncio.run(
        _ask(
            read_key,
            [
                ("sleep_summary", {"period": "this_year"}),
                ("year_in_health", {}),
                ("observatory_overview", {}),
                ("findings", {}),
                ("workouts", {"period": "last_7_days"}),
            ],
        )
    )
    assert len(names) == 9 and {"sleep_summary", "workouts"} <= set(names)
    assert "read-only" in instructions

    # Every seeded night comes back, counted the way the web counts it.
    codes = {lim["code"] for lim in sleep["limitations"]}
    expected = [n for n in seeded["nights"] if n < today.isoformat()]
    cut = next((lim for lim in sleep["limitations"] if lim["code"] == "window_cut"), None)
    if cut is not None:  # late in December a year of stages passes the 5,000 cap
        kept_from = cut["detail"].split(" before ")[1][:10]
        expected = [n for n in expected if n >= kept_from]
    assert sleep["summary"]["nights"] == len(expected), sleep["summary"]
    assert 6.0 <= sleep["summary"]["asleep_h"]["median"] <= 7.6
    assert sleep["summary"]["typical_bedtime"].startswith(("22:", "23:"))
    assert "time_basis_utc" in codes  # a participant read key cannot read the time setting
    off_from, off_to = seeded["nothing_recorded"]
    if today.isoformat() > off_to and cut is None:
        runs = sleep["nights_without_data"]["runs"]
        assert {"from": off_from, "to": off_to, "days": 9} in runs
    if len(expected) > 45:
        assert sleep["months"][0]["month"] == f"{seeded['year']}-01"
    assert "interval_end" not in json.dumps(sleep)  # summaries, never raw readings

    # The year view through MCP: the same gap, the ring arriving in April.
    assert year["year"] == seeded["year"]
    if today.isoformat() > off_to:
        # The night of the 2nd runs into the 3rd, so the year's gap may start a day late.
        assert any(
            off_from <= g["start"] <= g["end"] <= off_to and g["days"] >= 7 for g in year["gaps"]
        ), year["gaps"]
    assert any(c["device"] == "Oura Ring" for c in year["device_changes"])

    # Phone batch -> workouts table -> export -> one record per workout, with the
    # participant's own read key (the export is one of the routes it may read).
    assert sessions["count"] == 2, sessions
    run, hike = sessions["workouts"]
    assert (run["type"], run["duration_min"], run["source"]) == ("Running", 45.0, "Apple Watch")
    assert (run["active_energy_kcal"], run["distance_km"]) == (410, 7.2)
    assert (run["avg_heart_rate_bpm"], run["max_heart_rate_bpm"]) == (142, 176)
    assert run["start"].endswith("T07:00+00:00")  # this key reads in UTC
    assert hike["type"] == "Hiking" and "distance_km" not in hike
    # Elevation gain: from a server that stores it (1.5.0+), on the run that
    # recorded one; a 1.4.0 server has no such column and the tool leaves it out.
    if _export_has_elevation(read_key):
        assert run["elevation_gain_m"] == 86 and "elevation_gain_m" not in hike
    else:
        assert "elevation_gain_m" not in run and "elevation_gain_m" not in hike
    assert sessions["sources"][0]["types"] == {"Running": 1, "Hiking": 1}

    # A participant's read key is told what it cannot read, not given it.
    assert overview["can_read"] == {"readings": True, "findings": False, "lab_results": False}
    assert found["findings"] == [] and found["limitations"][0]["code"] == "key_scope"


def test_the_primary_persons_own_read_key_reads_findings_and_labs() -> None:
    key = asyncio.run(_mint(f"e2e-mcp-primary-{uuid.uuid4().hex[:8]}", "read", DEFAULT_OWNER))
    _, _, (overview, labs) = asyncio.run(
        _ask(key, [("observatory_overview", {}), ("lab_results", {})])
    )
    assert overview["can_read"] == {"readings": True, "findings": True, "lab_results": True}
    assert not any(lim["code"] == "key_scope" for lim in labs["limitations"])


def test_a_participant_named_like_the_primary_read_key_never_gets_the_primary_owner() -> None:
    """Real SQL: the label lookup must not hand a participant the default owner."""

    from sqlalchemy.ext.asyncio import create_async_engine
    from storage.timescale.api_keys import create_api_key, hash_api_key

    label = f"MCP read key e2e {uuid.uuid4().hex[:8]}"

    async def run() -> tuple[uuid.UUID, uuid.UUID]:
        engine = create_async_engine(DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://"))
        try:
            async with engine.connect() as conn:
                from sqlalchemy.ext.asyncio import AsyncSession

                async with AsyncSession(bind=conn) as session:
                    primary = await create_api_key(
                        session,
                        label=label,
                        scope="read",
                        key_hash=hash_api_key(secrets.token_hex(24)),
                        primary=True,
                    )
                    phone = await create_api_key(
                        session,
                        label=label.lower(),
                        scope="ingest",
                        key_hash=hash_api_key(secrets.token_hex(24)),
                    )
                    await session.commit()
                    return primary.owner_id, phone.owner_id
        finally:
            await engine.dispose()

    primary_owner, phone_owner = asyncio.run(run())
    assert primary_owner == DEFAULT_OWNER
    assert phone_owner != DEFAULT_OWNER
