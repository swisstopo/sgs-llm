"""Verify an Agno MCPTools client can discover and call the HTTP server.

As of 2026-08-21, Agno 2.9.0 imports the MCP 1.x Python API. Run this script in a
separate client environment containing ``agno==2.9.0`` and ``mcp<2``; the server itself
continues to use MCP 2.0 and serves legacy clients on the same protocol endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from agno.tools.mcp import MCPTools


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test the MCP through Agno.")
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8791/mcp")
    return parser


async def smoke(url: str) -> dict[str, Any]:
    async with MCPTools(transport="streamable-http", url=url) as toolkit:
        functions = toolkit.get_async_functions()
        expected = {
            "search_datasets",
            "describe_dataset",
            "search_divisions",
            "create_map_preview",
            "geocode_location",
            "identify_at_point",
            "explain_swisstopo",
        }
        assert set(functions) == expected
        entrypoint = functions["search_divisions"].entrypoint
        assert entrypoint is not None
        result = await entrypoint(query="Wallis", kinds=["kanton"], limit=1)
        content = json.loads(result.content)
        division = content["divisions"][0]
        assert division["name"] == "Valais"
        return {
            "client": "agno",
            "transport": "streamable-http",
            "endpoint": url,
            "tools": sorted(functions),
            "division": {
                "name": division["name"],
                "kind": division["kind"],
                "canton": division["canton"],
            },
        }


if __name__ == "__main__":
    arguments = _parser().parse_args()
    print(json.dumps(asyncio.run(smoke(arguments.url)), indent=2, ensure_ascii=False))
