"""Connect an Agno agent to a running Swisstopo Search MCP HTTP endpoint."""

from __future__ import annotations

import asyncio
import os

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools


async def main() -> None:
    server_url = os.environ.get("SWISSTOPO_MCP_URL", "http://127.0.0.1:8791/mcp")
    async with MCPTools(transport="streamable-http", url=server_url) as tools:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-6"),
            tools=[tools],
            instructions=[
                "Use the Swisstopo tools for Swiss geodata facts.",
                "Keep dataset subjects separate from division names.",
            ],
            markdown=True,
        )
        await agent.aprint_response(
            "Find official avalanche datasets and resolve the canton of Valais.",
            stream=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
