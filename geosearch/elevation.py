"""Route selection, LV95 projection and validation of sampled elevation profiles."""

from __future__ import annotations

import math
from typing import Any

from pyproj import Transformer

PROFILE_URL = "https://api3.geo.admin.ch/rest/services/profile.json"
MAX_VERTICES = 5_000
MAX_SAMPLES = 200
_TO_LV95 = Transformer.from_crs(4326, 2056, always_xy=True)


class RouteSelectionRequired(ValueError):
    def __init__(
        self, message: str, candidates: list[dict[str, Any]], total: int
    ) -> None:
        super().__init__(message)
        self.candidates = candidates[:20]
        self.total = total


def select_route(
    features: list[dict[str, Any]], feature_index: int | None, part_index: int | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    if feature_index is None:
        if len(features) != 1:
            candidates = [
                {
                    "feature_index": i,
                    "feature_id": f.get("id"),
                    "name": (f.get("properties") or {}).get("name"),
                    "geometry_type": (f.get("geometry") or {}).get("type"),
                }
                for i, f in enumerate(features[:20])
            ]
            raise RouteSelectionRequired(
                "Choose one route with feature_index, or narrow filter_features first.",
                candidates,
                len(features),
            )
        feature_index = 0
    if not 0 <= feature_index < len(features):
        raise ValueError("feature_index is outside this result.")
    feature = features[feature_index]
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates")
    scope: dict[str, Any] = {
        "feature_index": feature_index,
        "scope": "whole line feature",
    }
    if geometry.get("type") == "MultiLineString" and isinstance(
        coordinates, (list, tuple)
    ):
        if part_index is None and len(coordinates) != 1:
            raise RouteSelectionRequired(
                "Choose a MultiLineString part_index; separate parts are never joined across gaps.",
                [
                    {"part_index": i, "vertex_count": len(part)}
                    for i, part in enumerate(coordinates[:20])
                ],
                len(coordinates),
            )
        part_index = 0 if part_index is None else part_index
        if not 0 <= part_index < len(coordinates):
            raise ValueError("part_index is outside this line feature.")
        scope.update(
            part_index=part_index,
            part_count=len(coordinates),
            scope="selected line part",
        )
        coordinates = coordinates[part_index]
    elif geometry.get("type") != "LineString":
        raise ValueError(
            "Elevation profiles require a LineString or a selected MultiLineString part."
        )
    elif part_index is not None:
        raise ValueError("part_index is only valid for a MultiLineString.")
    return {
        **feature,
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }, scope


def project_route(geometry: dict[str, Any]) -> dict[str, Any]:
    coordinates = geometry.get("coordinates")
    if geometry.get("type") != "LineString" or not isinstance(
        coordinates, (list, tuple)
    ):
        raise ValueError("A LineString is required.")
    if not 2 <= len(coordinates) <= MAX_VERTICES:
        raise ValueError("Choose a route with between 2 and 5,000 vertices.")
    projected = []
    for point in coordinates:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ValueError("Invalid route coordinate.")
        x, y = point[:2]
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in (x, y)):
            raise ValueError("Route coordinates must be finite WGS84 numbers.")
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            raise ValueError("Route coordinates must be WGS84 longitude/latitude.")
        easting, northing = _TO_LV95.transform(x, y)
        if not math.isfinite(easting) or not math.isfinite(northing):
            raise ValueError("Route coordinates could not be projected to LV95.")
        projected.append([easting, northing])
    if sum(math.dist(a, b) for a, b in zip(projected, projected[1:])) == 0:
        raise ValueError("The route has zero length.")
    return {"type": "LineString", "coordinates": projected}


def summarize_profile(payload: Any, route: dict[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(payload, list)
        or not 2 <= len(payload) <= MAX_VERTICES + MAX_SAMPLES + 2
    ):
        raise ValueError(
            "The elevation service did not return a bounded, complete profile."
        )
    points = []
    for row in payload:
        if not isinstance(row, dict) or not isinstance(row.get("alts"), dict):
            raise ValueError("The elevation profile is missing sample data.")
        values = [
            row.get("dist"),
            row["alts"].get("COMB"),
            row.get("easting"),
            row.get("northing"),
        ]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError(
                "The elevation profile contains missing or invalid measurements."
            )
        points.append({"distance_m": float(values[0]), "elevation_m": float(values[1])})
    distances = [p["distance_m"] for p in points]
    if (
        distances[0] != 0
        or distances[-1] <= 0
        or any(a > b for a, b in zip(distances, distances[1:]))
    ):
        raise ValueError("The elevation profile has invalid or unordered distances.")
    coordinates = route["coordinates"]
    for sample, endpoint in (
        (payload[0], coordinates[0]),
        (payload[-1], coordinates[-1]),
    ):
        if math.dist([sample["easting"], sample["northing"]], endpoint) > 2:
            raise ValueError(
                "The elevation profile does not cover both route endpoints."
            )
    expected_length = sum(math.dist(a, b) for a, b in zip(coordinates, coordinates[1:]))
    if abs(distances[-1] - expected_length) > max(2, expected_length * 0.001):
        raise ValueError(
            "The elevation profile does not cover the complete route length."
        )
    heights = [p["elevation_m"] for p in points]
    changes = [b - a for a, b in zip(heights, heights[1:])]
    # The service may return every source vertex (HTTP 203) when there are more
    # vertices than requested samples. Compute metrics from all rows, then bound the
    # model-facing series without discarding measurements from the totals.
    series = points
    if len(points) > MAX_SAMPLES:
        series = [
            points[round(i * (len(points) - 1) / (MAX_SAMPLES - 1))]
            for i in range(MAX_SAMPLES)
        ]
    return {
        "complete": True,
        "sample_count": len(points),
        "returned_sample_count": len(series),
        "samples_summarized": len(series) < len(points),
        "distance_m": round(distances[-1], 1),
        "min_elevation_m": min(heights),
        "max_elevation_m": max(heights),
        "ascent_m": round(sum(max(0, d) for d in changes), 1),
        "descent_m": round(sum(max(0, -d) for d in changes), 1),
        "samples": series,
        "source_url": PROFILE_URL,
        "attribution": "swisstopo / geo.admin.ch",
        "note": "Ascent and descent are estimates from sampled elevations in the line's coordinate order.",
    }
