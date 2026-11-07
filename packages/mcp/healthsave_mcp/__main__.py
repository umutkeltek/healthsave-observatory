"""``healthsave-mcp``: run the read server over stdio, or check it end to end.

    healthsave-mcp            serve over stdio (what an AI client starts)
    healthsave-mcp --check    start the server the way a client does, call one tool, report
    healthsave-mcp --version

Configuration comes from the environment: HEALTHSAVE_URL and HEALTHSAVE_API_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from . import __version__
from .client import ENV_KEY, ENV_URL, Config, ConfigError


def _serve(config: Config) -> int:
    from .server import build_server

    build_server(config).run("stdio")
    return 0


async def _check_async(config: Config) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {
        **{
            k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "SYSTEMROOT", "PYTHONPATH")
        },
        ENV_URL: config.url,
        ENV_KEY: config.api_key,
    }
    params = StdioServerParameters(command=sys.executable, args=["-m", "healthsave_mcp"], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        listed = await session.list_tools()
        names = sorted(tool.name for tool in listed.tools)
        writable = [
            tool.name
            for tool in listed.tools
            if not (tool.annotations and tool.annotations.readOnlyHint)
        ]
        result = await session.call_tool("observatory_overview", {})
        text = "".join(getattr(c, "text", "") for c in result.content)
        if result.isError:
            return {"ok": False, "error": text, "tools": names}
        body = json.loads(text)
        return {
            "ok": not writable,
            "server": f"{init.serverInfo.name} {init.serverInfo.version}",
            "tools": names,
            "not_read_only": writable,
            "last_reading_at": body.get("last_reading_at"),
            "kinds_of_data": body.get("kinds_of_data"),
            "can_read": body.get("can_read"),
        }


def _check(config: Config) -> int:
    try:
        report = asyncio.run(_check_async(config))
    except Exception as exc:  # noqa: BLE001 - a check reports any failure plainly
        print(f"[ERR] MCP check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not report["ok"]:
        print(f"[ERR] MCP check failed: {report.get('error') or report}", file=sys.stderr)
        return 1
    can = report.get("can_read") or {}
    readable = ", ".join(name for name, ok in can.items() if ok) or "nothing"
    print(
        f"[OK] MCP server answers: {len(report['tools'])} read-only tools; "
        f"observatory_overview read {report['kinds_of_data']} kinds of data, last reading "
        f"{report['last_reading_at'] or 'none yet'}; this key reads: {readable}."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="healthsave-mcp",
        description="Read-only MCP server for a HealthSave Observatory "
        f"(config: {ENV_URL}, {ENV_KEY}).",
    )
    parser.add_argument(
        "--check", action="store_true", help="start the server, call one tool, report"
    )
    parser.add_argument("--version", action="version", version=f"healthsave-mcp {__version__}")
    args = parser.parse_args(argv)
    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 2
    return _check(config) if args.check else _serve(config)


if __name__ == "__main__":
    sys.exit(main())
