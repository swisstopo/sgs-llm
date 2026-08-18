"""The geodata MCP server: semantic catalogue search over the pre-built index.

    python -m geosearch.build      # once
    python -m geosearch.server     # http://127.0.0.1:8790/mcp

The public tools are intent-oriented rather than mirrors of REST endpoints. Semantic
layer/area search reads the FAISS
index instead of geo.admin.ch's SearchServer, and filter_features fetches through the
grid-subdivided identify rather than a single capped request.

Tool docstrings are the descriptions the model sees, so they are written as instructions
to it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .geometry import bounding_box, clip, geometry_type, measure, summarise_properties
from .index import INDEX_DIR, GeoIndex, confidence
from .rerank import Reranker
from .results import ResultCache
from .s3 import BoundaryStore, S3Store, start_local_s3
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

# Complete feature layers only. A partial first-N layer would make the displayed map,
# count, and later analysis calls disagree with the real result.
MAX_LAYER_FEATURES = 100_000
LAYER_LIMIT_ERROR = (
    "Result contains more than 100,000 features. Narrow the place, area, or dataset."
)


def _with_clipping_scope(
    result: dict[str, Any], clipped_to: str | None
) -> dict[str, Any]:
    """Attach provenance only after the real administrative boundary was applied."""
    if clipped_to:
        result["clipped_to"] = clipped_to
    return result


_FILTER_OPERATORS = {
    "equals",
    "not_equals",
    "contains",
    "starts_with",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
}


def _apply_filters(
    features: list[dict[str, Any]], filters: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    """Apply the MCP's structured filter language without evaluating expressions."""
    available = {
        str(key)
        for feature in features
        for key in (feature.get("properties") or {})
        if isinstance(feature.get("properties"), dict)
    }
    compiled: list[tuple[str, str, Any]] = []
    for item in filters:
        if not isinstance(item, dict):
            return features, "Every filter must be an object with field, operator and value."
        field = item.get("field")
        operator = item.get("operator", "equals")
        if not isinstance(field, str) or field not in available:
            return features, f"Unknown filter field '{field}'. Available fields: {sorted(available)[:30]}"
        if operator not in _FILTER_OPERATORS:
            return features, f"Unsupported filter operator '{operator}'."
        compiled.append((field, str(operator), item.get("value")))

    def matches(feature: dict[str, Any]) -> bool:
        properties = feature.get("properties") or {}
        for field, operator, wanted in compiled:
            actual = properties.get(field)
            if operator in {"contains", "starts_with"}:
                left, right = str(actual or "").casefold(), str(wanted or "").casefold()
                if operator == "contains" and right not in left:
                    return False
                if operator == "starts_with" and not left.startswith(right):
                    return False
                continue
            if operator in {"equals", "not_equals"}:
                equal = str(actual).casefold() == str(wanted).casefold()
                if (operator == "equals" and not equal) or (operator == "not_equals" and equal):
                    return False
                continue
            try:
                left_number, right_number = float(str(actual)), float(str(wanted))
            except (TypeError, ValueError):
                return False
            if operator == "greater_than" and not left_number > right_number:
                return False
            if operator == "greater_or_equal" and not left_number >= right_number:
                return False
            if operator == "less_than" and not left_number < right_number:
                return False
            if operator == "less_or_equal" and not left_number <= right_number:
                return False
        return True

    return [feature for feature in features if matches(feature)], None


def _property_values(features: list[dict[str, Any]], field: str) -> list[Any]:
    return [
        properties[field]
        for feature in features
        if isinstance((properties := feature.get("properties")), dict)
        and field in properties
        and properties[field] is not None
    ]


def build_server(
    index: GeoIndex,
    swisstopo: Swisstopo,
    artifacts: Any,
    store: S3Store | BoundaryStore,
    reranker: Reranker | None = None,
) -> MCPServer:
    """`artifacts` publishes browser-facing GeoParquet feature layers.

    `store` is where the pre-built division boundaries live, and is separate from
    `artifacts` on purpose: artifacts is wherever this deployment publishes new layers
    (the backend swaps its own in), whereas the boundaries are build output that ships
    with the image. Only `get_geojson(key)` is used, which is why either store fits.

    Everything is injected rather than constructed here so the eval harness can swap
    those in, and so the HTTP client always has an owner that can close it.
    """
    server = MCPServer(name="sgs-llm-geodata", version="1")
    cache = ResultCache()
    location_refs: dict[str, dict[str, float]] = {}
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
        candidates = [{**h.row, "similarity": round(h.score, 4)} for h in hits]
        kept, reranked = await judge.filter(query, candidates, top_n=top_n)

        # The persisted semantic index is built from one catalogue language. Cohere is
        # multilingual, but short terms occasionally still miss across languages (live
        # example: French "crues" retrieved only Krebspest from the German index). If
        # the precision judge rejects every semantic candidate, seed a second pass from
        # SearchServer's language-specific lexical index. Try the complete phrase first,
        # then its meaningful words when SearchServer treats that phrase too literally.
        if not kept:
            lexical: list[dict[str, str]] = []
            searches = [query]
            searches.extend(
                word for word in query.split() if len(word.strip("'’-,.")) >= 4
            )
            seen_searches: set[str] = set()
            seen_layers: set[str] = set()
            for search in searches[:4]:
                normalized = search.strip("'’-,.").casefold()
                if not normalized or normalized in seen_searches:
                    continue
                seen_searches.add(normalized)
                for found in await swisstopo.search_catalog_layers(
                    search, lang, limit=CANDIDATES
                ):
                    if found["layer_id"] not in seen_layers:
                        seen_layers.add(found["layer_id"])
                        lexical.append(found)
                if len(lexical) >= CANDIDATES:
                    break

            fallback_candidates: list[dict[str, Any]] = []
            for rank, found in enumerate(lexical[:CANDIDATES]):
                row = index.layer_by_id(found["layer_id"])
                if row is None:
                    continue
                fallback_candidates.append(
                    {
                        **row,
                        "title": found["title"] or row["title"],
                        "description": found["description"] or row["description"],
                        "similarity": round(max(0.25, 0.9 - rank * 0.02), 4),
                    }
                )
            if fallback_candidates:
                kept, fallback_reranked = await judge.filter(
                    query, fallback_candidates, top_n=top_n
                )
                reranked = reranked or fallback_reranked

        layers = [
            {
                "layer_ref": f"layer:{row['layer_id']}",
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
        # These are suggestions, not automatic map mutations. The backend forwards the
        # references as inline chat actions so every named result can be shown without
        # reopening the Geocatalog; the user still chooses whether to add it.
        result["layer_refs"] = [
            {
                "id": layer["layer_id"],
                "name": layer["title"],
                "attribution": layer["data_owner"] or "geo.admin.ch",
            }
            for layer in layers
            if layer["displayable"]
        ]
        if not layers:
            result["note"] = (
                f"Nothing in the swisstopo catalogue matches '{query}'. Try a broader "
                "subject word rather than a longer phrase."
            )
            return result
        if not reranked:
            # The agent is choosing from a raw vector ranking, which contains
            # near-misses by design. It should know that before it trusts rank 1.
            result["note"] = (
                "Ranked by vector similarity only - the relevance filter was "
                "unavailable, so check each candidate against the question yourself."
            )
        return result

    @server.tool()
    async def geocode_location(
        query: str,
        origins: list[str] | None = None,
        lang: str = "de",
        limit: int = 5,
    ) -> dict[str, Any]:
        """Resolve a precise Swiss address, parcel, postcode, or named point.

        Use this for an address or parcel, never search_locations: search_locations finds
        areas for clipping, while this tool returns explicit WGS84 longitude/latitude and
        LV95 easting/northing. `origins` may contain address, parcel, zipcode, gazetteer,
        gg25, district, or kantone; prefer ["address"] for a street address. Each result
        includes a `result_id` for a personalized point marker. If the user asks to show
        the geocoded place, pass that exact id directly to display_layer; do not replace
        it with a nationwide catalog layer.
        """
        if not query.strip():
            return {"error": "Give a non-empty address, parcel, postcode, or place name."}
        allowed_origins = {
            "address", "parcel", "zipcode", "gazetteer", "gg25", "district", "kantone"
        }
        invalid_origins = sorted(set(origins or []) - allowed_origins)
        if invalid_origins:
            return {"error": f"Unsupported location origins: {invalid_origins}."}
        locations = await swisstopo.geocode_location(
            query, origins=origins, lang=lang, limit=limit
        )
        for location in locations:
            ref = location.get("location_ref")
            coordinates = location.get("coordinates") or {}
            wgs84 = coordinates.get("wgs84") or {}
            if isinstance(ref, str):
                try:
                    longitude = float(wgs84["longitude"])
                    latitude = float(wgs84["latitude"])
                    location_refs[ref] = {
                        "longitude": longitude,
                        "latitude": latitude,
                    }
                    related = location.get("related_features") or []
                    source_layer = next(
                        (
                            str(item["layer_id"])
                            for item in related
                            if isinstance(item, dict) and item.get("layer_id")
                        ),
                        "geocode-location",
                    )
                    label = str(location.get("label") or ref)
                    entry = cache.put(
                        source_layer,
                        label,
                        [
                            {
                                "type": "Feature",
                                "id": ref,
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [longitude, latitude],
                                },
                                "properties": {
                                    "label": label,
                                    "location_ref": ref,
                                    "kind": location.get("kind"),
                                    "match_quality": location.get("match_quality"),
                                },
                            }
                        ],
                    )
                    location["result_id"] = entry.result_id
                    location["display_scope"] = "geocoded_point"
                    location["display_note"] = (
                        "Personalized point marker for this geocoded result. Pass this "
                        "exact result_id to display_layer when the user asks to show the "
                        "address; do not use display_catalog_layer as a substitute."
                    )
                except (KeyError, TypeError, ValueError):
                    pass
        return {
            "locations": locations,
            "note": (
                "SearchServer matches are candidates, not an independently verified "
                "address certificate. Prefer an exact match with official related features."
            ),
        }

    @server.tool()
    async def describe_layer(layer_id: str, lang: str = "de") -> dict[str, Any]:
        """Inspect one official GeoAdmin layer before querying it.

        Returns its description, owner, complete field schema, render/query capability,
        timestamps, legend, details, and download link. Use it when field names or the
        meaning and availability of a dataset matter; do not guess attribute names.
        """
        layer = await swisstopo.describe_layer(layer_id, lang)
        if layer is None:
            return {"error": f"Unknown official layer '{layer_id}'. Call search_layers first."}
        return {"layer": layer}

    @server.tool()
    async def identify_at_point(
        layer_ids: list[str],
        location_ref: str | None = None,
        longitude: float | None = None,
        latitude: float | None = None,
        lang: str = "de",
        return_geometry: bool = False,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Return complete feature records from selected layers at one exact point.

        Prefer `location_ref` from geocode_location; otherwise give WGS84 longitude and
        latitude explicitly. Unlike filter_features this does not summarize properties,
        so official PDF and web fields such as ÖREB extract links are preserved. When
        the user asks to show the identified result, set `return_geometry: true`; the
        response then includes a `result_id` that can be passed to display_layer. That
        personalized result is separate from the nationwide official catalog layer.
        """
        if location_ref:
            point = location_refs.get(location_ref)
            if point is None:
                return {"error": "Unknown location_ref. Call geocode_location in this session first."}
            longitude, latitude = point["longitude"], point["latitude"]
        if longitude is None or latitude is None:
            return {"error": "Give location_ref or WGS84 longitude and latitude."}
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            return {"error": "longitude/latitude are not valid WGS84 coordinates."}
        if not layer_ids or len(layer_ids) > 10 or any(
            not isinstance(layer_id, str) or not layer_id.startswith("ch.")
            for layer_id in layer_ids
        ):
            return {"error": "Give between 1 and 10 official ch.* layer ids."}
        features = await swisstopo.identify_at_point(
            layer_ids,
            longitude,
            latitude,
            lang=lang,
            return_geometry=return_geometry,
            limit=limit,
        )
        display_result: dict[str, Any] = {}
        if return_geometry:
            geometries = [feature for feature in features if isinstance(feature.get("geometry"), dict)]
            # Identify may return both the parcel and its enclosing municipality from
            # the same ÖREB layer. Prefer the parcel record carrying its EGRID/extract
            # links so the personalized result zooms to the parcel, not all of Köniz.
            specific = [
                feature
                for feature in geometries
                if (feature.get("properties") or {}).get("egris_egrid")
                or any(
                    str(link.get("field", "")).startswith("oereb_extract_")
                    for link in feature.get("external_links") or []
                    if isinstance(link, dict)
                )
            ]
            selected = specific or geometries
            geojson_features: list[dict[str, Any]] = []
            for feature in selected:
                reference = feature.get("feature_ref") or {}
                properties = dict(feature.get("properties") or {})
                properties["source_layer_id"] = reference.get("layer_id")
                properties["source_feature_id"] = reference.get("feature_id")
                geojson_features.append(
                    {
                        "type": "Feature",
                        "id": reference.get("feature_id"),
                        "geometry": feature["geometry"],
                        "properties": properties,
                    }
                )
            if geojson_features:
                source_ids = {
                    str((feature.get("feature_ref") or {}).get("layer_id"))
                    for feature in selected
                }
                source_id = next(iter(source_ids)) if len(source_ids) == 1 else "point-identify"
                title = next(
                    (str(feature["layer_name"]) for feature in selected if feature.get("layer_name")),
                    source_id,
                )
                entry = cache.put(source_id, title, geojson_features)
                display_result["result_id"] = entry.result_id
                display_result["display_feature_count"] = len(geojson_features)
                display_result["display_scope"] = "oereb_parcel" if specific else "identified_features"
                display_result["display_note"] = (
                    "This personalized result contains the exact ÖREB parcel polygon "
                    "carrying the EGRID, not the enclosing municipality boundary. Pass "
                    "result_id to display_layer. display_catalog_layer is the separate "
                    "official nationwide availability map."
                    if specific
                    else "This is a personalized feature result for the queried point. "
                    "Pass result_id to display_layer; display_catalog_layer is a separate "
                    "official nationwide map layer."
                )
        # Geometry can be a municipality-sized polygon with thousands of coordinates.
        # It stays in the server-side result cache; sending it through the model hid the
        # result_id beyond the useful context and caused invented handles. Properties and
        # official links remain complete in the agent-facing records.
        response_features = [
            {key: value for key, value in feature.items() if key != "geometry"}
            for feature in features
        ]
        result: dict[str, Any] = {
            "point": {"longitude": longitude, "latitude": latitude},
            "feature_count": len(features),
            **display_result,
            "features": response_features,
        }
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
        """Prepare an administrative boundary as a clickable chat map layer.

        `name` is a place from search_locations; `kind` is one of "land", "kanton",
        "bezirk", "gemeinde", "ortschaft" and disambiguates the many cases where one name
        names several levels (Zug and Bern are a commune and a canton; Zürich is also a
        district and a locality).

        The boundary polygons were downloaded once at build time, so this does not call
        geo.admin.ch. This returns a map `layer`, not a feature `result_id`; never pass
        its layer id to analyze_features. Only filter_features produces analyzable
        result ids.
        """
        row = index.division_by_name(name, kind)
        if row is None:
            return {
                "error": f"No division named '{name}'. Call search_locations first."
            }

        collection = store.get_geojson(row["s3_key"])
        features = collection.get("features") or []
        url = await artifacts.publish_geoparquet(
            f"division-{row['kind']}-{name}.parquet", features
        )
        if url is None:
            return {"error": "Could not publish the layer."}
        return {
            "layer": {
                "id": f"division-{row['kind']}-{name}",
                "name": row["name"],
                "format": "parquet",
                "url": url,
                "geometry_type": "Polygon",
                "feature_count": row["feature_count"],
                "bbox": row["bbox"],
                "attribution": f"{ATTRIBUTION} · {_SOURCES.get(row['kind'], 'swissBOUNDARIES3D')}",
            }
        }

    @server.tool()
    async def filter_features(
        layer_id: str,
        bbox: list[float] | None = None,
        lang: str = "de",
        contains: str | None = None,
        place: str | None = None,
        place_kind: str | None = None,
        filters: list[dict[str, Any]] | None = None,
        time: str | None = None,
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

        `filters` is a list of safe structured filters with `field`, `operator`, and
        `value`. Supported operators: equals, not_equals, contains, starts_with,
        greater_than, greater_or_equal, less_than, less_or_equal. Never pass a raw API
        expression. `contains` remains as a compatibility-wide text search.

        This fetches ALL features in the area, not a page of them, so the count it
        reports is a real total rather than a cap.

        Returns a summary plus a `result_id` handle - not the features themselves. Pass
        the handle to analyze_features for figures, or to display_layer to put it on the map.
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
            features = await swisstopo.fetch_features(
                layer_id, bbox, lang=lang, time_instant=time
            )
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
        if filters and features:
            features, filter_error = _apply_filters(features, filters)
            if filter_error:
                return {"error": filter_error}
        # Cut after `contains` rather than before: the text filter is free and the
        # intersection is not, so it runs on the smaller set.
        if boundary is not None:
            features = clip(features, boundary)
        if not features:
            where = f"in {place}" if place else "in this area"
            return _with_clipping_scope(
                {
                    "feature_count": 0,
                    "note": (
                        f"Dataset '{layer_id}' returned no features {where}. It may not cover it."
                    ),
                },
                clipped_to,
            )

        if len(features) > MAX_LAYER_FEATURES:
            return _with_clipping_scope(
                {
                    "error": LAYER_LIMIT_ERROR,
                    "feature_count": len(features),
                    "limit": MAX_LAYER_FEATURES,
                },
                clipped_to,
            )

        entry = cache.put(layer_id, layer_id, features)
        result = {
            "result_id": entry.result_id,
            "layer_id": layer_id,
            "feature_count": len(features),
            "geometry_type": geometry_type(features),
            "bbox": bounding_box(features),
            "attributes": summarise_properties(features),
        }
        return _with_clipping_scope(result, clipped_to)

    @server.tool()
    async def display_catalog_layer(
        layer_id: str,
        lang: str = "de",
        name: str | None = None,
        opacity: float | None = None,
        focus_bbox: list[float] | None = None,
    ) -> dict[str, Any]:
        """Offer an official geo.admin.ch layer through a clickable title in chat.

        This is how to show raster and image layers - flood hazard, noise maps, warning
        maps - anything search_layers reports as `queryable: false`. After the user
        clicks Add map layer, the client renders it straight from swisstopo.

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
    async def analyze_features(
        result_id: str,
        operation: str = "summary",
        field: str | None = None,
        metrics: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Compute trustworthy figures over a fetched feature set.

        Operations are summary, count, area, length, extent, group_by,
        numeric_statistics, and top_values. group_by/top_values require `field`;
        numeric_statistics returns count, missing, min, max, mean and sum. Use this
        instead of estimating or counting values from filter_features' preview.
        """
        entry = cache.get(result_id)
        if entry is None:
            return {
                "error": (
                    f"Unknown result_id '{result_id}'. Call filter_features, or call "
                    "identify_at_point with return_geometry=true, first."
                )
            }

        wanted = operation.strip().lower()
        allowed = {
            "summary", "count", "area", "length", "extent", "group_by",
            "numeric_statistics", "top_values",
        }
        if wanted not in allowed:
            return {"error": f"Unsupported analysis operation '{operation}'."}
        result: dict[str, Any] = {"result_id": result_id, "count": len(entry.features)}
        if wanted in ("area", "length", "summary"):
            result.update(measure(entry.features))
        if wanted in ("extent", "summary"):
            result["bbox"] = bounding_box(entry.features)
        if wanted in {"group_by", "top_values", "numeric_statistics"}:
            if not field:
                return {"error": f"operation '{wanted}' requires field."}
            values = _property_values(entry.features, field)
            missing = len(entry.features) - len(values)
            result.update({"field": field, "missing_values": missing})
            if wanted == "top_values":
                counts = Counter(str(value) for value in values)
                rows = [
                    {"value": value, "count": count}
                    for value, count in counts.most_common(max(1, min(limit, 100)))
                ]
                result["values"] = rows
            elif wanted == "group_by":
                grouped: dict[str, list[dict[str, Any]]] = {}
                for feature in entry.features:
                    properties = feature.get("properties") or {}
                    if not isinstance(properties, dict) or properties.get(field) is None:
                        continue
                    grouped.setdefault(str(properties[field]), []).append(feature)
                requested_metrics = set(metrics or ["count"])
                rows = []
                for value, group in grouped.items():
                    row: dict[str, Any] = {"value": value}
                    if "count" in requested_metrics:
                        row["count"] = len(group)
                    if requested_metrics & {"area", "area_km2", "length", "length_km"}:
                        measured = measure(group)
                        if requested_metrics & {"area", "area_km2"}:
                            row["area_km2"] = measured.get("area_km2", 0.0)
                        if requested_metrics & {"length", "length_km"}:
                            row["length_km"] = measured.get("length_km", 0.0)
                    rows.append(row)
                def group_sort_key(row: dict[str, Any]) -> tuple[int, str]:
                    count = row.get("count")
                    return (-count if isinstance(count, int) else 0, str(row["value"]))

                rows.sort(key=group_sort_key)
                result["groups"] = rows[: max(1, min(limit, 100))]
            else:
                numbers = []
                for value in values:
                    if isinstance(value, bool):
                        continue
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(number):
                        numbers.append(number)
                if not numbers:
                    return {"error": f"Field '{field}' has no numeric values."}
                selected = set(metrics or ["min", "max", "mean", "sum"])
                statistics: dict[str, Any] = {"numeric_count": len(numbers)}
                if "min" in selected:
                    statistics["min"] = min(numbers)
                if "max" in selected:
                    statistics["max"] = max(numbers)
                if "mean" in selected:
                    statistics["mean"] = sum(numbers) / len(numbers)
                if "sum" in selected:
                    statistics["sum"] = sum(numbers)
                result["statistics"] = statistics
        return result

    @server.tool()
    async def display_layer(
        result_id: str,
        name: str,
        fill_color: str | None = None,
        opacity: float | None = None,
    ) -> dict[str, Any]:
        """Offer a fetched feature set as a clickable result layer in chat.

        Call this once you have data worth showing. `name` is the label the user sees,
        so write it in their language. The user then chooses Show result on map.
        """
        entry = cache.get(result_id)
        if entry is None:
            return {
                "error": (
                    f"Unknown result_id '{result_id}'. Call filter_features, or call "
                    "identify_at_point with return_geometry=true, first."
                )
            }

        url = await artifacts.publish_geoparquet(f"{result_id}.parquet", entry.features)
        if url is None:
            return {"error": "Could not publish the layer."}

        layer: dict[str, Any] = {
            "id": result_id,
            "name": name or entry.layer_id,
            "format": "parquet",
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


def _artifact_store() -> S3Store:
    """Where published layers go: the real bucket if one is named, moto if not.

    `GEOSEARCH_S3_BUCKET` is the switch because it is the one thing that has to be set for
    real S3 to work at all. A task definition that names the bucket is a deployment;
    anything else is a workstation with no credentials for it.
    """
    if os.environ.get("GEOSEARCH_S3_BUCKET"):
        return S3Store()
    try:
        return start_local_s3()
    except ModuleNotFoundError as exc:
        # moto is in requirements-dev.txt, not requirements.txt, so the deployed image
        # does not carry a test double. Reaching here means it was started without being
        # told where to publish - say that, rather than naming a package nobody installed
        # on purpose.
        raise SystemExit(
            "No GEOSEARCH_S3_BUCKET set, and the local S3 stand-in is unavailable "
            f"({exc}). Set GEOSEARCH_S3_BUCKET to publish to real S3, or install "
            "geosearch/requirements-dev.txt for local development."
        ) from exc


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
    from starlette.routing import Route

    directory = Path(args.index)
    index = GeoIndex(directory)
    api = Swisstopo()
    # Two stores, because they hold two different things: `store` is the build's own
    # boundaries, read-only and shipped with the image, `artifacts` is where answers get
    # published for the browser. They were one object only while both were moto.
    server = build_server(
        index, api, artifacts=_artifact_store(), store=BoundaryStore(directory / "s3")
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
