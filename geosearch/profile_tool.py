"""MCP elevation profile over a selected cached route."""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server import MCPServer

from .elevation import RouteSelectionRequired, select_route
from .results import ResultCache
from .swisstopo import Swisstopo


def register_profile_tool(
    server: MCPServer, api: Swisstopo, cache: ResultCache
) -> None:
    @server.tool()
    async def elevation_profile(
        result_id: str,
        feature_index: int | None = None,
        part_index: int | None = None,
        samples: int = 200,
    ) -> dict[str, Any]:
        """Get official sampled elevations and ascent/descent for a fetched line route.

        Pass a result_id from filter_features. When it contains multiple features,
        choose the intended zero-based feature_index from the candidates or narrow the
        result first; never silently profile the first route. MultiLineString features
        with multiple parts require a part_index; disconnected parts are never joined.
        samples is 2..200; source routes may contain at most 5,000 vertices.

        Returns distances/elevations in metres, estimated ascent/descent in coordinate
        order, and a new result_id for the exact profiled line. Pass that result_id to
        display_layer so the map and profile describe the same route. For a selected
        line part, describe its figures as that segment, not the entire route network.
        """
        entry = cache.get(result_id)
        if entry is None:
            return {
                "error": "Unknown result_id. Fetch the route with filter_features first."
            }
        try:
            route, scope = select_route(entry.features, feature_index, part_index)
            profile = await api.elevation_profile(route["geometry"], samples=samples)
        except RouteSelectionRequired as exc:
            return {
                "error": str(exc),
                "candidates": exc.candidates,
                "candidate_count": exc.total,
                "candidates_truncated": exc.total > 20,
            }
        except ValueError as exc:
            return {"error": str(exc), "complete": False}
        except httpx.HTTPError:
            return {
                "error": "The elevation service is unavailable. No complete profile was computed.",
                "complete": False,
            }
        selected = cache.put(
            entry.layer_id, entry.title, [route], spatial_scope=entry.spatial_scope
        )
        return {
            **profile,
            **scope,
            "source_result_id": result_id,
            "result_id": selected.result_id,
        }
