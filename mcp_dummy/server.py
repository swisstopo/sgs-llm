"""A stand-in geodata MCP server backed by the real geo.admin.ch APIs.

Development and evaluation only; it never serves production traffic (mcp_dummy/README.md).

    python -m mcp_dummy.server            # http://127.0.0.1:8788/mcp

Tool docstrings are the descriptions the model sees, so they are written as instructions
to it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import OrderedDict
from typing import Any

from mcp.server import MCPServer

from .geometry import bounding_box, geometry_type, measure, summarise_properties
from .results import ResultCache
from .swisstopo import LayerNotQueryable, Swisstopo

logger = logging.getLogger(__name__)

ATTRIBUTION = "swisstopo / geo.admin.ch"
MAX_FEATURES = 200


def build_server(artifacts: Any, swisstopo: Swisstopo) -> MCPServer:
    """Builds the server.

    `artifacts` needs one method - `async publish_geojson(name, collection) -> url`.
    Standalone that is LocalArtifacts below; the eval harness passes the backend's
    ArtifactStore.

    `swisstopo` is required rather than defaulted so its HTTP client always has an owner
    that can close it - a server built with a hidden client leaks a connection pool.
    """
    server = MCPServer(name="sgs-llm-geodata-dummy", version="1")
    api = swisstopo
    cache = ResultCache()

    @server.tool()
    async def search_layers(query: str, lang: str = "de") -> dict[str, Any]:
        """Find official Swiss geodata datasets by topic.

        Use this first for any question about what data exists. Returns candidate
        layer_id values, each flagged with how it can be used:

        - `queryable: true`  → filter_features can fetch individual features from it.
        - `queryable: false` → it is a raster/image layer. Do NOT call filter_features on
          it; call display_catalog_layer to put it on the map instead.

        `query` should be the subject only (e.g. "Hochwasser", "solar potential"), not a
        place name.
        """
        layers = await api.search_layers(query, lang)
        if not layers:
            return {"layers": [], "note": f"No official dataset matches '{query}'."}
        return {"layers": layers}

    @server.tool()
    async def search_locations(query: str, lang: str = "de") -> dict[str, Any]:
        """Resolve a Swiss place name to a bounding box.

        Accepts cantons (any national language, or the two-letter code), communes,
        districts and place names. Use this whenever the question mentions a place, and
        pass the resulting bbox to filter_features. Returns [] if the place is unknown
        - do not invent a bbox.
        """
        places = await api.search_locations(query, lang)
        if not places:
            return {"places": [], "note": f"No Swiss place matches '{query}'."}
        return {"places": places}

    @server.tool()
    async def filter_features(
        layer_id: str,
        bbox: list[float],
        lang: str = "de",
        contains: str | None = None,
        limit: int = MAX_FEATURES,
    ) -> dict[str, Any]:
        """Fetch features of one dataset inside a bounding box.

        `layer_id` comes from search_layers, `bbox` from search_locations, as WGS84
        [min_lon, min_lat, max_lon, max_lat]. `contains` optionally keeps only features
        whose attributes contain that text.

        Returns a summary plus a `result_id` handle - not the features themselves. Pass
        the handle to analyze_features for figures, or to display_layer to put it on the user's
        map.
        """
        if len(bbox) != 4:
            return {"error": "bbox must be [min_lon, min_lat, max_lon, max_lat] in WGS84."}

        try:
            features = await api.identify_features(
                layer_id, bbox, lang, limit=min(limit, MAX_FEATURES)
            )
        except LayerNotQueryable:
            # An answerable fact, not a failure. Reported so the model picks a different
            # dataset instead of retrying this one until it runs out of iterations.
            return {
                "feature_count": 0,
                "queryable": False,
                "note": (
                    f"Dataset '{layer_id}' cannot be queried feature-by-feature - it is "
                    "raster or image-based. Call search_layers again and choose a "
                    "different, vector-based dataset; do not retry this layer_id."
                ),
            }
        if contains:
            needle = contains.lower()
            features = [
                f
                for f in features
                if any(needle in str(v).lower() for v in (f.get("properties") or {}).values())
            ]

        if not features:
            return {
                "feature_count": 0,
                "note": (
                    f"Dataset '{layer_id}' returned no features in this area. It may not "
                    "cover it, or may not be queryable feature-by-feature."
                ),
            }

        entry = cache.put(layer_id, layer_id, features)
        truncated = len(features) >= min(limit, MAX_FEATURES)
        result: dict[str, Any] = {
            "result_id": entry.result_id,
            "layer_id": layer_id,
            "feature_count": len(features),
            "geometry_type": geometry_type(features),
            "bbox": bounding_box(features),
            "truncated": truncated,
            "attributes": summarise_properties(features),
        }
        if truncated:
            # Unsaid, models report the cap as the total: observed live as "50
            # Messstationen im Kanton Bern", 50 being the old limit, not a fact about Bern.
            result["count_note"] = (
                f"The fetch hit its limit of {min(limit, MAX_FEATURES)} features, so this is "
                "NOT the total. Report it as 'at least "
                f"{len(features)}' and say the list is capped."
            )
        return result

    @server.tool()
    async def display_catalog_layer(
        layer_id: str,
        lang: str = "de",
        name: str | None = None,
        opacity: float | None = None,
        focus_bbox: list[float] | None = None,
    ) -> dict[str, Any]:
        """Put an official geo.admin.ch layer on the user's map, without fetching it.

        This is how to show raster and image layers - flood hazard (Aquaprotect), noise
        maps, warning maps - i.e. anything search_layers reports as `queryable: false`.
        The client renders it straight from swisstopo.

        Pass `focus_bbox` (from search_locations) to zoom to the area asked about: the
        layer itself covers all of Switzerland and cannot be subset. Use `name` to label
        it in the user's language.

        For vector data you have already fetched, use display_layer instead.
        """
        caps = await api.layer_capabilities(layer_id, lang)
        if not caps["known"]:
            return {"error": f"'{layer_id}' is not an official layer id. Use search_layers first."}
        if not caps["displayable"]:
            return {"error": f"'{layer_id}' cannot be rendered as a map layer."}

        layer: dict[str, Any] = {
            "id": layer_id,
            "name": name or caps.get("label") or layer_id,
            "attribution": ATTRIBUTION,
        }
        if opacity is not None:
            layer["opacity"] = opacity
        result: dict[str, Any] = {
            "catalog_layer": layer,
            "layer_type": caps.get("type"),
        }
        if focus_bbox and len(focus_bbox) == 4:
            result["focus_bbox"] = focus_bbox
        return result

    @server.tool()
    async def analyze_features(result_id: str, operation: str = "summary") -> dict[str, Any]:
        """Compute figures over a fetched feature set.

        `operation` is one of: "count", "area" (total km²), "length" (total km),
        "extent" (bounding box), or "summary" (all of them). Use this instead of
        estimating numbers yourself.
        """
        entry = cache.get(result_id)
        if entry is None:
            return {"error": f"Unknown result_id '{result_id}'. Call filter_features first."}

        features = entry.features
        wanted = operation.strip().lower()
        result: dict[str, Any] = {"result_id": result_id, "count": len(features)}
        if len(features) >= MAX_FEATURES:
            # Every figure below is computed over a capped set, so none of them are totals.
            result["truncated"] = True
            result["count_note"] = (
                f"Computed over a capped set of {len(features)} features, so the count, area "
                "and length are lower bounds, not totals. Say so in the answer."
            )
        if wanted in ("area", "length", "summary"):
            result.update(measure(features))
        if wanted in ("extent", "summary"):
            result["bbox"] = bounding_box(features)
        return result

    @server.tool()
    async def display_layer(
        result_id: str,
        name: str,
        fill_color: str | None = None,
        opacity: float | None = None,
    ) -> dict[str, Any]:
        """Put a fetched feature set on the user's map.

        Call this once you have data worth showing. `name` is the label the user sees,
        so write it in their language. Returns the published layer; mention in your
        answer what is now visible on the map.
        """
        entry = cache.get(result_id)
        if entry is None:
            return {"error": f"Unknown result_id '{result_id}'. Call filter_features first."}

        collection = {"type": "FeatureCollection", "features": entry.features}
        url = await artifacts.publish_geojson(f"{result_id}.geojson", collection)
        if url is None:
            return {"error": "Could not publish the layer."}

        layer: dict[str, Any] = {
            "id": result_id,
            "name": name or entry.layer_id,
            "format": "geojson",
            "url": url,
            "geometry_type": geometry_type(entry.features),
            "feature_count": len(entry.features),
            "bbox": bounding_box(entry.features),
            "attribution": f"{ATTRIBUTION} · {entry.layer_id}",
        }
        style = {
            key: value
            for key, value in (("fill_color", fill_color), ("opacity", opacity))
            if value is not None
        }
        if style:
            layer["style_hint"] = style
        return {"layer": layer}

    return server


class LocalArtifacts:
    """Standalone artifact publishing: keeps GeoJSON in memory and serves it from
    this server, so `python -m mcp_dummy.server` needs no AWS and no backend."""

    def __init__(self, base_url: str, limit: int = 64) -> None:
        self.base_url = base_url
        self._limit = limit
        self._files: OrderedDict[str, bytes] = OrderedDict()

    async def publish_geojson(self, name: str, feature_collection: dict[str, Any]) -> str | None:
        self._files[name] = json.dumps(feature_collection, ensure_ascii=False).encode("utf-8")
        self._files.move_to_end(name)
        while len(self._files) > self._limit:
            self._files.popitem(last=False)
        return f"{self.base_url}/artifacts/{name}"

    def read(self, name: str) -> bytes | None:
        return self._files.get(name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the stand-in geodata MCP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    import uvicorn
    from starlette.responses import Response

    artifacts = LocalArtifacts(f"http://{args.host}:{args.port}")
    api = Swisstopo()
    server = build_server(artifacts, api)

    # The SDK's route decorator carries no annotations, so strict mode would flag the
    # handler as untyped.
    @server.custom_route("/artifacts/{name}", methods=["GET"])  # type: ignore[untyped-decorator]
    async def serve_artifact(request: Any) -> Response:
        body = artifacts.read(request.path_params["name"])
        if body is None:
            return Response(status_code=404)
        return Response(
            content=body,
            media_type="application/geo+json",
            headers={"access-control-allow-origin": "*"},
        )

    app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True)
    logger.info("dummy MCP server on http://%s:%d/mcp", args.host, args.port)

    async def serve() -> None:
        # Awaited rather than uvicorn.run so the HTTP client is closed on shutdown while
        # its event loop is still alive.
        config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
        try:
            await uvicorn.Server(config).serve()
        finally:
            await api.aclose()

    asyncio.run(serve())


if __name__ == "__main__":
    main()
