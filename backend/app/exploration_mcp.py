"""Public, read-only exploration MCP mounted into the existing backend process.

The MCP is deliberately a separate ASGI application even though it shares the Fargate
task. That keeps its protocol middleware and lifespan independent from the chat API while
letting both services reuse the already-paid-for Uvicorn process, ALB and CloudFront
distribution.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Collection
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from swisstopo_mcp.catalog import CatalogIndex
from swisstopo_mcp.geo_admin import GeoAdminClient
from swisstopo_mcp.server import build_server

from .config import Settings
from .limits import RateLimiter
from .security import client_key

_MCP_METHODS = ["GET", "POST", "DELETE", "OPTIONS"]
_MCP_HEADERS = [
    "accept",
    "content-type",
    "last-event-id",
    "mcp-protocol-version",
    "mcp-session-id",
]
_MCP_EXPOSE_HEADERS = ["mcp-protocol-version", "mcp-session-id"]


def _origin_is_allowed(origin: str, allowed_origins: Collection[str]) -> bool:
    if origin in allowed_origins:
        return True
    for candidate in allowed_origins:
        if not candidate.endswith(":*"):
            continue
        prefix = f"{candidate[:-2]}:"
        if origin.startswith(prefix) and origin.removeprefix(prefix).isdigit():
            return True
    return False


class PublicMcpGuard:
    """Bounds unauthenticated MCP traffic before it reaches geo.admin.ch.

    The per-viewer key is trustworthy because the backend ALB accepts traffic only from
    CloudFront's origin-facing prefix list. The global cap protects the chat API from a
    burst of slow upstream calls even when that burst comes from many addresses.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_minute: int,
        concurrency: int,
        allowed_origins: Collection[str],
    ) -> None:
        self._app = app
        self._limiter = RateLimiter(requests_per_minute)
        self._slots = asyncio.Semaphore(max(concurrency, 1))
        self._allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        peer = scope.get("client")
        key = client_key(
            headers.get("x-forwarded-for"),
            str(peer[0]) if peer else None,
        )
        if not self._limiter.allow(key):
            await JSONResponse(
                {"error": "exploration_mcp_rate_limit", "retry_after_seconds": 60},
                status_code=429,
                headers={"retry-after": "60"},
            )(scope, receive, send)
            return

        origin = headers.get("origin")
        if origin is not None and not _origin_is_allowed(origin, self._allowed_origins):
            # The distribution maps 403/404 to index.html for frontend SPA navigation.
            # A 400 keeps this MCP protocol error intact through CloudFront.
            await JSONResponse(
                {"error": "exploration_mcp_origin_not_allowed"},
                status_code=400,
            )(scope, receive, send)
            return

        # Do not queue an unbounded number of public requests inside the backend task.
        if self._slots.locked():
            await JSONResponse(
                {"error": "exploration_mcp_busy", "retry_after_seconds": 1},
                status_code=503,
                headers={"retry-after": "1"},
            )(scope, receive, send)
            return

        await self._slots.acquire()
        try:
            await self._app(scope, receive, send)
        finally:
            self._slots.release()


@dataclass
class PublicExplorationMcp:
    """The mounted app plus the resources whose lifespan the parent must own."""

    app: ASGIApp
    runtime_app: Starlette
    catalog: CatalogIndex
    api: GeoAdminClient

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        try:
            async with self.runtime_app.router.lifespan_context(self.runtime_app):
                yield
        finally:
            await self.api.aclose()


def _public_origin(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def build_public_exploration_mcp(
    settings: Settings,
    *,
    catalog: CatalogIndex | None = None,
    api: GeoAdminClient | None = None,
) -> PublicExplorationMcp:
    """Build the stateless Streamable HTTP server mounted at the parent's ``/mcp``."""

    index = catalog or CatalogIndex()
    geo_admin = api or GeoAdminClient()

    allowed_hosts = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"]
    public_origin = _public_origin(settings.public_base_url)
    if public_origin is not None:
        allowed_hosts.append(urlsplit(public_origin).netloc)

    allowed_origins = [
        "http://127.0.0.1",
        "http://127.0.0.1:*",
        "http://localhost",
        "http://localhost:*",
        *settings.exploration_mcp_origin_allowlist,
    ]
    if public_origin is not None:
        allowed_origins.append(public_origin)
    allowed_origins = list(dict.fromkeys(allowed_origins))

    server = build_server(index, geo_admin)
    runtime_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=settings.max_frame_bytes,
        transport_security=TransportSecuritySettings(
            allowed_hosts=list(dict.fromkeys(allowed_hosts)),
            allowed_origins=allowed_origins,
        ),
        host="0.0.0.0",
    )
    guarded: ASGIApp = PublicMcpGuard(
        runtime_app,
        requests_per_minute=settings.exploration_mcp_requests_per_minute,
        concurrency=settings.exploration_mcp_max_concurrent_requests,
        allowed_origins=allowed_origins,
    )
    public_app: ASGIApp = CORSMiddleware(
        guarded,
        allow_origins=allowed_origins,
        allow_methods=_MCP_METHODS,
        allow_headers=_MCP_HEADERS,
        expose_headers=_MCP_EXPOSE_HEADERS,
        max_age=86_400,
    )
    return PublicExplorationMcp(
        app=public_app,
        runtime_app=runtime_app,
        catalog=index,
        api=geo_admin,
    )
