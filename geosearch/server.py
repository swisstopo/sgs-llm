"""The geodata MCP server: semantic catalogue search over the pre-built index.

    python -m geosearch.build      # once
    python -m geosearch.server     # http://127.0.0.1:8790/mcp

Same six-tool surface as mcp_dummy, so the backend and the eval harness need no
changes. What differs is underneath: search_layers and search_locations read the FAISS
index instead of geo.admin.ch's SearchServer, and filter_features fetches through the
grid-subdivided identify rather than a single capped request.

Tool docstrings are the descriptions the model sees, so they are written as instructions
to it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.routing import Route

from .boundaries import BoundaryStore
from .geometry import bounding_box, clip, geometry_type, measure, summarise_properties
from .index import INDEX_DIR, GeoIndex, confidence
from .layer_publisher import S3LayerPublisher
from .rerank import Reranker
from .results import ResultCache
from .swisstopo import LayerNotQueryable, Swisstopo

logger = logging.getLogger(__name__)

ATTRIBUTION = "swisstopo / geo.admin.ch"

# Localities come from the official locality register, not swissBOUNDARIES3D; crediting
# the wrong dataset on a swisstopo layer is the kind of thing swisstopo notices.
_SOURCES = {"ortschaft": "Amtliches Ortschaftenverzeichnis"}

# What the vector stage hands the reranker. Wide enough that the answer is in there,
# small enough that judging it is one cheap call.
CANDIDATES = 30

# Divisions returned before truncation is reported. Ported from division_search.py's
# reasoning: canton-scale bulk questions ("every commune in Valais") need the whole set
# in one call, not a page of it.
MAX_DIVISIONS = 500


def build_server(
    index: GeoIndex,
    swisstopo: Swisstopo,
    artifacts: Any,
    store: BoundaryStore,
    reranker: Reranker | None = None,
) -> MCPServer:
    """`artifacts` needs `async publish_layer(result_id, features) -> PublishedLayer | None`.

    `store` is where the pre-built division boundaries live, and is separate from
    `artifacts` on purpose: generated layers are private expiring S3 sources, whereas
    the boundaries are read-only build output that ships with the image.

    Everything is injected rather than constructed here so the eval harness can swap
    those in, and so the HTTP client always has an owner that can close it.
    """
    server = MCPServer(name="sgs-llm-geodata", version="1")
    cache = ResultCache()
    judge = reranker or Reranker()

    @server.tool()
    async def search_layers(
        query: str, lang: str = "de", top_n: int = 8
    ) -> dict[str, Any]:
        """Find official Swiss geodata datasets by topic.

        Use this first for any question about what data exists. Search is semantic, so
        describe the subject in plain words - "forest area", "Waldfläche" and "surface
        boisée" all work, and you do not need the catalogue's exact wording.

        `query` should be the subject only ("flooding", "solar potential"), never a place
        name - places go to search_locations.

        Each result is flagged with how it can be used:
        - `queryable: true`  → filter_features can fetch individual features from it.
        - `queryable: false` → raster or image layer. Do NOT call filter_features on it;
          use display_catalog_layer to put it on the map instead.

        When `low_confidence` is true the top result is not a clear winner. Do not
        silently pick it - either say which candidates you are choosing between, or ask
        the user to narrow the question.
        """
        hits = index.search_layers(query, limit=CANDIDATES)
        if not hits:
            return {
                "layers": [],
                "note": (
                    f"Nothing in the swisstopo catalogue matches '{query}'. Try a broader "
                    "subject word rather than a longer phrase."
                ),
            }

        candidates = [{**h.row, "similarity": round(h.score, 4)} for h in hits]
        kept, reranked = await judge.filter(query, candidates, top_n=top_n)

        layers = [
            {
                "layer_id": row["layer_id"],
                "title": row["title"],
                "summary": (row["description"] or "")[:400],
                "queryable": row["queryable"],
                "displayable": row["displayable"],
                "data_owner": row["data_owner"],
                "similarity": row["similarity"],
            }
            for row in kept
        ]
        result: dict[str, Any] = {"layers": layers, **confidence(hits)}
        if not reranked:
            # The agent is choosing from a raw vector ranking, which contains
            # near-misses by design. It should know that before it trusts rank 1.
            result["note"] = (
                "Ranked by vector similarity only - the relevance filter was "
                "unavailable, so check each candidate against the question yourself."
            )
        return result

    @server.tool()
    async def search_locations(
        query: str, lang: str = "de", top_n: int = 10
    ) -> dict[str, Any]:
        """Resolve a Swiss place name to a bounding box.

        Covers Switzerland itself and every canton, district, commune and locality -
        localities being the level below a commune, which is what makes "Wengen",
        "Gstaad" and "Verbier" resolvable: none of them is a commune. Matching is
        semantic, so accents and spelling variants resolve ("Geneve" → "Genève",
        "Zurich" → "Zürich"). Use this whenever the question names a place.

        Pass the `name` and `kind` of the hit you chose to filter_features as `place` and
        `place_kind`, not the `bbox`: the bbox is only the rectangle around the place, and
        filtering by it answers with the neighbours in the corners too.

        Returns [] if the place is unknown - never invent one.
        """
        hits = index.search_divisions(query, limit=min(top_n, MAX_DIVISIONS))
        if not hits:
            return {"places": [], "note": f"No Swiss place matches '{query}'."}
        return {
            "places": [
                {
                    "name": h.row["name"],
                    "kind": h.row["kind"],
                    "canton": h.row["canton"],
                    "bbox": h.row["bbox"],
                    "similarity": round(h.score, 4),
                }
                for h in hits
            ]
        }

    @server.tool()
    async def display_division(name: str, kind: str | None = None) -> dict[str, Any]:
        """Put an administrative boundary on the user's map.

        `name` is a place from search_locations; `kind` is one of "land", "kanton",
        "bezirk", "gemeinde", "ortschaft" and disambiguates the many cases where one name
        names several levels (Zug and Bern are a commune and a canton; Zürich is also a
        district and a locality).

        The boundary polygons were downloaded once at build time, so this does not call
        geo.admin.ch.
        """
        row = index.division_by_name(name, kind)
        if row is None:
            return {
                "error": f"No division named '{name}'. Call search_locations first."
            }

        collection = store.get_geojson(row["s3_key"])
        published = await artifacts.publish_layer(
            f"division-{row['kind']}-{name}", collection["features"], complete=True
        )
        if published is None:
            return {"error": "Could not publish the boundary."}
        result = {
            "layer": {
                "id": f"division-{row['kind']}-{name}",
                "name": row["name"],
                "format": "mvt",
                "url": published.url,
                "url_expires_at": published.url_expires_at,
                "dispose_url": published.dispose_url,
                "geometry_type": "polygon",
                "feature_count": row["feature_count"],
                "bbox": row["bbox"],
                "min_zoom": published.min_zoom,
                "max_zoom": published.max_zoom,
                "attribution": f"{ATTRIBUTION} · {_SOURCES.get(row['kind'], 'swissBOUNDARIES3D')}",
            }
        }
        return result

    @server.tool()
    async def filter_features(
        layer_id: str,
        bbox: list[float] | None = None,
        lang: str = "de",
        contains: str | None = None,
        place: str | None = None,
        place_kind: str | None = None,
    ) -> dict[str, Any]:
        """Fetch features of one dataset inside a place, or inside a bounding box.

        `layer_id` comes from search_layers. Give the area one of two ways:

        - `place` (+ `place_kind`) - the `name` and `kind` of a hit from search_locations.
          **Prefer this.** The result is cut to the real boundary, so counts, figures and
          the map all describe the place itself.
        - `bbox` - WGS84 [min_lon, min_lat, max_lon, max_lat]. A rectangle, so it also
          answers with everything in the corners: asked for the communes of canton Zug it
          returns 42 of them across five cantons, against the 11 that are really there.
          Use it only for an area with no name, such as the current map view.

        `contains` optionally keeps only features with that text in their attributes.

        This fetches ALL features in the area, not a page of them, so the count it
        reports is a real total rather than a cap.

        Returns a summary plus a `result_id` handle - not the features themselves. Pass
        the handle to compute for figures, or to display_layer to put it on the map.
        """
        boundary = None
        clipped_to = None
        if place:
            row = index.division_by_name(place, place_kind)
            if row is None:
                return {
                    "error": f"No Swiss place named '{place}'. Call search_locations first."
                }
            boundary = store.get_geojson(row["s3_key"]).get("features") or []
            clipped_to = f"{row['kind']} {row['name']}"
            # The boundary decides what is inside; its box is only how much to ask for.
            bbox = bbox or row["bbox"]
        if not bbox or len(bbox) != 4:
            return {
                "error": "Give an area: `place` from search_locations, or a bbox "
                "[min_lon, min_lat, max_lon, max_lat] in WGS84."
            }

        try:
            fetched = await swisstopo.fetch_features(layer_id, bbox, lang=lang)
        except LayerNotQueryable:
            # An answerable fact, not a failure. Reported as one so the model picks a
            # different dataset instead of retrying this one until it runs out of turns.
            return {
                "feature_count": 0,
                "queryable": False,
                "note": (
                    f"Dataset '{layer_id}' cannot be queried feature-by-feature - it is "
                    "raster or image-based. Call search_layers again and choose a "
                    "vector-based dataset; do not retry this layer_id."
                ),
            }
        features = fetched.features

        if contains:
            needle = contains.lower()
            features = [
                f
                for f in features
                if any(
                    needle in str(v).lower()
                    for v in (f.get("properties") or {}).values()
                )
            ]
        # Cut after `contains` rather than before: the text filter is free and the
        # intersection is not, so it runs on the smaller set.
        if boundary is not None:
            features = clip(features, boundary)
        if not features:
            where = f"in {place}" if place else "in this area"
            return {
                "feature_count": 0,
                "note": (
                    f"Dataset '{layer_id}' returned no features {where}. It may not cover it."
                ),
            }

        entry = cache.put(
            layer_id,
            layer_id,
            features,
            complete=fetched.complete,
            limit_reason=fetched.limit_reason,
        )
        result = {
            "result_id": entry.result_id,
            "layer_id": layer_id,
            "feature_count": len(features),
            "geometry_type": geometry_type(features),
            "bbox": bounding_box(features),
            "attributes": summarise_properties(features),
            "complete": entry.complete,
            "truncated": not entry.complete,
        }
        if not entry.complete:
            reason = (entry.limit_reason or "upstream_limit").replace("_", " ")
            result["note"] = (
                f"Result stopped at {len(features)} features because of {reason}; "
                "the count is not a total. Narrow the place or dataset for a complete answer."
            )
        if clipped_to:
            result["clipped_to"] = clipped_to
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

        This is how to show raster and image layers - flood hazard, noise maps, warning
        maps - anything search_layers reports as `queryable: false`. The client renders
        it straight from swisstopo.

        Pass `focus_bbox` (from search_locations) to zoom to the area asked about: the
        layer covers all of Switzerland and cannot be subset. Use `name` to label it in
        the user's language.

        For vector data you have already fetched, use display_layer instead.
        """
        caps = await swisstopo.layers_config(lang)
        entry = caps.get(layer_id)
        if not isinstance(entry, dict):
            return {
                "error": f"'{layer_id}' is not an official layer id. Use search_layers first."
            }
        if entry.get("type") not in ("wmts", "wms", "geojson"):
            return {"error": f"'{layer_id}' cannot be rendered as a map layer."}

        layer: dict[str, Any] = {
            "id": layer_id,
            "name": name or entry.get("label") or layer_id,
            "attribution": ATTRIBUTION,
        }
        if opacity is not None:
            layer["opacity"] = opacity
        result: dict[str, Any] = {
            "catalog_layer": layer,
            "layer_type": entry.get("type"),
        }
        if focus_bbox and len(focus_bbox) == 4:
            result["focus_bbox"] = focus_bbox
        return result

    @server.tool()
    async def compute(result_id: str, operation: str = "summary") -> dict[str, Any]:
        """Compute figures over a fetched feature set.

        `operation` is one of "count", "area" (total km²), "length" (total km), "extent"
        (bounding box) or "summary" (all of them). Use this instead of estimating
        numbers yourself.
        """
        entry = cache.get(result_id)
        if entry is None:
            return {
                "error": f"Unknown result_id '{result_id}'. Call filter_features first."
            }

        wanted = operation.strip().lower()
        result: dict[str, Any] = {"result_id": result_id, "count": len(entry.features)}
        if wanted in ("area", "length", "summary"):
            result.update(measure(entry.features))
        if wanted in ("extent", "summary"):
            result["bbox"] = bounding_box(entry.features)
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
        so write it in their language. Mention in your answer what is now visible.
        """
        entry = cache.get(result_id)
        if entry is None:
            return {
                "error": f"Unknown result_id '{result_id}'. Call filter_features first."
            }

        published = await artifacts.publish_layer(
            result_id, entry.features, complete=entry.complete
        )
        if published is None:
            return {"error": "Could not publish the layer."}

        layer: dict[str, Any] = {
            "id": result_id,
            "name": name or entry.layer_id,
            "format": "mvt",
            "url": published.url,
            "url_expires_at": published.url_expires_at,
            "dispose_url": published.dispose_url,
            "geometry_type": geometry_type(entry.features),
            "feature_count": len(entry.features),
            "bbox": bounding_box(entry.features),
            "min_zoom": published.min_zoom,
            "max_zoom": published.max_zoom,
            "attribution": f"{ATTRIBUTION} · {entry.layer_id}",
            "truncated": not entry.complete,
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


def _layer_publisher() -> S3LayerPublisher:
    """Build the durable source publisher from validated deployment configuration."""
    import boto3

    bucket = os.environ.get("GEOSEARCH_S3_BUCKET", "")
    if not bucket:
        raise SystemExit(
            "GEOSEARCH_S3_BUCKET is required for generated MVT sources. "
            "For local development, point GEOSEARCH_S3_ENDPOINT and "
            "GENERATED_DATA_ENDPOINT_URL at the same S3-compatible server."
        )
    region = os.environ.get("GEOSEARCH_S3_REGION", "eu-central-1")
    endpoint = os.environ.get("GEOSEARCH_S3_ENDPOINT") or None
    client_options: dict[str, Any] = {"region_name": region}
    if endpoint is not None:
        client_options.update(
            endpoint_url=endpoint,
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
    s3 = boto3.client("s3", **client_options)
    return S3LayerPublisher(
        s3,
        bucket,
        tile_base_url=os.environ.get("GEOSEARCH_TILE_BASE_URL", "/data/tiles"),
        ttl_seconds=int(os.environ.get("GEOSEARCH_LAYER_TTL_SECONDS", "86400")),
    )


def _transport_security(port: int) -> TransportSecuritySettings:
    """Host headers `/mcp` will answer to.

    The SDK's DNS-rebinding guard allows loopback and nothing else, so in the cluster every
    POST /mcp came back `421 Misdirected Request` while GET /health stayed green: the health
    check dials 127.0.0.1, the backend dials the service by name. The name is deployment
    configuration - it differs between Service Connect, a private DNS namespace and a
    laptop - so it comes from the environment, comma separated, and `host:*` is allowed for
    any port. The loopback defaults stay so local runs and the CI smoke test keep the
    protection that is actually worth something on a workstation: nothing in the cluster can
    reach this server except the backend's security group, but a browser can reach a laptop.
    """
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
    hosts += [
        h.strip()
        for h in os.environ.get("GEOSEARCH_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    ]
    return TransportSecuritySettings(allowed_hosts=hosts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the geodata MCP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--index", default=str(INDEX_DIR))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    import uvicorn
    from starlette.responses import JSONResponse

    directory = Path(args.index)
    index = GeoIndex(directory)
    api = Swisstopo()
    publisher = _layer_publisher()
    # Boundaries are immutable build output; generated answers are private, expiring
    # source objects committed by their manifest and rendered as MVT by the backend.
    server = build_server(
        index, api, artifacts=publisher, store=BoundaryStore(directory / "s3")
    )

    counts = index.counts()
    logger.info("index: %s | %s", counts, index.embedder.model_name)
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=_transport_security(args.port),
    )
    # The MCP app serves /mcp and nothing else, and an orchestrator needs a URL it can GET
    # without speaking the protocol. Reporting the counts makes it an answer about the
    # index rather than about uvicorn: a container with no index is not healthy.
    app.router.routes.append(
        Route("/health", lambda _request: JSONResponse({"status": "ok", **counts}))
    )
    logger.info("geodata MCP server on http://%s:%d/mcp", args.host, args.port)

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
