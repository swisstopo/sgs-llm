"""Launch the installed server as a subprocess and verify the MCP stdio transport."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters, stdio_client

PROJECT_DIR = Path(__file__).resolve().parent.parent


async def smoke() -> dict[str, object]:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "swisstopo_mcp", "--transport", "stdio", "--log-level", "warning"],
        cwd=PROJECT_DIR,
    )
    async with Client(stdio_client(parameters), read_timeout_seconds=30) as client:
        tools = await client.list_tools()
        result = await client.call_tool(
            "search_divisions",
            {"query": "Geneve", "kinds": ["kanton"], "limit": 1},
        )
    assert isinstance(result.structured_content, dict)
    division = result.structured_content["divisions"][0]
    assert division["name"] == "Genève"
    return {
        "transport": "stdio",
        "tool_count": len(tools.tools),
        "tools": sorted(tool.name for tool in tools.tools),
        "division": {
            "name": division["name"],
            "kind": division["kind"],
            "canton": division["canton"],
        },
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(smoke()), indent=2, ensure_ascii=False))
