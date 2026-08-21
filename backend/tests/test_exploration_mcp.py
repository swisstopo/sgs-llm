"""The portable exploration MCP mounted into the production backend ASGI process."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.exploration_mcp import build_public_exploration_mcp

_HEADERS = {
    "accept": "application/json, text/event-stream",
    "mcp-protocol-version": "2025-06-18",
}


def _request(method: str, request_id: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {}}


@contextmanager
def _client(*, requests_per_minute: int = 120) -> Iterator[TestClient]:
    component = build_public_exploration_mcp(
        Settings(
            public_base_url="https://testserver",
            exploration_mcp_allowed_origins="https://claude.ai,https://claude.com",
            exploration_mcp_requests_per_minute=requests_per_minute,
        )
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> Any:
        async with component.run():
            yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount("/", component.app)
    with TestClient(app) as client:
        yield client


def test_backend_health_and_all_seven_public_tools_share_one_process() -> None:
    with _client() as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.post("/mcp", headers=_HEADERS, json=_request("tools/list"))

    assert response.status_code == 200
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == {
        "search_datasets",
        "describe_dataset",
        "search_divisions",
        "create_map_preview",
        "geocode_location",
        "identify_at_point",
        "explain_swisstopo",
    }


def test_mcp_cors_accepts_claude_and_rejects_an_untrusted_browser_origin() -> None:
    with _client() as client:
        preflight = client.options(
            "/mcp",
            headers={
                "origin": "https://claude.ai",
                "access-control-request-method": "POST",
                "access-control-request-headers": "mcp-protocol-version,content-type",
            },
        )
        rejected = client.post(
            "/mcp",
            headers={**_HEADERS, "origin": "https://evil.example"},
            json=_request("tools/list", 2),
        )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://claude.ai"
    assert rejected.status_code == 400
    assert rejected.json() == {"error": "exploration_mcp_origin_not_allowed"}


def test_mcp_rebinding_and_request_rate_guards_are_independent_from_chat() -> None:
    with _client(requests_per_minute=1) as client:
        invalid_host = client.post(
            "https://invalid.example/mcp",
            headers={**_HEADERS, "x-forwarded-for": "198.51.100.1"},
            json=_request("tools/list"),
        )
        first = client.post("/mcp", headers=_HEADERS, json=_request("tools/list", 2))
        limited = client.post("/mcp", headers=_HEADERS, json=_request("tools/list", 3))

    # An invalid Host is rejected by MCP security before tool handling. That caller still
    # spends its own rate-limit token, so it cannot use malformed requests as a free flood.
    assert invalid_host.status_code == 421
    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
