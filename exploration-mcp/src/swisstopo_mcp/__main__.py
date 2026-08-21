"""CLI entry point supporting local stdio and remote Streamable HTTP transports."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from contextlib import suppress
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

from .catalog import CatalogIndex
from .geo_admin import GeoAdminClient
from .server import SERVER_NAME, SERVER_VERSION, build_server


def _csv_environment(name: str) -> list[str]:
    return [value.strip() for value in os.environ.get(name, "").split(",") if value.strip()]


def _transport_security(host: str, port: int) -> TransportSecuritySettings:
    allowed_hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
    if host not in {"0.0.0.0", "::", "127.0.0.1", "localhost"}:
        allowed_hosts.append(f"{host}:{port}")
    allowed_hosts.extend(_csv_environment("SWISSTOPO_MCP_ALLOWED_HOSTS"))
    allowed_origins = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]
    allowed_origins.extend(_csv_environment("SWISSTOPO_MCP_ALLOWED_ORIGINS"))
    return TransportSecuritySettings(
        allowed_hosts=list(dict.fromkeys(allowed_hosts)),
        allowed_origins=list(dict.fromkeys(allowed_origins)),
    )


async def _serve_http(
    *,
    host: str,
    port: int,
    log_level: str,
    catalog: CatalogIndex,
    api: GeoAdminClient,
) -> None:
    import uvicorn
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    server = build_server(catalog, api)
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=_transport_security(host, port),
        host=host,
    )

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "server": SERVER_NAME,
                "version": SERVER_VERSION,
                **catalog.counts,
                "mcp_endpoint": "/mcp",
                "transport": "streamable-http",
                "stateless": True,
            }
        )

    async def root(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
                "mcp": "/mcp",
                "health": "/health",
                "documentation": "README.md",
            }
        )

    app.router.routes.extend(
        [
            Route("/health", health, methods=["GET"]),
            Route("/", root, methods=["GET"]),
        ]
    )
    config = uvicorn.Config(app, host=host, port=port, log_level=log_level.casefold())
    try:
        await uvicorn.Server(config).serve()
    finally:
        await api.aclose()


async def _serve_stdio(catalog: CatalogIndex, api: GeoAdminClient) -> None:
    server = build_server(catalog, api)
    try:
        await server.run_stdio_async()
    finally:
        await api.aclose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the read-only Swisstopo search MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http", "streamable-http"),
        default=os.environ.get("SWISSTOPO_MCP_TRANSPORT", "stdio"),
        help="stdio for a local subprocess; http/streamable-http for a remote endpoint.",
    )
    parser.add_argument("--host", default=os.environ.get("SWISSTOPO_MCP_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("SWISSTOPO_MCP_PORT", "8791")),
    )
    parser.add_argument(
        "--log-level",
        choices=("debug", "info", "warning", "error"),
        default=os.environ.get("SWISSTOPO_MCP_LOG_LEVEL", "info").casefold(),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    catalog = CatalogIndex()
    api = GeoAdminClient()
    logging.getLogger(__name__).info(
        "%s %s loaded: %s", SERVER_NAME, SERVER_VERSION, catalog.counts
    )
    coroutine: Any
    if args.transport == "stdio":
        coroutine = _serve_stdio(catalog, api)
    else:
        coroutine = _serve_http(
            host=args.host,
            port=args.port,
            log_level=args.log_level,
            catalog=catalog,
            api=api,
        )
    # SIGINT is the normal way a local stdio/HTTP MCP process is stopped. Uvicorn and
    # the MCP session manager have already run their shutdown hooks by here.
    with suppress(KeyboardInterrupt):
        asyncio.run(coroutine)


if __name__ == "__main__":
    main()
