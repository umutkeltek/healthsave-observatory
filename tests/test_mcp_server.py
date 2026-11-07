"""MCP read server through the protocol: a real MCP client session, in memory.

What an AI client sees: eight tools, every one marked read-only, typed
periods, JSON results, and errors it can explain.
"""

from __future__ import annotations

import json

import httpx
from healthsave_mcp import __version__
from healthsave_mcp.client import Config
from healthsave_mcp.server import INSTRUCTIONS, build_server
from mcp.shared.memory import create_connected_server_and_client_session

from scripts.release_notes import pyproject_version
from tests.test_mcp_tools import CLOCK, FakeObservatory

TOOLS = {
    "observatory_overview",
    "today_vs_usual",
    "sleep_summary",
    "activity_summary",
    "metric_trend",
    "findings",
    "lab_results",
    "year_in_health",
}


def _server(fake: FakeObservatory | None = None, handler=None):
    transport = httpx.MockTransport(handler or (fake or FakeObservatory()).handler)
    server = build_server(Config("http://obs.test:8000", "k"), transport=transport, clock=CLOCK)
    return server._mcp_server


def _json(result) -> dict:
    return json.loads("".join(getattr(c, "text", "") for c in result.content))


async def test_eight_read_only_tools_and_nothing_else() -> None:
    async with create_connected_server_and_client_session(_server()) as session:
        listed = await session.list_tools()
    assert {tool.name for tool in listed.tools} == TOOLS
    for tool in listed.tools:
        a = tool.annotations
        assert a is not None, tool.name
        assert (a.readOnlyHint, a.destructiveHint, a.idempotentHint, a.openWorldHint) == (
            True,
            False,
            True,
            False,
        ), tool.name
        assert tool.description and len(tool.description) > 40
    sleep = next(t for t in listed.tools if t.name == "sleep_summary")
    assert "this_year" in json.dumps(sleep.inputSchema)


async def test_how_did_i_sleep_this_year_through_the_protocol() -> None:
    fake = FakeObservatory()
    async with create_connected_server_and_client_session(_server(fake)) as session:
        init = await session.list_tools()
        assert init.tools
        result = await session.call_tool("sleep_summary", {"period": "this_year"})
    assert not result.isError
    body = _json(result)
    assert body["tool"] == "sleep_summary" and body["summary"]["nights"] > 290
    assert body["nights_without_data"]["runs"][0]["from"] == "2026-08-03"
    assert all(r.method == "GET" for r in fake.requests)


async def test_a_bad_argument_is_an_error_result_not_a_crash() -> None:
    async with create_connected_server_and_client_session(_server()) as session:
        result = await session.call_tool("sleep_summary", {"period": "forever"})
        assert result.isError
        result = await session.call_tool("metric_trend", {"metric_id": "vital.hrv"})
        assert result.isError and "did you mean" in result.content[0].text


async def test_an_unreachable_observatory_is_explained() -> None:
    def down(request):
        raise httpx.ConnectError("refused")

    async with create_connected_server_and_client_session(_server(handler=down)) as session:
        result = await session.call_tool("observatory_overview", {})
    assert result.isError
    assert "unreachable: Could not reach the Observatory" in result.content[0].text


async def test_a_narrow_key_is_a_limitation_not_an_error() -> None:
    fake = FakeObservatory(deny=("/api/v2/insights",))
    async with create_connected_server_and_client_session(_server(fake)) as session:
        result = await session.call_tool("findings", {})
    assert not result.isError
    assert _json(result)["limitations"][0]["code"] == "key_scope"


async def test_the_server_tells_the_client_what_it_is_and_is_not() -> None:
    async with create_connected_server_and_client_session(_server()) as session:
        # The session fixture already initialized; the instructions are the server's.
        assert session is not None
    flat = " ".join(INSTRUCTIONS.split())
    assert "read-only" in flat and "they do not diagnose" in flat
    assert "medical advice" in flat
    assert __version__ == pyproject_version()  # ships in the release it says
