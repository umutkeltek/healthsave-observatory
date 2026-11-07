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

    from scripts.seed_synthetic_year import seed

    owner = uuid.uuid4()
    label = f"e2e-mcp-{owner.hex[:8]}"
    ingest = asyncio.run(_mint(label, "ingest", owner))
    read = asyncio.run(_mint(label, "read", owner))
    summary = seed(BASE_URL, ingest)
    return read, summary


def test_how_did_i_sleep_this_year_through_a_real_mcp_client(synthetic_year) -> None:
    read_key, seeded = synthetic_year
    today = dt.datetime.now(dt.UTC).date()
    names, instructions, (sleep, year, overview, found) = asyncio.run(
        _ask(
            read_key,
            [
                ("sleep_summary", {"period": "this_year"}),
                ("year_in_health", {}),
                ("observatory_overview", {}),
                ("findings", {}),
            ],
        )
    )
    assert len(names) == 8 and "sleep_summary" in names
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
