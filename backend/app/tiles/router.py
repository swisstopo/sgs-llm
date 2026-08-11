"""Public capability routes for generated vector tiles."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from tile_server.model import InvalidTile, RenderTimedOut, SourceInvalid, TileCoord, TileTooLarge

from app.tiles.service import (
    RenderBusy,
    TileIoBusy,
    TileRenderFailed,
    TileService,
    TileTotalTimedOut,
)
from app.tiles.store import (
    LayerDeleteError,
    LayerExpired,
    LayerInvalid,
    LayerMissing,
    capability_fingerprint,
)

logger = logging.getLogger(__name__)
router = APIRouter()

MVT_CONTENT_TYPE = "application/vnd.mapbox-vector-tile"
_PUBLIC_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-expose-headers": "ETag, Retry-After",
    "x-content-type-options": "nosniff",
}
_ERROR_HEADERS = {**_PUBLIC_HEADERS, "cache-control": "no-store"}


def _service(request: Request) -> TileService | None:
    service = getattr(request.app.state, "tile_service", None)
    return service if isinstance(service, TileService) else None


def _error(status: int, *, retry_after: int | None = None) -> Response:
    headers = dict(_ERROR_HEADERS)
    if retry_after is not None:
        headers["retry-after"] = str(retry_after)
    return Response(status_code=status, headers=headers)


@router.options("/data/tiles/{capability}/{z}/{x}/{y}.mvt")
@router.options("/data/layers/{capability}")
async def tile_options(capability: str, z: int = 0, x: int = 0, y: int = 0) -> Response:
    del capability, z, x, y
    return Response(
        status_code=204,
        headers={
            **_PUBLIC_HEADERS,
            "access-control-allow-methods": "GET, DELETE, OPTIONS",
            "access-control-allow-headers": "If-None-Match",
            "access-control-max-age": "600",
        },
    )


@router.get("/data/tiles/{capability}/{z}/{x}/{y}.mvt")
async def vector_tile(
    capability: str,
    z: int,
    x: int,
    y: int,
    request: Request,
) -> Response:
    """Return one immutable MVT tile generated from the private GeoParquet source."""
    service = _service(request)
    if service is None:
        return _error(503, retry_after=2)
    try:
        result = await service.tile(capability, TileCoord(z=z, x=x, y=y))
    except (ValueError, InvalidTile):
        return _error(400)
    except (LayerMissing, LayerExpired):
        return _error(410)
    except (RenderBusy, TileIoBusy) as exc:
        return _error(503, retry_after=exc.retry_after)
    except (RenderTimedOut, TileTotalTimedOut):
        return _error(503, retry_after=2)
    except (
        LayerInvalid,
        SourceInvalid,
        TileRenderFailed,
        TileTooLarge,
    ):
        return _error(500)
    except Exception:
        try:
            fingerprint = capability_fingerprint(capability)
        except ValueError:
            return _error(400)
        logger.exception("unexpected tile failure fp=%s coord=%d/%d/%d", fingerprint, z, x, y)
        return _error(500)

    if request.headers.get("if-none-match") == result.etag:
        return Response(
            status_code=304,
            headers={**_PUBLIC_HEADERS, "etag": result.etag, "cache-control": "no-cache"},
        )

    max_age = 300
    if result.expires_at is not None:
        remaining = int((result.expires_at - datetime.now(UTC)).total_seconds())
        max_age = max(0, min(max_age, remaining))
    headers = {
        **_PUBLIC_HEADERS,
        "etag": result.etag,
        "cache-control": f"public, max-age={max_age}",
    }
    if not result.body:
        return Response(status_code=204, headers=headers)
    return Response(content=result.body, media_type=MVT_CONTENT_TYPE, headers=headers)


@router.delete("/data/layers/{capability}")
async def delete_layer(capability: str, request: Request) -> Response:
    """Tombstone and remove one generated layer; repeated calls remain safe."""
    service = _service(request)
    if service is None:
        return _error(503, retry_after=2)
    try:
        await service.delete(capability)
    except ValueError:
        return _error(400)
    except TileIoBusy as exc:
        return _error(503, retry_after=exc.retry_after)
    except (LayerDeleteError, LayerInvalid):
        return _error(500)
    except Exception:
        try:
            fingerprint = capability_fingerprint(capability)
        except ValueError:
            return _error(400)
        logger.exception("unexpected generated-layer deletion failure fp=%s", fingerprint)
        return _error(500)
    return Response(status_code=204, headers={**_PUBLIC_HEADERS, "cache-control": "no-store"})
