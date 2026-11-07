"""MCP surface: eight read-only tools over the Observatory read API.

No ``from __future__ import annotations`` here: FastMCP (1.12) inspects the
tool parameters' annotations as real objects to build their schemas.
"""

from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import tools
from .client import Config, ObservatoryClient, ObservatoryError

SERVER_NAME = "healthsave"

INSTRUCTIONS = """\
These tools read one person's health record from their own HealthSave Observatory, a server
they run themselves. The record holds readings from their phone, watch, ring and scale, blood
test results they imported, and findings from the Observatory's statistical engine.

Use them to answer questions like "how did I sleep this year", "how active was I last month",
"what changed recently" or "what do my iron results say".

- observatory_overview: what the record holds, which devices, last sync. Start here if unsure.
- today_vs_usual: today's readings against the person's own last 28 days.
- sleep_summary / activity_summary: nights or days over a period, with monthly rows for long
  periods.
- metric_trend: one kind of data (any metric id from the overview) over a period.
- findings: what the statistical engine found (anomalies, trends, correlations, recovery).
- lab_results: blood test results against each lab's own reference range.
- year_in_health: a calendar year's coverage, gaps, devices and headline numbers.

Every number comes with its unit and its source. When a result lists `limitations`, tell the
person about the ones that matter for their question. The tools describe; they do not
diagnose. Do not give medical advice; suggest a clinician for anything that worries the person.
All tools are read-only. They cannot change the record.
"""

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

SleepPeriod = Literal[
    "last_night",
    "last_7_nights",
    "last_30_nights",
    "last_90_nights",
    "last_365_nights",
    "this_year",
]
DayPeriod = Literal[
    "today", "last_7_days", "last_30_days", "last_90_days", "last_365_days", "this_year"
]


def build_server(
    config: Config,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: tools.Clock | None = None,
) -> FastMCP:
    """The MCP server for one Observatory. ``transport``/``clock`` are for tests."""

    server = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)
    holder: dict[str, ObservatoryClient] = {}

    def client() -> ObservatoryClient:
        # Created on first use, inside the server's event loop.
        if "client" not in holder:
            holder["client"] = ObservatoryClient(config, transport=transport)
        return holder["client"]

    async def run(call) -> dict[str, Any]:
        try:
            return await call
        except ObservatoryError as exc:
            raise ToolError(f"{exc.code}: {exc}") from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        title="Observatory overview",
        description="What this health record holds: kinds of data with days recorded, devices, "
        "last reading and last sync, and what this key may read.",
        annotations=READ_ONLY,
    )
    async def observatory_overview() -> dict[str, Any]:
        return await run(tools.observatory_overview(client(), clock=clock))

    @server.tool(
        title="Today against your usual",
        description="Today's readings (resting heart rate, HRV, respiratory rate, blood oxygen, "
        "wrist temperature, weight), today's activity so far and last night's sleep, each "
        "against the same source's previous 28 days. Includes the engine's recovery score when "
        "the key may read findings.",
        annotations=READ_ONLY,
    )
    async def today_vs_usual() -> dict[str, Any]:
        return await run(tools.today_vs_usual(client(), clock=clock))

    @server.tool(
        title="Sleep",
        description="Nights over a period: hours asleep, bedtime, wake time, stages, nights "
        "without data, and monthly rows for long periods. Use period='this_year' for "
        "'how did I sleep this year'.",
        annotations=READ_ONLY,
    )
    async def sleep_summary(period: SleepPeriod = "last_30_nights") -> dict[str, Any]:
        return await run(tools.sleep_summary(client(), period, clock=clock))

    @server.tool(
        title="Activity",
        description="Daily steps, active energy, exercise minutes and walking/running distance "
        "over a period: per-day averages, totals, best day, monthly rows for long periods.",
        annotations=READ_ONLY,
    )
    async def activity_summary(period: DayPeriod = "last_30_days") -> dict[str, Any]:
        return await run(tools.activity_summary(client(), period, clock=clock))

    @server.tool(
        title="One metric over time",
        description="One kind of data over a period, one value per day (or per month for long "
        "periods), from one source; other sources are named, never mixed in. metric_id is a "
        "canonical id such as vital.resting_heart_rate, vital.hrv_sdnn, body.weight or "
        "activity.steps (observatory_overview lists what this record holds).",
        annotations=READ_ONLY,
    )
    async def metric_trend(metric_id: str, period: DayPeriod = "last_90_days") -> dict[str, Any]:
        return await run(tools.metric_trend(client(), metric_id, period, clock=clock))

    @server.tool(
        title="Findings",
        description="Findings from the Observatory's statistical engine (anomalies, trends, "
        "recovery, correlations), newest first. kind filters by finding type, for example "
        "'anomaly' or 'recovery_score'. At most 25.",
        annotations=READ_ONLY,
    )
    async def findings(kind: str | None = None, limit: int = 10) -> dict[str, Any]:
        return await run(tools.findings(client(), kind, limit, clock=clock))

    @server.tool(
        title="Blood test results",
        description="Imported blood test results: each marker's latest result against its own "
        "lab's reference range, and the change from the previous result. Pass a LOINC code "
        "(for example 2276-4 for ferritin) for one marker's history and its wearable "
        "cross-match.",
        annotations=READ_ONLY,
    )
    async def lab_results(loinc: str | None = None) -> dict[str, Any]:
        return await run(tools.lab_results(client(), loinc, clock=clock))

    @server.tool(
        title="Year in Health",
        description="One calendar year of the record: days with data per month, every gap, "
        "kinds of data, devices that started or stopped, and headline numbers per source.",
        annotations=READ_ONLY,
    )
    async def year_in_health(year: int | None = None) -> dict[str, Any]:
        return await run(tools.year_in_health(client(), year, clock=clock))

    return server
