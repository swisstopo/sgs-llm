"""Turning tool output into protocol `LayerSpec`s.

Matches the documented shape (fetchable GeoJSON/GeoParquet URL plus WGS84 bbox) anywhere
in a tool result rather than the bundled server's exact schema, so swisstopo's server
should need no code change here.

Anything that would fail the frontend's `isLayerSpec` guard is dropped rather than
emitted, since the browser would discard it silently.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

from ..protocol import BBox, CatalogLayerRef, LayerSpec, coerce_layer_spec

logger = logging.getLogger(__name__)

_URL_KEYS = ("url", "href", "layer_url", "data_url")
_NAME_KEYS = ("name", "title", "label", "layer_name")
_GEOMETRY_KEYS = ("geometry_type", "geometryType", "geometry")
_BBOX_KEYS = ("bbox", "bounds", "extent")

_GEOMETRY_ALIASES = {
    "point": "point",
    "multipoint": "point",
    "line": "line",
    "linestring": "line",
    "multilinestring": "line",
    "polygon": "polygon",
    "multipolygon": "polygon",
}

# Only formats the protocol declares. `parquet` stays recognised because it is stable
# in the contract, even though the frontend shows it as not yet displayable.
_EXTENSION_FORMATS = {".geojson": "geojson", ".json": "geojson", ".parquet": "parquet"}

MAX_LAYERS_PER_ANSWER = 6

_MAX_DEPTH = 6
_DEGENERATE = 1e-9
_POINT_PAD = 0.02


def _first(candidate: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in candidate and candidate[key] is not None:
            return candidate[key]
    return None


def _normalise_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        bbox = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    # WGS84 sanity check: a bbox still in LV95 metres would send the map to nowhere.
    lon_ok = -180.0 <= bbox[0] <= 180.0 and -180.0 <= bbox[2] <= 180.0
    lat_ok = -90.0 <= bbox[1] <= 90.0 and -90.0 <= bbox[3] <= 90.0
    if not (lon_ok and lat_ok):
        logger.warning("dropping bbox that is not WGS84: %s", bbox)
        return None
    west, south, east, north = bbox
    # Corners may arrive in any order, and the protocol says [minLon, minLat, maxLon,
    # maxLat]; an inverted box would make the client fit an empty extent.
    west, east = min(west, east), max(west, east)
    south, north = min(south, north), max(south, north)
    # A point result has zero area, which the client would fit at infinite zoom. Padded to
    # roughly 2 km, the same as mcp_dummy does for gazetteer hits.
    if east - west < _DEGENERATE:
        west, east = west - _POINT_PAD, east + _POINT_PAD
    if north - south < _DEGENERATE:
        south, north = south - _POINT_PAD, north + _POINT_PAD
    # Padding runs after the range check, so clamp: a point at lat 90 would otherwise be
    # padded to 90.02, which has no Web Mercator image.
    return [
        max(-180.0, west),
        max(-90.0, south),
        min(180.0, east),
        min(90.0, north),
    ]


def _clamp01(value: Any) -> float | None:
    """Opacity coerced into the 0..1 the protocol declares. Out-of-range values are
    clamped, not rejected, so a bad value costs the styling and not the layer."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(1.0, max(0.0, float(value)))


def _normalise_format(candidate: dict[str, Any], url: str) -> str | None:
    declared = candidate.get("format")
    if isinstance(declared, str) and declared.lower() in {"geojson", "parquet"}:
        return declared.lower()
    lowered = url.split("?", 1)[0].lower()
    for extension, fmt in _EXTENSION_FORMATS.items():
        if lowered.endswith(extension):
            return fmt
    return None


def _normalise_geometry(value: Any) -> str | None:
    if isinstance(value, str):
        return _GEOMETRY_ALIASES.get(value.strip().lower())
    return None


def _looks_like_layer(candidate: dict[str, Any]) -> bool:
    url = _first(candidate, _URL_KEYS)
    return isinstance(url, str) and bool(url.strip())


def _build(candidate: dict[str, Any], *, base_url: str, index: int) -> LayerSpec | None:
    raw_url = str(_first(candidate, _URL_KEYS) or "").strip()
    if not raw_url:
        return None
    # The in-memory artifact fallback returns "/data/<name>"; presigned S3 URLs are
    # already absolute and pass through untouched.
    url = urljoin(base_url, raw_url) if base_url else raw_url

    fmt = _normalise_format(candidate, url)
    if fmt is None:
        return None

    geometry = _normalise_geometry(_first(candidate, _GEOMETRY_KEYS))
    if geometry is None:
        # A wrong guess is visible but harmless for polygons and lines; for points it
        # would render them invisible, so this is logged rather than silent.
        logger.warning("tool layer %s declared no geometry_type; assuming polygon", url)
        geometry = "polygon"

    name = _first(candidate, _NAME_KEYS)
    layer_id = candidate.get("id") or candidate.get("layer_id") or f"agent-layer-{index}"

    payload: dict[str, Any] = {
        "id": str(layer_id),
        "name": str(name) if name else str(layer_id),
        "format": fmt,
        "url": url,
        "geometry_type": geometry,
    }

    bbox = _normalise_bbox(_first(candidate, _BBOX_KEYS))
    if bbox is not None:
        payload["bbox"] = bbox

    count = candidate.get("feature_count", candidate.get("count"))
    if isinstance(count, int):
        payload["feature_count"] = count

    attribution = candidate.get("attribution")
    if isinstance(attribution, str) and attribution.strip():
        payload["attribution"] = attribution.strip()

    style = candidate.get("style_hint", candidate.get("style"))
    if isinstance(style, dict):
        if "opacity" in style:
            style = {**style, "opacity": _clamp01(style["opacity"])}
        payload["style_hint"] = style

    return coerce_layer_spec(payload)


def _walk(node: Any, found: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > _MAX_DEPTH or len(found) >= MAX_LAYERS_PER_ANSWER:
        return
    if isinstance(node, dict):
        if _looks_like_layer(node):
            found.append(node)
            return
        for value in node.values():
            _walk(value, found, depth + 1)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found, depth + 1)


# An official geo.admin.ch layer id: dotted, lowercase, starts with the country prefix.
_CATALOG_ID = re.compile(r"^ch\.[a-z0-9_.-]+$")

# Only these keys mean "display this". Matching any dict merely holding a ch.* id put
# every `search_layers` candidate on the user's map, since results have that same shape.
_CATALOG_CONTAINER_KEYS = ("catalog_layer", "catalog_layers")


def extract_catalog_layers(data: Any) -> list[CatalogLayerRef]:
    """Finds official layers a tool explicitly asked to display.

    Only values under a `catalog_layer` / `catalog_layers` key count, which is the shape
    documented in docs/protocol.md. Search results are candidates, not instructions.
    """
    found: list[CatalogLayerRef] = []
    seen: set[str] = set()

    def collect(node: Any, depth: int = 0) -> None:
        if len(found) >= MAX_LAYERS_PER_ANSWER or depth > _MAX_DEPTH:
            return
        if isinstance(node, list):
            for item in node:
                collect(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        ref = _catalog_ref(node)
        if ref is not None and ref.id not in seen:
            seen.add(ref.id)
            found.append(ref)

    def visit(node: Any, depth: int = 0) -> None:
        if depth > _MAX_DEPTH or len(found) >= MAX_LAYERS_PER_ANSWER:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _CATALOG_CONTAINER_KEYS:
                    collect(value)
                else:
                    visit(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                visit(value, depth + 1)

    visit(data)
    return found


def _catalog_ref(candidate: dict[str, Any]) -> CatalogLayerRef | None:
    if _looks_like_layer(candidate):
        # It has a fetchable URL, so it belongs to extract_layers, not here.
        return None
    raw = candidate.get("id") or candidate.get("layer_id")
    if not isinstance(raw, str) or not _CATALOG_ID.match(raw):
        return None
    name = _first(candidate, _NAME_KEYS)
    attribution = candidate.get("attribution")
    return CatalogLayerRef(
        id=raw,
        name=str(name) if isinstance(name, str) and name.strip() else None,
        opacity=_clamp01(candidate.get("opacity")),
        attribution=str(attribution) if isinstance(attribution, str) else None,
    )


def extract_focus_bbox(data: Any, depth: int = 0) -> BBox | None:
    """Finds a `focus_bbox` a tool asked the camera to point at.

    Depth-limited like the other walkers: `data` is untrusted tool output, and unbounded
    recursion would turn one hostile result into a failed turn.
    """
    if depth > _MAX_DEPTH:
        return None
    if isinstance(data, dict):
        direct = _normalise_bbox(data.get("focus_bbox"))
        if direct is not None:
            return (direct[0], direct[1], direct[2], direct[3])
        for value in data.values():
            found = extract_focus_bbox(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = extract_focus_bbox(value, depth + 1)
            if found is not None:
                return found
    return None


def extract_layers(data: Any, *, base_url: str = "", start_index: int = 0) -> list[LayerSpec]:
    """Finds every displayable layer in one tool result.

    `start_index` seeds the fallback id. It has to keep counting across the tool calls of
    one turn, or two layers from different calls both become `agent-layer-0` and the
    client, which keys on id, silently renders only the first.
    """
    candidates: list[dict[str, Any]] = []
    _walk(data, candidates)

    layers: list[LayerSpec] = []
    seen: set[str] = set()
    for offset, candidate in enumerate(candidates):
        spec = _build(candidate, base_url=base_url, index=start_index + offset)
        if spec is None or spec.url in seen:
            continue
        seen.add(spec.url)
        layers.append(spec)
    return layers[:MAX_LAYERS_PER_ANSWER]
