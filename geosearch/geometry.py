"""Geometry helpers for the `compute` tool.

Areas and lengths are measured in LV95 (EPSG:2056), the projected Swiss CRS the whole
map pipeline already uses, because measuring them in degrees is meaningless.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

_POINT_TYPES = {"Point", "MultiPoint"}
_LINE_TYPES = {"LineString", "MultiLineString"}
_POLYGON_TYPES = {"Polygon", "MultiPolygon"}

# How much of a feature has to survive the cut to count as being in the place. Two
# swisstopo datasets do not agree to the metre where they meet - they are surveyed and
# maintained separately - so clipping the commune layer to the locality of Wengen leaves
# 22 m² of Grindelwald beside 34 km² of Lauterbrunnen. That is a rounding artefact, but
# a feature count cannot tell it from a commune, and the answer becomes "Wengen lies in
# two communes". A millionth is far below any real overlap and far above these.
SLIVER = 1e-6

# 0 for points, 1 for lines, 2 for areas - what `clip` compares to decide whether an
# intersection is still the kind of thing the feature was.
_DIMENSION = {
    name: dimension
    for dimension, names in enumerate((_POINT_TYPES, _LINE_TYPES, _POLYGON_TYPES))
    for name in names
}


def geometry_type(features: list[dict[str, Any]]) -> str:
    """The protocol `geometry_type` that best describes a feature set.

    Picks the most common family rather than the first feature's: a mixed set styled
    after an outlier renders badly, and points styled as polygons render invisibly.
    """
    counts = {"point": 0, "line": 0, "polygon": 0}
    for feature in features:
        kind = (feature.get("geometry") or {}).get("type")
        if kind in _POINT_TYPES:
            counts["point"] += 1
        elif kind in _LINE_TYPES:
            counts["line"] += 1
        elif kind in _POLYGON_TYPES:
            counts["polygon"] += 1
    best = max(counts, key=lambda key: counts[key])
    return best if counts[best] else "point"


def bounding_box(features: list[dict[str, Any]]) -> list[float] | None:
    """WGS84 [w, s, e, n] over every coordinate in the set."""
    lons: list[float] = []
    lats: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
                lons.append(float(node[0]))
                lats.append(float(node[1]))
                return
            for item in node:
                walk(item)

    for feature in features:
        walk((feature.get("geometry") or {}).get("coordinates"))

    if not lons or not lats:
        return None
    return [min(lons), min(lats), max(lons), max(lats)]


@lru_cache(maxsize=1)
def _to_lv95() -> Any:
    from pyproj import Transformer

    return Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)


def measure(features: list[dict[str, Any]]) -> dict[str, float]:
    """Total projected area (km²) and length (km) of a feature set."""
    from shapely.geometry import shape
    from shapely.ops import transform

    transformer = _to_lv95()
    area_m2 = 0.0
    length_m = 0.0
    for feature in features:
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        try:
            projected = transform(transformer.transform, shape(geometry))
        except Exception:
            logger.debug("skipping unprojectable geometry", exc_info=True)
            continue
        area_m2 += float(getattr(projected, "area", 0.0) or 0.0)
        length_m += float(getattr(projected, "length", 0.0) or 0.0)
    return {"area_km2": round(area_m2 / 1_000_000, 4), "length_km": round(length_m / 1_000, 4)}


def clip(
    features: list[dict[str, Any]], boundary: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every feature cut to `boundary`, dropping whatever falls outside it.

    A bounding box is a rectangle drawn around a place, so fetching by one also answers
    with the corners. Measured against the live API: the communes of canton Zug come back
    as 42 features spread over five cantons, and `compute` then sums 808 km² for a canton
    of 239. Nothing downstream can tell a neighbour from a member - they are the same
    dataset with the same attributes - so the correction has to happen here, while the
    boundary that defines "in" is still in hand.

    Cutting rather than merely filtering is what makes the figures right as well as the
    map: a forest or a river that straddles the border belongs to the place only in part.
    """
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union

    area = unary_union(
        [shape(f["geometry"]) for f in boundary if isinstance(f.get("geometry"), dict)]
    )
    if not area.is_valid:
        # Cheapest repair that keeps the outline; an invalid boundary makes every
        # intersection below raise, which would empty the result rather than trim it.
        area = area.buffer(0)

    kept: list[dict[str, Any]] = []
    for feature in features:
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        try:
            whole = shape(geometry)
            piece = _same_dimension(whole.intersection(area), geometry.get("type"))
        except Exception:
            logger.debug("skipping unclippable geometry", exc_info=True)
            continue
        if piece is not None and _fraction(piece, whole) >= SLIVER:
            kept.append({**feature, "geometry": mapping(piece)})
    return kept


def _fraction(piece: Any, whole: Any) -> float:
    """How much of a feature survived the cut: by area for polygons, length for lines.

    Always 1.0 for points, which have neither - a point is inside or it is not.
    """
    for extent in ("area", "length"):
        size = float(getattr(whole, extent, 0.0) or 0.0)
        if size:
            return float(getattr(piece, extent, 0.0) or 0.0) / size
    return 1.0


def _same_dimension(piece: Any, source_type: Any) -> Any:
    """The parts of an intersection that are still the shape the feature was, or None.

    Two polygons that share a border intersect in a *line*, and every commune touching
    the canton edge produces one. Kept, they are neighbours the user did not ask about,
    drawn as hairlines along the boundary and counted as if they were inside it.
    """
    from shapely.ops import unary_union

    if piece.is_empty:
        return None
    wanted = _DIMENSION.get(str(source_type))
    if piece.geom_type == "GeometryCollection":
        parts = [g for g in piece.geoms if _DIMENSION.get(g.geom_type) == wanted]
        return unary_union(parts) if parts else None
    return piece if _DIMENSION.get(piece.geom_type) == wanted else None


def summarise_properties(
    features: list[dict[str, Any]], *, max_keys: int = 12, max_values: int = 5
) -> dict[str, list[str]]:
    """The distinct values per attribute, so the model can see what it can filter on."""
    seen: dict[str, list[str]] = {}
    for feature in features:
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            continue
        for key, value in properties.items():
            if value is None or value == "":
                continue
            bucket = seen.setdefault(str(key), [])
            text = str(value)[:80]
            if text not in bucket and len(bucket) < max_values:
                bucket.append(text)
    return dict(list(seen.items())[:max_keys])
