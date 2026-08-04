"""The agent backend application.

Serves the paths CloudFront routes here (/ws/v1, /feedback, /data/*) plus /health for the
ALB. See docs/deployment.md#what-the-container-image-must-provide.

Everything expensive is lazy: the app must start healthy with no AWS credentials, no
tables and no MCP server, because that is how CI smoke-tests the image before allowing a
deploy.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from .agent.bedrock import BedrockModels
from .config import Settings, get_settings
from .feedback import router as feedback_router
from .limits import ConnectionRegistry, RateLimiter
from .mcp.client import ToolGateway
from .store.artifacts import ArtifactStore
from .store.dynamo import Store
from .ws import router as ws_router

logger = logging.getLogger(__name__)


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    _configure_logging(settings)

    app.state.settings = settings
    app.state.store = Store(settings)
    app.state.artifacts = ArtifactStore(settings)
    app.state.models = BedrockModels(settings)
    app.state.limiter = RateLimiter(settings.rate_limit_messages_per_minute)
    app.state.connections = ConnectionRegistry(limit=settings.max_connections_per_ip)

    # The bundled stand-in is never wired up here; the tests and eval harness construct
    # it themselves. Locally, point MCP_SERVER_URL at `python -m mcp_dummy.server`.
    app.state.gateway = ToolGateway(settings.mcp_server_url, settings.mcp_server_token)

    logger.info(
        "backend ready: models=%s mcp=%s (%s) feedback_table=%s data_bucket=%s",
        ", ".join(str(h) for h in app.state.models.handles) or "(none configured)",
        settings.mcp_server_url or "NOT CONFIGURED (refusing turns)",
        app.state.gateway.transport,
        settings.feedback_table or "(disabled)",
        settings.data_layer_bucket or "(in-memory)",
    )
    if not app.state.gateway.is_production:
        logger.warning(
            "no production MCP server: set MCP_SERVER_URL to swisstopo's endpoint to "
            "enable the chat. Until then /ws/v1 accepts connections and refuses every "
            "turn; the map (Track A) is unaffected."
        )
    yield


app = FastAPI(title="SGS LLM agent backend", version="1", lifespan=lifespan)
app.include_router(feedback_router)
app.include_router(ws_router)


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe for the ALB target group. Must stay cheap and dependency-free:
    a health check that touched Bedrock or DynamoDB would take the service down
    whenever they were slow."""
    return JSONResponse({"status": "ok"}, headers={"cache-control": "no-store"})


@app.get("/data/{name}")
async def data_artifact(name: str) -> Response:
    """Serves in-memory artifacts when no data bucket is configured.

    With a bucket, layers are handed out as presigned URLs and this path is unused.
    """
    if "/" in name or ".." in name:
        return Response(status_code=400)
    body = app.state.artifacts.read_local(name)
    if body is None:
        return Response(status_code=404, headers={"access-control-allow-origin": "*"})
    return Response(
        content=body,
        media_type="application/geo+json",
        # Mirrors the presigned-URL behavior: any origin may fetch.
        headers={"access-control-allow-origin": "*"},
    )
