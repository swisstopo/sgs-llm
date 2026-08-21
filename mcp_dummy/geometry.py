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
    return {
        "area_km2": round(area_m2 / 1_000_000, 4),
        "length_km": round(length_m / 1_000, 4),
    }


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
