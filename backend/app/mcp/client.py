"""The MCP client side of the backend (docs/architecture.md#mcp-client-interface).

One session per turn, so several tool calls share one `initialize` and nothing stale has
to be reconnected between turns. An unreachable server yields no tools rather than
failing the turn.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from .schema import to_tool_spec

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 24_000

# A cursor loop needs a bound; a real catalogue is a handful of tools.
MAX_TOOL_PAGES = 20


def _has_cancellation(exc: BaseException) -> bool:
    """Whether a failure is (or wraps) a cancellation.

    anyio reports transport failures as an ExceptionGroup, so the broad handlers
    below must catch groups - but a cancelled turn arrives the same way, and
    swallowing it would leave a cancelled exchange running to completion.
    """
    if isinstance(exc, asyncio.CancelledError):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_has_cancellation(inner) for inner in exc.exceptions)
    return False


def _semantic_error(data: Any) -> str | None:
    """Return a tool-declared failure without treating nested data fields as errors."""
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if not isinstance(error, str):
        return None
    cleaned = error.strip()
    return cleaned or None


@dataclass
class ToolOutcome:
    """One tool call's result, in the two shapes the caller needs."""

    # What is fed back to the model.
    text: str
    # Parsed JSON, when the tool returned any - used to build LayerSpecs.
    data: Any | None
    is_error: bool


class ToolSession:
    """Tools available for one turn, and the means to call them."""

    def __init__(self, session: Any, tool_specs: list[dict[str, Any]]) -> None:
        self._session = session
        self._tool_specs = tool_specs

    @property
    def tool_specs(self) -> list[dict[str, Any]]:
        return self._tool_specs

    @property
    def tool_names(self) -> list[str]:
        return [spec["toolSpec"]["name"] for spec in self._tool_specs]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        if self._session is None:
            return ToolOutcome(text=f"Tool {name} is not available.", data=None, is_error=True)
        try:
            result = await self._session.call_tool(name, arguments)
        except (Exception, BaseExceptionGroup) as exc:
            if _has_cancellation(exc):
                raise
            logger.warning("tool %s failed", name, exc_info=True)
            # Reported as a failed tool rather than raised, so the model can try another
            # or explain the gap.
            return ToolOutcome(
                text=f"Tool {name} failed: {type(exc).__name__}", data=None, is_error=True
            )

        texts: list[str] = []
        for block in result.content or []:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                texts.append(text)
        payload = "\n".join(texts)

        data: Any | None = getattr(result, "structured_content", None)
        if data is None and payload:
            try:
                data = json.loads(payload)
            except ValueError:
                data = None

        semantic_error = _semantic_error(data)

        return ToolOutcome(
            text=(semantic_error or payload)[:MAX_TOOL_RESULT_CHARS] or "(no output)",
            data=data,
            is_error=bool(getattr(result, "is_error", False)) or semantic_error is not None,
        )


NO_TOOLS = ToolSession(None, [])


class ToolGateway:
    """Opens tool sessions against the configured MCP server.

    Two transports, one session interface:

    - **`url`** - Streamable HTTP to a remote server. This is the production path once
      `MCP_SERVER_URL` points at swisstopo's endpoint.
    - **`server`** - an in-process `MCPServer` over the SDK's in-memory transport, used
      by the tests and the eval harness. A loopback HTTP server inside this process
      accepts connections before the ASGI lifespan has started the MCP session manager,
      and requests in that window are answered without being handled, leaving the agent
      with no tools. An in-memory transport has no listener and no such window.
    """

    def __init__(
        self,
        url: str = "",
        token: str = "",
        *,
        server: Any = None,
        read_timeout: float = 60.0,
    ) -> None:
        self._url = url
        self._token = token
        self._server = server
        self._read_timeout = read_timeout
        self._cached_specs: list[dict[str, Any]] | None = None
        self._cache_expires_at: float | None = None

    @property
    def configured(self) -> bool:
        return bool(self._url) or self._server is not None

    @property
    def is_production(self) -> bool:
        """Only a configured URL counts: the bundled stand-in must not be mistaken for
        swisstopo's server. A configured-but-unreachable URL still degrades (app/ws.py)."""
        return bool(self._url)

    @property
    def transport(self) -> str:
        if self._server is not None:
            return "in-process"
        return "streamable-http" if self._url else "none"

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ToolSession]:
        """Yields a ToolSession for the duration of one turn.

        Never raises: an unreachable or misconfigured server yields NO_TOOLS.
        """
        if not self.configured:
            yield NO_TOOLS
            return

        # Server unreachable, caller body raised, and teardown-after-a-good-turn all
        # arrive at the same handler and must stay distinguishable.
        #
        # NO_TOOLS is yielded after the exit stack unwinds, not from inside the handler:
        # the transport lives in an anyio task group, and yielding inside a failed group's
        # scope raises instead of returning control to the caller.
        caller_failed = False
        yielded = False
        try:
            async with AsyncExitStack() as stack:
                tool_session = await self._connect(stack)
                try:
                    yielded = True
                    yield tool_session
                except BaseException:
                    caller_failed = True
                    raise
        except (Exception, BaseExceptionGroup) as exc:
            if caller_failed or _has_cancellation(exc):
                raise
            logger.warning(
                "MCP server (%s) unusable; running without tools", self.transport, exc_info=True
            )

        if not yielded:
            yield NO_TOOLS

    async def _connect(self, stack: AsyncExitStack) -> ToolSession:
        """Opens the session and resolves the tool catalogue. Raises on failure."""
        if self._server is not None:
            from mcp import Client

            client = await stack.enter_async_context(Client(self._server))
            return ToolSession(client, await self._resolve_specs(client))

        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        http_client = await stack.enter_async_context(
            httpx2.AsyncClient(headers=headers, timeout=self._read_timeout)
        )
        read, write = await stack.enter_async_context(
            streamable_http_client(self._url, http_client=http_client)
        )
        session = await stack.enter_async_context(
            ClientSession(read, write, read_timeout_seconds=self._read_timeout)
        )
        await session.initialize()
        return ToolSession(session, await self._resolve_specs(session))

    async def _resolve_specs(self, session: Any) -> list[dict[str, Any]]:
        # Truthiness, not `is not None`: an empty catalogue means the server answered
        # before it was ready, and caching that leaves the agent toolless for the process
        # lifetime while /health stays green.
        if self._cached_specs and not self._cache_expired():
            return self._cached_specs

        tools, ttl_ms = await self._list_all_tools(session)
        specs = [to_tool_spec(tool.name, tool.description, tool.input_schema) for tool in tools]

        # `cache_scope` is not consulted: it distinguishes a shared cache from a per-user
        # one, and this is the latter. `ttl_ms` is honoured, so a server can bound how long
        # a stale catalogue survives; 0 means it did not say, and we keep it for the
        # process as before.
        self._cached_specs = specs
        self._cache_expires_at = time.monotonic() + ttl_ms / 1000 if ttl_ms else None

        logger.info("MCP tools available: %s", ", ".join(t.name for t in tools) or "(none)")
        return specs

    def _cache_expired(self) -> bool:
        return self._cache_expires_at is not None and time.monotonic() >= self._cache_expires_at

    async def _list_all_tools(self, session: Any) -> tuple[list[Any], int]:
        """Every page of `tools/list`, plus the server's advertised cache lifetime.

        Without following the cursor, everything past page one is silently invisible to
        the model.
        """
        tools: list[Any] = []
        cursor: str | None = None
        ttl_ms = 0
        for _ in range(MAX_TOOL_PAGES):
            listing = await self._list_tools_page(session, cursor)
            tools.extend(listing.tools)
            ttl_ms = getattr(listing, "ttl_ms", 0) or 0
            cursor = getattr(listing, "next_cursor", None)
            if not cursor:
                return tools, ttl_ms
        logger.warning("tools/list still paginating after %d pages; truncating", MAX_TOOL_PAGES)
        return tools, ttl_ms

    async def _list_tools_page(self, session: Any, cursor: str | None) -> Any:
        """One page. The two SDK clients paginate differently: ClientSession takes a
        PaginatedRequestParams, the in-process Client takes a bare cursor."""
        if cursor is None:
            return await session.list_tools()
        if "cursor" in inspect.signature(session.list_tools).parameters:
            return await session.list_tools(cursor=cursor)
        from mcp.types import PaginatedRequestParams

        return await session.list_tools(params=PaginatedRequestParams(cursor=cursor))
